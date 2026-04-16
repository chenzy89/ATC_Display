"""
ATC Display - 空管雷达态势显示系统
从 UDP 组播接收 CAT062 数据并实时显示

入口文件: python -m atc_display

窗体布局:
  GIW (54px)     ← 屏幕顶部, 置顶
  ASD            ← 全屏背景 (覆盖任务栏), show() 后 lower() 位于最底
  CLW (30px)     ← 屏幕底部, 置顶, Quit 按钮退出程序
  Replay         ← 浮动窗口, 置顶, GIW Replay 按钮触发
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

# 确保包能被导入：将项目根目录添加到 sys.path
# 无论通过 python -m atc_display 还是直接运行此文件都能工作
_PROJECT_ROOT = Path(__file__).parent.parent  # /home/share/ATC_Display
_parent_str = str(_PROJECT_ROOT)
if _parent_str not in sys.path:
    sys.path.insert(0, _parent_str)

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from atc_display.config import load_app_config
from atc_display.asd_widget import ASDWidget
from atc_display.giw_widget import GIWWidget
from atc_display.clw_widget import CLWWidget
from atc_display.replay_widget import ReplayWidget
from atc_display.wx_map import WXMapManager
from atc_display.maps_widget import MapsWidget


def setup_logging() -> None:
    """配置日志
    
    支持通过 DEBUG 环境变量控制日志级别:
      DEBUG=1 python -m atc_display  # 启用调试日志
    """
    import os
    debug_mode = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
    log_level = logging.DEBUG if debug_mode else logging.INFO
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler()],
    )
    
    if debug_mode:
        logging.getLogger("atc_display").debug("调试模式已启用")


def main() -> None:
    setup_logging()
    logger = logging.getLogger("atc_display")

    # 加载配置
    try:
        config = load_app_config()
    except Exception as exc:
        logger.error("加载配置失败: %s", exc)
        return

    logger.info("=== ATC Display 启动 ===")
    logger.info("组播地址: %s:%d", config.network.multicast_ip, config.network.multicast_port)
    logger.info("地图中心: (%.4f, %.4f)", config.map.center_lat, config.map.center_lon)
    logger.info("比例尺: %d 米/像素", config.map.scale)

    # 创建 Qt 应用
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # 获取主屏幕的真实物理尺寸
    primary_screen = app.primaryScreen()
    screen_rect = primary_screen.geometry()   # 覆盖任务栏的完整分辨率
    available_rect = primary_screen.availableGeometry()  # 去除系统装饰的可用区域

    # ── 创建各窗体 ──
    asd = ASDWidget(config)
    giw = GIWWidget()
    clw = CLWWidget()

    # ── MAPS WINDOW ──
    def on_maps_changed(map_names):
        """地图选择变化: 重新加载地图并刷新显示"""
        asd.reload_maps(map_names)

    maps_win = MapsWidget(
        map_data_dir=Path(config.map.map_data_dir),
        on_maps_changed=on_maps_changed,
    )

    # 加载 CurrentMaps.txt 中的默认地图
    default_maps = maps_win.get_current_maps()
    if default_maps:
        asd.load_maps(default_maps)
    else:
        asd.load_maps()  # 使用 config 中的默认地图

    # ── 云图 (Weather Map) ──
    wx_map = WXMapManager(wx_base_path=config.map.wx_base_path)
    wx_map.wx_updated.connect(asd.invalidate_background)
    asd.set_wx_map(wx_map)

    # 气象 UDP 接收线程
    wx_port = config.network.wx_port
    wx_thread = None
    wx_sock = None  # type: Optional[socket.socket]
    
    if wx_port > 0:
        import socket
        import threading

        def _wx_udp_receiver():
            """气象 UDP 接收: buf.Length > 1 → 云图文件名 → 加载并刷新背景"""
            nonlocal wx_sock
            try:
                wx_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                wx_sock.bind(("0.0.0.0", wx_port))
                wx_sock.settimeout(2.0)
                logger.info("气象 UDP 接收线程已启动, 端口=%d", wx_port)
                
                while True:
                    try:
                        data, _ = wx_sock.recvfrom(1024)
                    except socket.timeout:
                        continue
                    except OSError:
                        break
                    
                    if len(data) > 1:
                        # 长报文: 云图文件名 (MMddHHmm 格式 ASCII)
                        filename = data.decode("ascii", errors="ignore").strip()
                        logger.info("收到气象文件名: %s", filename)
                        try:
                            if wx_map.load_png(filename):
                                wx_map.wx_updated.emit()
                        except Exception as exc:
                            logger.error("处理气象文件 %s 失败: %s", filename, exc)
                    # else: 单字节控制指令 (旧项目中用于地图切换等, 暂不处理)
            except Exception as exc:
                logger.error("气象 UDP 接收线程异常: %s", exc)
            finally:
                if wx_sock:
                    try:
                        wx_sock.close()
                    except OSError:
                        pass
                logger.info("气象 UDP 接收线程已退出")

        wx_thread = threading.Thread(target=_wx_udp_receiver, daemon=True)
        wx_thread.start()
    else:
        logger.info("气象 UDP 端口未配置 (wx_port=0), 跳过云图接收线程")

    # ── Replay 窗体 回调 ──
    def on_replay_time_update(replay_dt):
        giw.set_replay_time(replay_dt)

    def on_replay_frame(payloads, replay_time):
        asd.feed_replay_frames(payloads, replay_time)

    def on_load_start():
        """Replay 窗体 Load: ASD 进入回放模式 (暂停 UDP + 清空航迹 + 加载起始云图)"""
        asd.enter_replay_mode()
        # 加载开始时间之前最近的云图
        try:
            from datetime import datetime
            start_time = datetime.strptime(replay.edt_time.text().strip(), "%Y-%m-%d %H:%M:%S")
            asd.load_wx_for_replay_start(start_time)
        except Exception as exc:
            logger.warning("加载回放起始云图失败: %s", exc)

    def on_replay_stop(finished=False):
        """
        Replay 窗体 Stop/结束:
        - finished=False: 用户点击 Stop，退出回放模式，恢复实时
        - finished=True: 回放自然结束，清空ASD，保持replay状态
        """
        if finished:
            # 回放结束: 清空航迹，保持 replay 状态
            asd.track_store.tracks.clear()
            asd.track_count = 0
            asd.update()
            logger.info("回放结束: ASD 已清空，保持 replay 状态")
        else:
            # 用户点击 Stop: 退出回放模式，恢复实时
            asd.exit_replay_mode()
            giw.set_replay_time(None)
            giw._toggle_mode(realtime=True)

    replay = ReplayWidget(
        on_load_start=on_load_start,
        on_stop=on_replay_stop,
        on_frame=on_replay_frame,
        on_time_update=on_replay_time_update,
    )

    # ── GIW Replay / Realtime 按钮联动 ──
    def on_giw_replay_clicked():
        """GIW Replay 按钮额外逻辑: 暂停 UDP、清空航迹、弹出 Replay 窗体"""
        asd.enter_replay_mode()
        replay.show_at_top_left(offset_y=giw.height())

    def on_giw_realtime_clicked():
        """GIW Realtime 按钮额外逻辑: 退出回放模式、恢复 UDP、关闭 Replay 窗体"""
        if replay.isVisible():
            replay.hide()
        asd.exit_replay_mode()
        giw.set_replay_time(None)

    # 追加连接: GIW 内部 _toggle_mode 保持不变, 此处叠加回放逻辑
    giw.rdb_replay.clicked.connect(on_giw_replay_clicked)
    giw.rdb_realtime.clicked.connect(on_giw_realtime_clicked)

    # ── GIW VEL 按钮: 控制预计线显示 ──
    def on_vel_button_toggled(checked):
        """VEL 按钮切换: 切换预计线显示并更新预计时间"""
        predict_time = giw.get_predict_time_minutes()
        asd.set_predict_line_enabled(checked)
        asd.set_predict_time(predict_time)
        # 更新 VEL 按钮的样式
        giw._style_toggle_btn(giw.btn_vel, active=checked)
        logger.info("预计线 %s, 预计时间: %d 分钟", "已启用" if checked else "已禁用", predict_time)

    giw.btn_vel.toggled.connect(on_vel_button_toggled)
    
    # ── GIW VEL 输入框: 当输入框内容改变时更新预计时间 ──
    def on_vel_time_changed():
        """VEL 时间输入框变化: 更新预计时间"""
        if giw.is_predict_line_enabled():
            predict_time = giw.get_predict_time_minutes()
            asd.set_predict_time(predict_time)
            logger.debug("预计时间已更新: %d 分钟", predict_time)

    giw.tbx_vel.textChanged.connect(on_vel_time_changed)

    # ── CLW Replay 按钮: 仅切换 Replay 窗体显隐 ──
    def toggle_replay_visibility():
        if replay.isVisible():
            replay.hide()
        else:
            replay.show_at_top_left(offset_y=giw.height())

    clw.btn_replay.clicked.connect(toggle_replay_visibility)

    # ── CLW Maps 按钮: 显示/隐藏 MAPS WINDOW ──
    def toggle_maps_window():
        if maps_win.isVisible():
            maps_win.hide()
        else:
            # 定位到 GIW 下方
            maps_win.move(available_rect.left(), available_rect.top() + giw.height())
            maps_win.show()

    clw.btn_maps.clicked.connect(toggle_maps_window)

    # ── 鼠标坐标 100ms 同步到 GIW ──
    coord_timer = QTimer()
    coord_timer.timeout.connect(lambda: giw.update_coordinates(*asd.get_mouse_geo_str()))
    coord_timer.start(100)

    # ── 显示并定位 ──
    # GIW / CLW 先 show, 然后 ASD show + lower()
    # lower() 只影响同进程窗口的 Z 序, 不影响其他应用窗口
    # 使用 screen_rect (完整屏幕坐标) 而非 available_rect, 确保覆盖系统菜单栏
    
    giw.setFixedWidth(screen_rect.width())
    giw.show()
    giw.move(screen_rect.left(), -1)

    clw.setFixedWidth(screen_rect.width())
    clw.show()
    clw.move(screen_rect.left(), screen_rect.bottom() - clw.height() + 1)

    asd.show()
    getattr(asd, 'raise')()      # 提升到最前 (解决被 VSCode 等遮挡的问题)
    asd.activateWindow()         # 激活窗体
    asd.lower()                  # 再压到同进程窗口最底层 (GIW/CLW 保持在其上方)

    # 确保 GIW/CLW 仍在 ASD 上方
    getattr(giw, 'raise')()
    getattr(clw, 'raise')()

    # ── 启动 UDP 接收 ──
    asd.start_receive()

    logger.info("窗口已显示, 使用 CLW 的 Quit 按钮退出")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
