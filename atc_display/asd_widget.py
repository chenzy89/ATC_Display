"""
ATC 雷达态势显示主窗口 (ASD - Air Situation Display)
对应 C# Frm_ASD + MapRadar 的双缓冲渲染
V0.1: 航迹符号 + 标牌 + 地图背景
"""
from __future__ import annotations

import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QPointF, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush, QPixmap, QPainterPath,
    QFontMetrics, QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from .cat062 import RadarTrack
from .config import AppConfig
from .geometry import RealPoint, GeoTransform, cal_angle, pixel_point_from_pixel
from .map_data import (
    MapElement, load_map_file, get_qcolor,
    COLOR_CONTROLLED, COLOR_ASSUMED, COLOR_UNCONTROLLED, COLOR_BACKGROUND,
)
from .udp_receiver import CAT062Receiver

logger = logging.getLogger("atc_display.asd")

# === 航迹超时及处理 ===
TRACK_TIMEOUT_SECONDS = 10  # 超过10秒未更新则消失
TRAIL_JUMP_FILTER_M = 5000  # 航迹跳变过滤距离 (米)
TRAIL_MAX_POINTS = 20       # 历史航迹点最大数量

# === 字体 ===
SYS_FONT_FAMILY = "SimSun"
SYS_FONT_SIZE = 10
MAP_STR_FONT_SIZE = 10
LABEL_FONT_FAMILY = "SimSun"
LABEL_FONT_SIZE = 10

# === 渲染定时器 ===
RENDER_INTERVAL_MS = 200   # 5 FPS (与 C# 保持一致, 降低 CPU 占用)
UDP_POLL_INTERVAL_MS = 50  # UDP 轮询间隔

# === SSR 过滤范围 ===
SSR_MAX_VALUE = 7776  # SSR 最大有效值 (0000-7777)


class TrackStore:
    """
    航迹数据存储
    对应 C# CommonFun.List_FDR
    """
    def __init__(self):
        self.tracks: Dict[int, RadarTrack] = {}  # track_number -> RadarTrack

    def update_tracks(self, new_tracks: List[RadarTrack]) -> int:
        """
        更新航迹数据, 返回新增数量
        对应 C# CAT062.Decode() 末尾的 List_FDR 更新逻辑
        """
        new_count = 0
        now = datetime.now()
        for track in new_tracks:
            track.last_update_time = now
            # 过滤 7776+ 的 SSR (有效范围: 0000-7777)
            if int(track.ssr) >= SSR_MAX_VALUE:
                continue

            if track.track_number in self.tracks:
                # 更新已有航迹 - 将新数据复制到旧对象中，保持对象引用有效（用于测距线与航迹关联）
                old = self.tracks[track.track_number]
                # 判断高度变化状态
                old_fl = old.flight_level_m
                new_fl = track.flight_level_m
                if round(new_fl / 10) > round(old_fl / 10):
                    new_level_status = 'c'
                elif round(new_fl / 10) < round(old_fl / 10):
                    new_level_status = 'd'
                else:
                    new_level_status = 'm'

                # 保留历史航迹点
                track.trail_points = old.trail_points.copy()
                # 添加当前点到历史
                if track.latitude != 0 or track.longitude != 0:
                    curr_pt = RealPoint(track.latitude, track.longitude)
                    if len(track.trail_points) >= 2:
                        last = track.trail_points[-2]
                        last_pt = RealPoint(last[0], last[1]) if isinstance(last, tuple) else last
                        dist = curr_pt.distance_to(last_pt)
                        # 过滤跳变 (距离 > TRAIL_JUMP_FILTER_M)
                        if dist > TRAIL_JUMP_FILTER_M:
                            track.trail_points[-1] = (track.latitude, track.longitude)
                        else:
                            track.trail_points[-1] = (track.latitude, track.longitude)
                    track.trail_points.append((track.latitude, track.longitude))
                    # 限制历史点数量
                    if len(track.trail_points) > TRAIL_MAX_POINTS:
                        track.trail_points = track.trail_points[-TRAIL_MAX_POINTS:]

                # 保留显示属性
                old.offset_x = getattr(old, 'offset_x', 20.0)
                old.offset_y = getattr(old, 'offset_y', -20.0)
                old.selected = getattr(old, 'selected', False)
                old.dragging = getattr(old, 'dragging', False)
                old.show_predict_line = getattr(old, 'show_predict_line', False)

                # 将新数据复制到旧对象中，保持对象引用有效（用于测距线与航迹关联）
                old.target_id = track.target_id
                old.acid = track.acid
                old.ssr = track.ssr
                old.latitude = track.latitude
                old.longitude = track.longitude
                old.speed_kmh = track.speed_kmh
                old.heading_deg = track.heading_deg
                old.spdx_kmh = track.spdx_kmh
                old.spdy_kmh = track.spdy_kmh
                old.flight_level_m = track.flight_level_m
                old.qnh_height_m = track.qnh_height_m
                old.qnh_applied = track.qnh_applied
                old.selected_altitude_m = track.selected_altitude_m
                old.cfl_m = track.cfl_m
                old.aircraft_type = track.aircraft_type
                old.wtc = track.wtc
                old.adep = track.adep
                old.adst = track.adst
                old.runway = track.runway
                old.sector_index = track.sector_index
                old.sid = track.sid
                old.star = track.star
                old.flight_plan_correlated = track.flight_plan_correlated
                old.time_of_track = track.time_of_track
                old.received_at = track.received_at
                old.level_status = new_level_status
                old.trail_points = track.trail_points
                old.last_update_time = now
                # self.tracks[track.track_number] 保持对 old 的引用，无需重新赋值
            else:
                # 新航迹
                track.offset_x = 20.0
                track.offset_y = -20.0
                track.level_status = 'm'
                track.trail_points = [(track.latitude, track.longitude)]
                track.show_predict_line = False  # 新航迹默认不显示预计线，通过点击标牌速度字段启用
                self.tracks[track.track_number] = track
                new_count += 1

        return new_count


class ASDWidget(QWidget):
    """
    空管雷达态势显示主窗口
    对应 C# Frm_ASD + MapRadar 双缓冲渲染
    """

    # 地图平移步长 (像素)
    PAN_STEP = 50
    # 比例尺范围 (米/像素)
    SCALE_MIN = 50
    SCALE_MAX = 1000
    SCALE_STEP = 10
    # 标牌点击检测半径 (像素)
    CLICK_RADIUS = 10
    # 引线长度预设 (像素): 短/中/长
    LEADER_LENGTHS = [25, 50, 80]
    # 8 方向: (dx, dy) 像素偏移
    LABEL_DIRECTIONS = [
        (1, -1),   # 右上
        (1, 0),    # 右
        (1, 1),    # 右下
        (0, 1),    # 下
        (-1, 1),   # 左下
        (-1, 0),   # 左
        (-1, -1),  # 左上
        (0, -1),   # 上
    ]

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        self.config = config
        self.track_store = TrackStore()

        # === 坐标转换器 ===
        # 使用 geometry() (真实物理分辨率) 而非 availableGeometry(), 以覆盖任务栏
        screen = self.screen().geometry()
        self.screen_w = screen.width()
        self.screen_h = screen.height()
        center = RealPoint(config.map.center_lat, config.map.center_lon)
        self.geo = GeoTransform(center, config.map.scale, self.screen_w, self.screen_h)
        self.mag_var = config.map.magnetic_variation

        # === 字体 ===
        self.sys_font = QFont(SYS_FONT_FAMILY, SYS_FONT_SIZE)
        self.map_font = QFont(SYS_FONT_FAMILY, MAP_STR_FONT_SIZE)
        self.label_font = QFont(LABEL_FONT_FAMILY, LABEL_FONT_SIZE)
        self.label_font_metrics = QFontMetrics(self.label_font)

        # === 双缓冲位图 ===
        self.bg_pixmap = QPixmap(self.screen_w, self.screen_h)
        self.fg_pixmap = QPixmap(self.screen_w, self.screen_h)

        # === 地图数据 ===
        self.map_elements: List[MapElement] = []
        self._bg_dirty = True  # 背景需要重绘

        # === 云图 ===
        self._wx_map = None  # WXMapManager, 由 set_wx_map() 设置

        # === UDP 接收器 ===
        self.receiver: Optional[CAT062Receiver] = None
        self.track_count = 0

        # === 交互状态 ===
        self._dragging_label = False    # 是否正在拖拽标牌
        self._drag_track = None         # 正在拖拽的航迹

        # === 测距状态 ===
        # 正在绘制的测距线（最多2个点）: 每个点为 (real_pt, track_or_None)
        self._measure_points: List[Tuple[RealPoint, Optional[RadarTrack]]] = []
        # 已完成的测距线列表（最多20条）: 每条线为 ((起点, track), (终点, track))
        self._completed_measure_lines: List[Tuple[Tuple[RealPoint, Optional[RadarTrack]], Tuple[RealPoint, Optional[RadarTrack]]]] = []
        self._measure_active = False    # 是否正在绘制中 (已按第一次中键, 等待第二次)
        self._measure_temp_end = None   # 测距过程中的临时终点 (real_pt, track_or_None)
        # 存储完成线的信息框位置用于双击检测
        self._measure_info_boxes: List[Tuple[float, float, float, float]] = []  # (x, y, w, h)

        # === 预计线 ===
        self.predict_line_enabled = False  # 全局预计线显示开关
        self.predict_time_minutes = 1      # 预计时间，单位分钟
        self.wx_visible = True             # 云图显示开关

        # === 高度过滤 ===
        self.label_filter_enabled = False
        self.label_filter_min_m = 0
        self.label_filter_max_m = 10000
        
        # === 标牌点击检测 ===
        # 记录标牌第二行速度字段的点击区域: {track_number: (x, y, width, height)}
        self._label_clickable_areas: Dict[int, Tuple[float, float, float, float]] = {}

        # === 鼠标位置追踪 (供 GIW 显示坐标) ===
        self._mouse_geo = RealPoint(0.0, 0.0)  # 鼠标对应的地理坐标
        self._mouse_pos = (0, 0)  # 鼠标屏幕坐标

        # === 窗口属性 (无边框, 全屏背景; show() 后 lower() 放到同级最底) ===
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setStyleSheet(f"background-color: rgb({COLOR_BACKGROUND[0]},{COLOR_BACKGROUND[1]},{COLOR_BACKGROUND[2]});")
        # 用 geometry() 覆盖任务栏区域
        self.setGeometry(screen)

    def load_maps(self, map_names: Optional[List[str]] = None) -> None:
        """
        加载地图文件
        map_names: 指定地图名称列表 (不含 draw_ 前缀), None 则使用 config.map.map_files
        """
        self.map_elements.clear()
        map_dir = Path(self.config.map.map_data_dir)

        names = map_names if map_names is not None else self.config.map.map_files

        for map_name in names:
            # 支持带或不带 draw_ 前缀
            if map_name.startswith("draw_"):
                filepath = map_dir / f"{map_name}.txt"
            else:
                filepath = map_dir / f"draw_{map_name}.txt"

            elements = load_map_file(filepath)
            self.map_elements.extend(elements)

        self._bg_dirty = True
        logger.info("共加载 %d 个地图元素 (来自 %d 个地图文件)", len(self.map_elements), len(names))

    def reload_maps(self, map_names: List[str]) -> None:
        """
        重新加载指定地图 (MAPS WINDOW 选择变化时调用)
        """
        self.load_maps(map_names)
        self.update()  # 触发重绘

    def set_wx_map(self, wx_map) -> None:
        """
        设置云图管理器并加载最新云图。
        wx_map: WXMapManager 实例
        """
        self._wx_map = wx_map
        wx_map.load_latest()
        self._bg_dirty = True

    def invalidate_background(self) -> None:
        """标记背景为失效, 下次渲染时将重新绘制"""
        self._bg_dirty = True

    def set_wx_visible(self, visible: bool) -> None:
        """设置云图显示开关"""
        self.wx_visible = visible
        self._bg_dirty = True
        self.update()

    def start_receive(self) -> None:
        """启动 CAT062 数据接收"""
        net = self.config.network
        self.receiver = CAT062Receiver(
            multicast_ip=net.multicast_ip,
            multicast_port=net.multicast_port,
            bind_host=net.bind_host,
            interface_ip=net.interface_ip,
            on_tracks=self._on_tracks_received,
        )
        self.receiver.start()

        # UDP 轮询定时器
        self._udp_timer = QTimer(self)
        self._udp_timer.timeout.connect(self._poll_udp)
        self._udp_timer.start(UDP_POLL_INTERVAL_MS)

        # 渲染定时器
        self._render_timer = QTimer(self)
        self._render_timer.timeout.connect(self.update)
        self._render_timer.start(RENDER_INTERVAL_MS)

    def stop_receive(self) -> None:
        """停止接收"""
        if self.receiver:
            self.receiver.stop()
        if hasattr(self, '_udp_timer'):
            self._udp_timer.stop()
        if hasattr(self, '_render_timer'):
            self._render_timer.stop()

    # ============== 预计线控制 ==============
    def set_predict_line_enabled(self, enabled: bool) -> None:
        """设置全局预计线显示开关"""
        self.predict_line_enabled = enabled
        self.update()

    def set_predict_time(self, minutes: int) -> None:
        """设置预计时间（分钟）"""
        if minutes > 0:
            self.predict_time_minutes = minutes
            self.update()

    def set_label_filter_enabled(self, enabled: bool) -> None:
        """设置高度过滤开关"""
        self.label_filter_enabled = enabled
        self.update()

    def set_label_filter_bounds(self, min_m: int, max_m: int) -> None:
        """设置高度过滤边界（米）"""
        self.label_filter_min_m = min(min_m, max_m)
        self.label_filter_max_m = max(min_m, max_m)
        self.update()

    def _is_track_within_label_filter(self, track: RadarTrack) -> bool:
        if not self.label_filter_enabled:
            return True
        height_m = track.flight_level_m or track.qnh_height_m
        if height_m <= 0:
            return False
        return self.label_filter_min_m <= height_m <= self.label_filter_max_m

    def toggle_track_predict_line(self, track: RadarTrack) -> None:
        """切换单个航迹的预计线显示状态"""
        track.show_predict_line = not getattr(track, 'show_predict_line', False)
        self.update()

    # ============== 回放模式 ==============
    def enter_replay_mode(self) -> None:
        """
        进入回放模式:
          1. 停止 UDP 接收 (保留渲染定时器)
          2. 清空所有航迹
          3. 清空云图
        """
        # 停止 UDP 轮询 (不停渲染定时器, 保持屏幕刷新)
        if self.receiver:
            self.receiver.stop()
        if hasattr(self, '_udp_timer'):
            self._udp_timer.stop()

        # 启动渲染定时器 (如果还没启动)
        if not hasattr(self, '_render_timer') or not self._render_timer.isActive():
            self._render_timer = QTimer(self)
            self._render_timer.timeout.connect(self.update)
            self._render_timer.start(RENDER_INTERVAL_MS)

        # 清空航迹
        self.track_store.tracks.clear()
        self.track_count = 0
        self._drag_track = None
        self._dragging_label = False

        # 清空云图
        if self._wx_map:
            self._wx_map.clear()
            self._bg_dirty = True

        logger.info("已进入回放模式, UDP 已暂停, 航迹和云图已清空")

    def exit_replay_mode(self) -> None:
        """
        退出回放模式:
          1. 清空航迹
          2. 加载最新云图
          3. 重新启动 UDP 接收
        """
        # 清空航迹
        self.track_store.tracks.clear()
        self.track_count = 0
        self._drag_track = None
        self._dragging_label = False

        # 加载最新云图
        if self._wx_map:
            self._wx_map.load_latest()
            self._bg_dirty = True

        # 重启 UDP
        self.start_receive()
        logger.info("已退出回放模式, 最新云图已加载, UDP 已恢复")

    def feed_replay_frames(self, payloads: list, replay_time) -> None:
        """
        回放引擎调用此方法喂入雷达帧 payload。
        payloads: List[bytes], 每个 bytes 是一帧 CAT062 原始报文
        replay_time: datetime, 当前回放时间 (用于超时判断)
        """
        from .cat062 import Cat062Parser
        if not hasattr(self, '_replay_parser'):
            self._replay_parser = Cat062Parser()

        now = replay_time if replay_time else datetime.now()

        # ── 云图同步加载 ──
        if self._wx_map and replay_time:
            self._sync_wx_map(replay_time)

        # 记录正在拖拽的航迹编号
        dragging_track_number = None
        if self._drag_track and self._dragging_label:
            dragging_track_number = self._drag_track.track_number

        for payload in payloads:
            try:
                tracks = self._replay_parser.parse_datagram(payload)
                if tracks:
                    for t in tracks:
                        t.last_update_time = now
                    self.track_store.update_tracks(tracks)
            except Exception as exc:
                logger.debug("回放帧解析失败: %s", exc)

        # 更新被拖拽航迹的引用，确保拖拽状态在航迹更新后仍然保持
        if dragging_track_number is not None and dragging_track_number in self.track_store.tracks:
            self._drag_track = self.track_store.tracks[dragging_track_number]
        else:
            self._drag_track = None
            self._dragging_label = False

        self.track_count = len(self.track_store.tracks)
        # 回放时也做超时清理 (基于回放时间)
        expired = [
            tn for tn, t in self.track_store.tracks.items()
            if t.last_update_time and (now - t.last_update_time).total_seconds() > TRACK_TIMEOUT_SECONDS
        ]
        for tn in expired:
            t = self.track_store.tracks[tn]
            if t is self._drag_track:
                continue
            del self.track_store.tracks[tn]
        if expired:
            self.track_count = len(self.track_store.tracks)

    def _sync_wx_map(self, replay_time: datetime) -> None:
        """
        回放时同步加载云图: 当回放时间的 HHmm 与云图文件名一致时加载
        """
        if not self._wx_map:
            return

        # 当前回放时间的云图名称: MMddHHmm
        wx_name = replay_time.strftime("%m%d%H%M")

        # 如果当前显示的云图已经是这个时间的，不重复加载
        if self._wx_map.current_name == wx_name:
            return

        # 尝试加载对应时间的云图
        if self._wx_map.load_png(wx_name):
            self._bg_dirty = True
            logger.debug("回放云图已同步: %s", wx_name)

    def load_wx_for_replay_start(self, start_time: datetime) -> None:
        """
        回放开始时加载开始时间之前最近的云图
        """
        if not self._wx_map:
            return

        # 扫描当日云图目录，找到 start_time 之前最新的云图
        dir_name = start_time.strftime("%m%d")  # MMdd
        wx_dir = self._wx_map._base_path / dir_name

        if not wx_dir.exists():
            logger.warning("回放开始: 云图目录不存在 %s", wx_dir)
            return

        png_files = sorted(wx_dir.glob("*.PNG"))
        if not png_files:
            logger.warning("回放开始: 当日无云图文件 %s", wx_dir)
            return

        # 找到 start_time 之前最新的云图
        start_hhmm = start_time.strftime("%H%M")
        latest_before = None
        for f in png_files:
            hhmm = f.stem  # HHmm
            if hhmm <= start_hhmm:
                latest_before = f
            else:
                break

        if latest_before:
            name = dir_name + latest_before.stem  # MMdd + HHmm
            if self._wx_map.load_png(name):
                self._bg_dirty = True
                logger.info("回放开始: 已加载最近云图 %s", name)
        else:
            # 如果没有找到 start_time 之前的，加载最早的
            earliest = png_files[0]
            name = dir_name + earliest.stem
            if self._wx_map.load_png(name):
                self._bg_dirty = True
                logger.info("回放开始: 已加载最早云图 %s", name)

    def _on_tracks_received(self, tracks: List[RadarTrack]) -> None:
        """收到航迹数据的回调"""
        logger.debug("收到回调: 传入 %d 条航迹数据", len(tracks))
        
        # 记录正在拖拽的航迹编号
        dragging_track_number = None
        if self._drag_track and self._dragging_label:
            dragging_track_number = self._drag_track.track_number
        
        new_count = self.track_store.update_tracks(tracks)
        self.track_count = len(self.track_store.tracks)
        if new_count > 0:
            logger.debug("新增 %d 条航迹, 当前共 %d 条航迹", new_count, self.track_count)
        else:
            logger.debug("更新 %d 条现有航迹, 当前共 %d 条航迹", len(tracks) - new_count, self.track_count)
        
        # 更新被拖拽航迹的引用，确保拖拽状态在航迹更新后仍然保持
        if dragging_track_number is not None and dragging_track_number in self.track_store.tracks:
            self._drag_track = self.track_store.tracks[dragging_track_number]
        else:
            # 如果拖拽的航迹已被清理，结束拖拽
            self._drag_track = None
            self._dragging_label = False
        
        # 清理过期航迹
        self._expire_old_tracks()
        
        # 触发重绘以显示最新的航迹位置（包括与测距线关联的航迹）
        self.update()

    def _expire_old_tracks(self) -> None:
        """清理超过10秒未更新的航迹"""
        now = datetime.now()
        expired = [
            tn for tn, t in self.track_store.tracks.items()
            if t.last_update_time and (now - t.last_update_time).total_seconds() > TRACK_TIMEOUT_SECONDS
        ]
        
        # 收集被删除的航迹对象
        expired_tracks = []
        for tn in expired:
            # 如果该航迹正在被拖拽, 不清理
            track = self.track_store.tracks[tn]
            if track is self._drag_track:
                continue
            expired_tracks.append(track)
            del self.track_store.tracks[tn]
        
        # 删除与过期航迹相关联的测距线
        if expired_tracks:
            lines_to_delete = []
            for idx, (pt1, pt2) in enumerate(self._completed_measure_lines):
                # 检查任一端点是否关联了被删除的航迹
                if (pt1[1] in expired_tracks) or (pt2[1] in expired_tracks):
                    lines_to_delete.append(idx)
            
            # 反向删除（从后往前）避免索引变化
            for idx in reversed(lines_to_delete):
                del self._completed_measure_lines[idx]
        
        if expired:
            self.track_count = len(self.track_store.tracks)

    def _poll_udp(self) -> None:
        """轮询 UDP socket"""
        if self.receiver:
            count = self.receiver.poll()
            if count > 0:
                logger.debug("UDP 轮询: 收到 %d 个报文", count)

    # ============== 渲染 ==============
    def paintEvent(self, event) -> None:
        """主渲染函数 - 双缓冲"""
        # 清空旧的标牌点击区域（每帧重新计算）
        self._label_clickable_areas.clear()
        
        if self._bg_dirty:
            self._draw_background()
            self._bg_dirty = False

        # 前景: 复制背景 + 画航迹
        self.fg_pixmap.fill(Qt.transparent)
        fg_painter = QPainter(self.fg_pixmap)
        fg_painter.setRenderHint(QPainter.Antialiasing, True)
        fg_painter.drawPixmap(0, 0, self.bg_pixmap)
        self._draw_aircraft(fg_painter)
        self._draw_measure(fg_painter)
        fg_painter.end()

        # 输出到屏幕
        screen_painter = QPainter(self)
        screen_painter.drawPixmap(0, 0, self.fg_pixmap)
        screen_painter.end()

    def _draw_background(self) -> None:
        """绘制静态背景 (地图 + 云图)"""
        self.bg_pixmap.fill(QColor(*COLOR_BACKGROUND))
        painter = QPainter(self.bg_pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # ── 云图 (Weather Map) ──
        if self._wx_map and self.wx_visible:
            self._wx_map.draw(painter, self.geo)

        # ── 地图  ── 
        for elem in self.map_elements:
            self._draw_map_element(painter, elem)

        painter.end()

    def _draw_map_element(self, painter: QPainter, elem: MapElement) -> None:
        """绘制单个地图元素"""
        r, g, b = get_qcolor(elem.color_index)
        color = QColor(r, g, b)
        pen = QPen(color, elem.width)
        brush = QBrush(color)

        # 线型
        style_map = {
            0: Qt.PenStyle.SolidLine,
            1: Qt.PenStyle.CustomDashLine,
            2: Qt.PenStyle.CustomDashLine,
            3: Qt.PenStyle.CustomDashLine,
            4: Qt.PenStyle.CustomDashLine,
        }
        pen.setStyle(style_map.get(elem.style, Qt.PenStyle.SolidLine))
        if elem.style == 1:
            pen.setDashPattern([8, 6])
        elif elem.style == 2:
            pen.setDashPattern([3, 5])
        elif elem.style == 3:
            pen.setDashPattern([8, 6, 3, 6])
        elif elem.style == 4:
            pen.setDashPattern([8, 6, 3, 6, 3, 6])

        # 抗锯齿: 圆头圆角
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        painter.setPen(pen)

        if elem.element_type == 0:
            # GTXT - 文字
            self._draw_map_text(painter, elem, color)
        elif elem.element_type == 1:
            # GV - 线段
            self._draw_map_line(painter, elem)
        elif elem.element_type == 2:
            # GST - 定位点
            self._draw_map_fix(painter, elem, color)
        elif elem.element_type == 3:
            # GC - 圆
            self._draw_map_circle(painter, elem, color)
        elif elem.element_type == 4:
            # GA - 弧 (三点定弧)
            self._draw_map_arc(painter, elem, color)
        elif elem.element_type == 5:
            # GAR - 弧 (圆心+半径+角度)
            self._draw_map_arc_center(painter, elem, color)
        elif elem.element_type == 6:
            # GR - 航路 (多点连线)
            self._draw_map_route(painter, elem)
        elif elem.element_type == 7:
            # GP - 多边形
            self._draw_map_polygon(painter, elem)

    def _draw_map_text(self, painter: QPainter, elem: MapElement, color: QColor) -> None:
        """绘制地图文字"""
        if not elem.points:
            return
        pt = elem.points[0]
        px, py = self.geo.real_to_pixel(pt)
        painter.setFont(self.map_font)
        painter.setPen(color)
        text = elem.labels[0] if elem.labels else elem.name
        painter.drawText(int(px), int(py), text)

    def _draw_map_line(self, painter: QPainter, elem: MapElement) -> None:
        """绘制地图线段"""
        if len(elem.points) < 2:
            return
        p1 = self.geo.real_to_pixel(elem.points[0])
        p2 = self.geo.real_to_pixel(elem.points[1])
        painter.drawLine(QPointF(*p1), QPointF(*p2))

    def _draw_map_fix(self, painter: QPainter, elem: MapElement, color: QColor) -> None:
        """
        绘制定位点 (GST)
        根据 elem.style 区分不同类型:
        0: 实心正方形 (DrawFix0)
        2: 实心三角形 (DrawFix2)
        3: VOR符号 - 菱形+方框+圆 (DrawFix3)
        4: NDB符号 - 圆+放射线 (DrawFix4)
        32: 空心三角形 (DrawFix32)
        100: 空心三角形 (DrawFix100)
        101: 实心三角形 (DrawFix101)
        102: 空心正方形 (DrawFix102)
        103: 实心正方形 (DrawFix103)
        104: 空心正方形+十字线 (DrawFix104)
        105: 圆+中心点 (DrawFix105)
        106: 圆+上方T字 (DrawFix106)
        107: 直升机场 - 圆+十字 (DrawFix107)
        108: 双圆 (DrawFix108)
        109: 圆+十字 (DrawFix109)
        110: 实心方块+十字线 (DrawFix110)
        111: 空心方块+十字线 (DrawFix111)
        112: X形十字 (DrawFix112)
        """
        if not elem.points:
            return
        px, py = self.geo.real_to_pixel(elem.points[0])
        ix, iy = int(px), int(py)

        style = elem.style
        pen = painter.pen()
        brush = QBrush(color)

        if style == 0:
            # 实心正方形 2x2 (DrawFix0)
            painter.fillRect(ix - 2, iy - 2, 5, 5, color)

        elif style == 2 or style == 101:
            # 实心三角形 (DrawFix2/DrawFix101)
            triangle = QPainterPath()
            triangle.moveTo(ix, iy - 6)
            triangle.lineTo(ix - 5, iy + 5)
            triangle.lineTo(ix + 5, iy + 5)
            triangle.closeSubpath()
            painter.fillPath(triangle, brush)

        elif style == 3:
            # VOR符号 - 菱形+方框+圆+十字 (DrawFix3)
            # 菱形
            painter.setBrush(Qt.NoBrush)   # 取消填充
            painter.setPen(Qt.SolidLine)  # 实线
            diamond = QPainterPath()
            diamond.moveTo(ix, iy - 5)
            diamond.lineTo(ix + 5, iy)
            diamond.lineTo(ix, iy + 5)
            diamond.lineTo(ix - 5, iy)
            diamond.closeSubpath()
            painter.drawPath(diamond)
            # 方框
            painter.drawRect(ix - 5, iy - 5, 10, 10)
            # # 外圆
            painter.drawEllipse(QPointF(px, py), 8, 8)
            # 十字 (4个点)
            painter.drawPoint(ix - 6, iy)
            painter.drawPoint(ix + 6, iy)
            painter.drawPoint(ix, iy - 6)
            painter.drawPoint(ix, iy + 6)

        elif style == 4:
            # NDB符号 - 圆+放射线 (DrawFix4)
            painter.drawEllipse(QPointF(px, py), 3, 3)
            # 放射线 (8个方向)
            for angle_deg in [0, 45, 90, 135, 180, 225, 270, 315]:
                angle_rad = math.radians(angle_deg)
                x1 = ix + int(6 * math.cos(angle_rad))
                y1 = iy - int(6 * math.sin(angle_rad))
                x2 = ix + int(8 * math.cos(angle_rad))
                y2 = iy - int(8 * math.sin(angle_rad))
                painter.drawLine(x1, y1, x2, y2)

        elif style == 32 or style == 100:
            # 空心三角形 (DrawFix32/DrawFix100)
            triangle = QPainterPath()
            triangle.moveTo(ix, iy - 6)
            triangle.lineTo(ix - 5, iy + 5)
            triangle.lineTo(ix + 5, iy + 5)
            triangle.closeSubpath()
            painter.drawPath(triangle)

        elif style == 102:
            # 空心正方形 (DrawFix102)
            painter.drawRect(ix - 6, iy - 6, 12, 12)

        elif style == 103:
            # 实心正方形 (DrawFix103)
            painter.fillRect(ix - 6, iy - 6, 12, 12, color)

        elif style == 104:
            # 空心正方形+十字线 (DrawFix104)
            painter.drawRect(ix - 6, iy - 6, 12, 12)
            painter.drawLine(ix - 6, iy, ix + 6, iy)

        elif style == 105:
            # 圆+中心点 (DrawFix105)
            painter.drawEllipse(QPointF(px, py), 7, 7)
            painter.fillRect(ix - 3, iy - 3, 6, 6, color)

        elif style == 106:
            # 圆+上方T字 (DrawFix106)
            painter.drawEllipse(QPointF(px, py), 5, 5)
            painter.drawLine(ix, iy - 6, ix, iy - 15)
            painter.drawLine(ix - 5, iy - 13, ix, iy - 15)

        elif style == 107:
            # 直升机场 - 圆+十字 (DrawFix107)
            painter.drawEllipse(QPointF(px, py), 5, 5)
            painter.drawLine(ix, iy - 5, ix, iy - 8)
            painter.drawLine(ix, iy + 5, ix, iy + 8)
            painter.drawLine(ix - 5, iy, ix - 8, iy)
            painter.drawLine(ix + 5, iy, ix + 8, iy)

        elif style == 108:
            # 双圆 (DrawFix108)
            painter.drawEllipse(QPointF(px, py), 7, 7)
            painter.drawEllipse(QPointF(px, py), 3, 3)

        elif style == 109:
            # 圆+十字 (DrawFix109)
            painter.drawEllipse(QPointF(px, py), 7, 7)
            painter.drawLine(ix, iy - 7, ix, iy - 4)
            painter.drawLine(ix, iy + 7, ix, iy + 4)
            painter.drawLine(ix - 7, iy, ix - 4, iy)
            painter.drawLine(ix + 7, iy, ix + 4, iy)

        elif style == 110:
            # 实心方块+十字线 (DrawFix110)
            painter.fillRect(ix - 3, iy - 3, 7, 7, color)
            painter.drawLine(ix, iy - 7, ix, iy + 7)
            painter.drawLine(ix - 7, iy, ix + 7, iy)

        elif style == 111:
            # 空心方块+十字线 (DrawFix111)
            painter.drawRect(ix - 6, iy - 6, 12, 12)
            painter.drawLine(ix, iy - 6, ix, iy - 3)
            painter.drawLine(ix, iy + 6, ix, iy + 3)
            painter.drawLine(ix - 6, iy, ix - 3, iy)
            painter.drawLine(ix + 6, iy, ix + 3, iy)

        elif style == 112:
            # X形十字 (DrawFix112)
            painter.drawLine(ix, iy - 6, ix, iy + 6)
            painter.drawLine(ix - 6, iy, ix + 6, iy)
            painter.drawLine(ix - 6, iy - 6, ix + 6, iy + 6)
            painter.drawLine(ix - 6, iy + 6, ix + 6, iy - 6)

        else:
            # 默认: 实心正方形
            painter.fillRect(ix - 2, iy - 2, 5, 5, color)

        # 标注文本: 优先显示 labels[0]（第5字段，如"650M"），无则显示 name（第4字段）
        painter.setFont(self.map_font)
        painter.setPen(color)
        # 逻辑: labels[0] 存在就用它，否则用 name
        text = (elem.labels[0] if elem.labels else "") or elem.name
        if text:
            # 移除引号
            text = text.replace('"', '')
            painter.drawText(ix - 2, iy + 20, text)
     
    def _draw_map_circle(self, painter: QPainter, elem: MapElement, color: QColor) -> None:
        """绘制圆"""
        if len(elem.points) < 2:
            return
        center = elem.points[0]
        edge = elem.points[1]
        dist_m = center.distance_to(edge)
        radius_px = self.geo.distance_to_pixels(dist_m)
        cx, cy = self.geo.real_to_pixel(center)
        filled = bool(elem.rsv1)
        if filled:
            painter.setBrush(QColor(96, 96, 96, 100))  # 半透明填充
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), radius_px, radius_px)

    def _draw_map_route(self, painter: QPainter, elem: MapElement) -> None:
        """绘制航路 (多点连线)"""
        if len(elem.points) < 2:
            return
        path = QPainterPath()
        px, py = self.geo.real_to_pixel(elem.points[0])
        path.moveTo(px, py)
        for pt in elem.points[1:]:
            px, py = self.geo.real_to_pixel(pt)
            path.lineTo(px, py)
        painter.drawPath(path)

    def _draw_map_arc(self, painter: QPainter, elem: MapElement, color: QColor) -> None:
        """
        绘制三点定弧 (GA)
        points[0] = 起点, points[1] = 弧上点, points[2] = 终点
        通过 3 点求圆心和半径, 再用 QPainterPath.arcTo 绘制
        """
        if len(elem.points) < 3:
            return

        p0 = self.geo.real_to_pixel(elem.points[0])
        p1 = self.geo.real_to_pixel(elem.points[1])
        p2 = self.geo.real_to_pixel(elem.points[2])

        # 将像素坐标转为 float
        ax, ay = float(p0[0]), float(p0[1])
        bx, by = float(p1[0]), float(p1[1])
        cx, cy = float(p2[0]), float(p2[1])

        # 三点求圆心 (中垂线交点)
        # 临时坐标系: y 翻转 (屏幕坐标 y 向下)
        ax2, ay2 = ax, -ay
        bx2, by2 = bx, -by
        cx2, cy2 = cx, -cy

        d = 2.0 * (ax2 * (by2 - cy2) + bx2 * (cy2 - ay2) + cx2 * (ay2 - by2))
        if abs(d) < 1e-10:
            # 三点近似共线, 退化画直线
            path = QPainterPath()
            path.moveTo(ax, ay)
            path.lineTo(cx, cy)
            painter.drawPath(path)
            return

        ux = ((ax2 * ax2 + ay2 * ay2) * (by2 - cy2) +
              (bx2 * bx2 + by2 * by2) * (cy2 - ay2) +
              (cx2 * cx2 + cy2 * cy2) * (ay2 - by2)) / d
        uy = ((ax2 * ax2 + ay2 * ay2) * (cx2 - bx2) +
              (bx2 * bx2 + by2 * by2) * (ax2 - cx2) +
              (cx2 * cx2 + cy2 * cy2) * (bx2 - ax2)) / d

        center_x = ux
        center_y = -uy  # 翻转回屏幕坐标

        radius = math.sqrt((ax - center_x) ** 2 + (ay - center_y) ** 2)

        # 计算起止角 (屏幕坐标系, 顺时针为正, Qt 也是顺时针)
        start_angle = math.degrees(math.atan2(-(ay - center_y), ax - center_x))
        end_angle = math.degrees(math.atan2(-(cy - center_y), cx - center_x))

        # 将弧上点也转为角度, 确定弧的方向
        mid_angle = math.degrees(math.atan2(-(by - center_y), bx - center_x))

        # 计算从 start 到 end 的两个可能扫过角度
        diff_ccw = (end_angle - start_angle) % 360  # 逆时针 (数学方向)
        diff_cw = (start_angle - end_angle) % 360    # 顺时针

        # 判断弧上点更接近哪个方向
        mid_from_start = (mid_angle - start_angle) % 360
        # 如果弧上点在逆时针方向上 (diff_ccw 范围内)
        if mid_from_start < diff_ccw:
            span_angle = diff_ccw
        else:
            span_angle = -diff_cw  # 顺时针, 取负

        # Qt arcTo: 矩形定义椭圆边界, 角度是度 (非1/16度), 正值为逆时针
        # arcTo 会从当前路径位置画直线到弧起点, 所以必须先 moveTo 到弧起点
        rect = QRectF(center_x - radius, center_y - radius, radius * 2, radius * 2)
        path = QPainterPath()
        path.moveTo(ax, ay)
        path.arcTo(rect, start_angle, span_angle)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _draw_map_arc_center(self, painter: QPainter, elem: MapElement, color: QColor) -> None:
        """
        绘制圆心+半径+角度弧 (GAR) - 参照旧项目 MapRadar.cs DrawArc2()

        数据格式:
            points[0] = 圆心 (经纬度)
            rsv1      = 半径 (米)
            rsv2      = SOA 起始方位角 (度, 正北顺时针)
            rsv3      = EOA 终止方位角 (度, 正北顺时针)

        """
        if not elem.points:
            return

        ccx, ccy = self.geo.real_to_pixel(elem.points[0])
        radius_px = self.geo.distance_to_pixels(elem.rsv1)

        if radius_px <= 0:
            return

        soa = elem.rsv2   # 起始方位角 (度)
        eoa = elem.rsv3   # 终止方位角 (度)

        # sweepA 始终为正 (顺时针扫过的角度)
        sweep_a = eoa - soa if eoa > soa else eoa - soa + 360

        # 转换为 Qt 角度坐标系: 正东=0°, 逆时针为正
        # 旧项目 GDI: startAngle = SOA - 90 - MagVar (0°=正东, 顺时针为正)
        # Qt: 0°=正东, 逆时针为正, 所以 Qt_angle = -GDI_angle
        # qt_start = -(SOA - 90 - MagVar) = 90 + MagVar - SOA
        qt_start = 90 + self.mag_var - soa

        # Qt arcTo: 正值逆时针, 负值顺时针; 旧项目顺时针扫 sweep_a, 传 -sweep_a
        rect = QRectF(ccx - radius_px, ccy - radius_px, radius_px * 2, radius_px * 2)

        # 计算弧起点像素坐标 (用于 moveTo, 避免从原点画杂线)
        start_rad = math.radians(qt_start)
        arc_sx = ccx + radius_px * math.cos(start_rad)
        arc_sy = ccy - radius_px * math.sin(start_rad)

        path = QPainterPath()
        path.moveTo(arc_sx, arc_sy)
        path.arcTo(rect, qt_start, -sweep_a)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)

    def _draw_map_polygon(self, painter: QPainter, elem: MapElement) -> None:
        """绘制多边形 (GP)"""
        if len(elem.points) < 3:
            return
        path = QPainterPath()
        px, py = self.geo.real_to_pixel(elem.points[0])
        path.moveTo(px, py)
        for pt in elem.points[1:]:
            px, py = self.geo.real_to_pixel(pt)
            path.lineTo(px, py)
        path.closeSubpath()

        if elem.rsv1:
            # 有填充
            r, g, b = get_qcolor(elem.color_index)
            if elem.name and "BACKGROUD" in elem.name.upper():
                # 背景多边形: 不透明填充, 用背景色
                painter.setBrush(QColor(r, g, b, 155))
            else:
                # 普通填充多边形: 半透明
                painter.setBrush(QColor(r, g, b, 100))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    # ============== 航迹渲染 ==============
    def _draw_aircraft(self, painter: QPainter) -> None:
        """绘制所有航迹 (前景层)"""
        painter.setRenderHint(QPainter.Antialiasing, True)
        for track in self.track_store.tracks.values():
            self._draw_single_track(painter, track)

    def _draw_single_track(self, painter: QPainter, track: RadarTrack) -> None:
        """绘制单个航迹: 符号 + 历史点 + 标牌引线 + 标牌"""
        if track.latitude == 0 and track.longitude == 0:
            return

        px, py = self.geo.real_to_pixel(RealPoint(track.latitude, track.longitude))

        # 超出屏幕不画
        margin = 50
        if px < -margin or px > self.screen_w + margin or py < -margin or py > self.screen_h + margin:
            return

        # 判断是否为未相关航迹 (没有起飞地和目的地)
        is_uncorrelated = not track.adep.strip() and not track.adst.strip()

        # 确定颜色
        if getattr(track, 'selected', False):
            track_color = (255, 255, 255)  # 选中: 白色
        elif is_uncorrelated:
            track_color = (0, 0, 0)  # 未相关: 黑色
        elif track.sector_index == 0:
            track_color = COLOR_UNCONTROLLED
        else:
            track_color = COLOR_ASSUMED

        # 如果高度过滤打开且当前航迹不在范围内, 只画中心圆
        if self.label_filter_enabled and not self._is_track_within_label_filter(track):
            r, g, b = track_color
            painter.setBrush(QColor(r, g, b))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(px, py), 6, 6)
            return

        # 绘制历史航迹点
        self._draw_trail(painter, track, track_color)

        # 绘制航迹符号 (实心圆)
        r, g, b = track_color
        painter.setBrush(QColor(r, g, b))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(px, py), 6, 6)

        # 绘制预计线（根据单航迹的show_predict_line属性，不依赖全局VEL开关）
        if not is_uncorrelated and getattr(track, 'show_predict_line', False):
            self._draw_predict_line(painter, track, px, py, track_color)

        # 绘制标牌
        self._draw_label(painter, track, px, py, track_color, is_uncorrelated)

    def _calculate_predict_point(self, track: RadarTrack) -> Optional[RealPoint]:
        """
        根据航迹的速度、航向和预计时间，计算预计点坐标
        返回 RealPoint 或 None（如果速度不足）
        
        速度单位：km/h
        地球半径：6371 km，1度纬度 ≈ 111 km
        """
        if track.speed_kmh < 10 or self.predict_time_minutes <= 0:
            return None
        
        # 使用速度分量计算预计点
        # spdx_kmh: 东向速度(km/h), spdy_kmh: 北向速度(km/h)
        # 时间：分钟 → 小时
        time_hours = self.predict_time_minutes / 60.0
        
        # 北向移动距离 (km) → 纬度变化 (度)
        # 1度纬度 ≈ 111 km
        dlat = track.spdy_kmh * time_hours / 111.0
        
        # 东向移动距离 (km) → 经度变化 (度)
        # 1度经度 ≈ 111 * cos(lat) km
        dlon = track.spdx_kmh * time_hours / (111.0 * math.cos(math.radians(track.latitude)))
        
        predict_lat = track.latitude + dlat
        predict_lon = track.longitude + dlon
        
        return RealPoint(predict_lat, predict_lon)

    def _draw_predict_line(self, painter: QPainter, track: RadarTrack, px: float, py: float, track_color: tuple) -> None:
        """
        绘制预计线：从当前位置到预计位置的直线（实线）
        """
        predict_pt = self._calculate_predict_point(track)
        if predict_pt is None:
            return
        
        # 预计点像素坐标
        predict_px, predict_py = self.geo.real_to_pixel(predict_pt)
        
        # 绘制预计线（实线）
        r, g, b = track_color
        pen = QPen(QColor(r, g, b), 1)
        pen.setStyle(Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.drawLine(QPointF(px, py), QPointF(predict_px, predict_py))
        
        # 保存预计点坐标供后续使用
        track.predict_lat = predict_pt.lat
        track.predict_lon = predict_pt.lon

    def _draw_trail(self, painter: QPainter, track: RadarTrack, color: tuple) -> None:
        """绘制历史航迹点"""
        if len(track.trail_points) < 2:
            return
        r, g, b = color
        painter.setBrush(QColor(r, g ,b))

        # 只画最后 5 个点
        recent = track.trail_points[-6:]
        for lat, lon in recent:
            tpx, tpy = self.geo.real_to_pixel(RealPoint(lat, lon))
            if 6 < tpx < self.screen_w - 6 and 6 < tpy < self.screen_h - 6:
                painter.fillRect(int(tpx) - 1, int(tpy) - 1, 3, 3, painter.brush())

    def _draw_label(self, painter: QPainter, track: RadarTrack, px: float, py: float, track_color: tuple, is_uncorrelated: bool = False) -> None:
        """绘制标牌 (航班号 + 高度 + 速度 + 目的地)
        is_uncorrelated=True 时: 黑色标牌, 第二行只显示高度和速度
        """
        r, g, b = track_color
        color = QColor(r, g, b)
        painter.setPen(color)
        painter.setFont(self.label_font)
        fm = self.label_font_metrics
        font_h = fm.height() - 2

        # 确定标识
        acid = track.target_id.strip()
        if not acid:
            acid = track.acid.strip()
        if not acid:
            acid = "A" + track.ssr

        # 标牌偏移位置
        ox = getattr(track, 'offset_x', 20.0)
        oy = getattr(track, 'offset_y', -20.0)

        # 引线终点
        leader_end_x = px + ox
        leader_end_y = py + oy

        # 标牌左上角位置 (根据偏移方向)
        label_rows = 3 if not is_uncorrelated else 2
        if ox > 0:
            blip_x = leader_end_x
            blip_y = leader_end_y - font_h * label_rows
        elif ox < 0:
            blip_x = leader_end_x - 120
            blip_y = leader_end_y - font_h * label_rows
        elif oy > 0:
            blip_x = px - 60
            blip_y = leader_end_y
        else:
            blip_x = px - 60
            blip_y = leader_end_y - font_h * (label_rows + 1)

        # 画引线
        painter.drawLine(QPointF(px, py), QPointF(leader_end_x, leader_end_y))

        # 画标牌内容
        # 第一行: 航班号 + 尾流
        painter.drawText(int(blip_x), int(blip_y + font_h), acid)
        acid_width = fm.horizontalAdvance(acid)
        if track.wtc:
            painter.drawText(int(blip_x + acid_width), int(blip_y + font_h), track.wtc)

        y2 = blip_y + font_h

        if is_uncorrelated:
            # 未相关: 第二行只显示高度和速度
            qnh_h = track.qnh_height_m / 10 if track.qnh_height_m > 20000 else 0
            fl_str = f"{qnh_h:04.0f}" if qnh_h > 0 else f"{track.flight_level_m / 10:04.0f}"
            spd_str = f"{track.speed_kmh / 10:03.0f}"

            painter.drawText(int(blip_x), int(y2 + font_h), fl_str)
            fl_width = fm.horizontalAdvance(fl_str)
            self._draw_level_indicator(painter, track.level_status, blip_x + fl_width + 1, y2, color)
            spd_x = blip_x + fl_width + 30
            painter.drawText(int(spd_x), int(y2 + font_h), spd_str)
            # 记录速度字段的点击区域
            spd_width = fm.horizontalAdvance(spd_str)
            self._label_clickable_areas[track.track_number] = (spd_x, y2, spd_width, font_h)
        else:
            # 已相关: 完整标牌
            # 第二行: 高度 + CFL + 速度
            qnh_h = track.qnh_height_m / 10 if track.qnh_height_m > 20000 else 0
            fl_str = f"{qnh_h:04.0f}" if qnh_h > 0 else f"{track.flight_level_m / 10:04.0f}"
            cfl_str = f"{track.cfl_m / 10:04.0f}" if track.cfl_m > 0 else "____"
            spd_str = f"{track.speed_kmh / 10:03.0f}"

            painter.drawText(int(blip_x), int(y2 + font_h), fl_str)
            fl_width = fm.horizontalAdvance(fl_str)
            self._draw_level_indicator(painter, track.level_status, blip_x + fl_width + 1, y2, color)
            painter.drawText(int(blip_x + fl_width + 10), int(y2 + font_h), cfl_str)
            cfl_width = fm.horizontalAdvance(cfl_str)
            spd_x = blip_x + fl_width + cfl_width + 20
            painter.drawText(int(spd_x), int(y2 + font_h), spd_str)
            # 记录速度字段的点击区域
            spd_width = fm.horizontalAdvance(spd_str)
            self._label_clickable_areas[track.track_number] = (spd_x, y2, spd_width, font_h)

            # 第三行: 目的地 + 机型
            y3 = y2 + font_h
            painter.drawText(int(blip_x), int(y3 + font_h), track.adst)
            adst_width = fm.horizontalAdvance(track.adst)
            if track.aircraft_type:
                painter.drawText(int(blip_x + adst_width + 6), int(y3 + font_h), track.aircraft_type)

    def _draw_level_indicator(self, painter: QPainter, status: str, x: float, y: float, color: QColor) -> None:
        """绘制高度变化指示符 (上箭头/下箭头/向右箭头) - 只画线不填充"""
        fm = self.label_font_metrics
        fh = fm.height() 
        painter.setPen(QPen(color, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if status == 'c':  # 上升: 向上的箭头 (3点连线)
            p = QPainterPath()
            p.moveTo(x, y + fh - 3)
            p.lineTo(x + 3, y + 7)
            p.lineTo(x + 6, y + fh - 3)
            painter.drawPath(p)
        elif status == 'd':  # 下降: 向下的箭头 (3点连线)
            p = QPainterPath()
            p.moveTo(x, y + 7)
            p.lineTo(x + 3, y + fh - 3)
            p.lineTo(x + 6, y + 7)
            painter.drawPath(p)
        else:  # 保持: 向右的箭头 (3点连线)
            p = QPainterPath()
            p.moveTo(x, y + 7)
            p.lineTo(x + 5, y + fh * 0.5 + 2)
            p.lineTo(x, y + fh - 3)
            painter.drawPath(p)

    def resizeEvent(self, event) -> None:
        """窗口大小变化时更新"""
        super().resizeEvent(event)
        self.screen_w = self.width()
        self.screen_h = self.height()
        self.geo.update_screen_size(self.screen_w, self.screen_h)
        self.bg_pixmap = QPixmap(self.screen_w, self.screen_h)
        self.fg_pixmap = QPixmap(self.screen_w, self.screen_h)
        self._bg_dirty = True

    # ============== 键盘事件 ==============
    def keyPressEvent(self, event) -> None:
        """键盘控制"""
        key = event.key()
        if key == Qt.Key.Key_Escape:
            # ESC 不退出程序 (由 CLW 的 Quit 按钮负责)
            return

        pan_pixels = 0
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right):
            pan_pixels = self.PAN_STEP
        elif key == Qt.Key.Key_PageUp:
            # 放大 (比例尺减小)
            new_scale = max(self.SCALE_MIN, self.geo.scale - self.SCALE_STEP)
            if new_scale != self.geo.scale:
                self.geo.set_scale(new_scale)
                self._bg_dirty = True
            return
        elif key == Qt.Key.Key_PageDown:
            # 缩小 (比例尺增大)
            new_scale = min(self.SCALE_MAX, self.geo.scale + self.SCALE_STEP)
            if new_scale != self.geo.scale:
                self.geo.set_scale(new_scale)
                self._bg_dirty = True
            return

        if pan_pixels > 0:
            dx, dy = 0.0, 0.0
            if key == Qt.Key.Key_Up:
                dy = pan_pixels
            elif key == Qt.Key.Key_Down:
                dy = -pan_pixels
            elif key == Qt.Key.Key_Left:
                dx = -pan_pixels
            elif key == Qt.Key.Key_Right:
                dx = pan_pixels
            self._pan_map(dx, dy)

        super().keyPressEvent(event)

    def _pan_map(self, dx_pixels: float, dy_pixels: float) -> None:
        """平移地图: 将屏幕中心偏移 dx/dy 像素对应的地理距离"""
        # 屏幕像素偏移 → 地理坐标偏移
        # py 向上为正, dy_pixels 向下为正 (屏幕坐标系), 所以取反
        dlat = -dy_pixels * self.geo.degree_per_pixel
        dlon = dx_pixels * self.geo.degree_per_pixel / math.cos(math.radians(self.geo.center.lat))
        new_center = RealPoint(self.geo.center.lat + dlat, self.geo.center.lon + dlon)
        self.geo.set_center(new_center)
        self._bg_dirty = True

    def _set_center_at_pixel(self, px: float, py: float) -> None:
        """将指定像素位置设为屏幕中心"""
        real_pt = self.geo.pixel_to_real(px, py)
        self.geo.set_center(real_pt)
        self._bg_dirty = True

    # ============== 鼠标事件 ==============
    def _find_track_at(self, mx: float, my: float) -> Optional[RadarTrack]:
        """查找鼠标位置附近的航迹"""
        best = None
        best_dist = self.CLICK_RADIUS
        for track in self.track_store.tracks.values():
            if track.latitude == 0 and track.longitude == 0:
                continue
            px, py = self.geo.real_to_pixel(RealPoint(track.latitude, track.longitude))
            dist = math.sqrt((mx - px) ** 2 + (my - py) ** 2)
            if dist < best_dist:
                best_dist = dist
                best = track
        return best

    def mousePressEvent(self, event) -> None:
        mx, my = event.position().x(), event.position().y()

        if event.button() == Qt.MouseButton.LeftButton:
            # 左键: 优先检测标牌速度区域点击 > 选中/取消选中航迹
            # 检测标牌第二行速度字段点击
            label_clicked_track = None
            for track_number, (label_x, label_y, label_w, label_h) in self._label_clickable_areas.items():
                if label_x <= mx <= label_x + label_w and label_y <= my <= label_y + label_h:
                    if track_number in self.track_store.tracks:
                        label_clicked_track = self.track_store.tracks[track_number]
                    break
            
            if label_clicked_track:
                # 点击了标牌速度区域，切换预计线
                self.toggle_track_predict_line(label_clicked_track)
                return
            
            # 否则，选中/取消选中航迹
            track = self._find_track_at(mx, my)
            if track:
                track.selected = not getattr(track, 'selected', False)
                track.dragging = False  # 取消拖拽状态
                self._dragging_label = False
                self._drag_track = None

        elif event.button() == Qt.MouseButton.RightButton:
            # 右键: 优先结束拖拽 > 取消测距 > 开始拖拽
            if self._dragging_label and self._drag_track:
                # 正在拖拽: 任意位置右键结束拖拽
                self._drag_track.dragging = False
                self._dragging_label = False
                self._drag_track = None
                return

            if self._measure_active:
                self._handle_measure_right_click()
                return

            track = self._find_track_at(mx, my)
            if track:
                # 开始拖拽
                track.dragging = True
                self._dragging_label = True
                self._drag_track = track

        elif event.button() == Qt.MouseButton.MiddleButton:
            # 中键: 测距
            self._handle_measure_click(mx, my)

    def mouseMoveEvent(self, event) -> None:
        mx, my = event.position().x(), event.position().y()
        self._mouse_pos = (mx, my)
        self._mouse_geo = self.geo.pixel_to_real(mx, my)

        if self._dragging_label and self._drag_track:
            self._handle_label_drag(mx, my)
            return

        # 动态测距: 如果正在绘制测距线且有第一个点, 显示临时终点
        if self._measure_active and len(self._measure_points) == 1:
            track = self._find_track_at(mx, my)
            geo_pt = self.geo.pixel_to_real(mx, my)
            self._measure_temp_end = (geo_pt, track)

    def mouseDoubleClickEvent(self, event) -> None:
        mx, my = event.position().x(), event.position().y()
        
        if event.button() == Qt.MouseButton.LeftButton:
            # 左键双击: 检测是否点击在测距线或信息框上，删除
            for i, (box_x, box_y, box_w, box_h) in enumerate(self._measure_info_boxes):
                if box_x <= mx <= box_x + box_w and box_y <= my <= box_y + box_h:
                    # 点击在信息框上，删除该测距线
                    if i < len(self._completed_measure_lines):
                        del self._completed_measure_lines[i]
                    return
            
            # 检测是否点击在测距线上（线段附近）
            for i, (pt1, pt2) in enumerate(self._completed_measure_lines):
                pt1_resolved = self._resolve_measure_point(pt1[0], pt1[1])
                pt2_resolved = self._resolve_measure_point(pt2[0], pt2[1])
                px1, py1 = self.geo.real_to_pixel(pt1_resolved)
                px2, py2 = self.geo.real_to_pixel(pt2_resolved)
                
                # 计算点到线段的距离
                dist = self._distance_to_line_segment(mx, my, px1, py1, px2, py2)
                if dist <= 5:  # 5 像素的容差范围
                    del self._completed_measure_lines[i]
                    return
        
        elif event.button() == Qt.MouseButton.RightButton:
            # 右键双击: 如果正在测距, 取消测距; 否则设置地图中心
            if self._measure_active:
                self._handle_measure_right_click()
            else:
                self._set_center_at_pixel(mx, my)

    def wheelEvent(self, event) -> None:
        """鼠标滚轮缩放 - 以鼠标位置为中心"""
        mx, my = event.position().x(), event.position().y()
        delta = event.angleDelta().y()

        # 记录鼠标位置的地理坐标
        mouse_geo = self.geo.pixel_to_real(mx, my)

        if delta > 0:
            new_scale = max(self.SCALE_MIN, self.geo.scale - self.SCALE_STEP)
        else:
            new_scale = min(self.SCALE_MAX, self.geo.scale + self.SCALE_STEP)

        if new_scale != self.geo.scale:
            self.geo.set_scale(new_scale)
            # 保持鼠标指向的地理点不变: 计算该点在新比例尺下的像素位置偏移,
            # 然后移动中心使该点回到鼠标位置
            new_px, new_py = self.geo.real_to_pixel(mouse_geo)
            dx = mx - new_px
            dy = my - new_py
            self._pan_map(dx, dy)

    # ============== 标牌拖拽逻辑 ==============
    def _handle_label_drag(self, mx: float, my: float) -> None:
        """处理标牌拖拽"""
        track = self._drag_track
        px, py = self.geo.real_to_pixel(RealPoint(track.latitude, track.longitude))

        # 计算鼠标相对于航迹符号的偏移
        dx = mx - px
        dy = my - py
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < 5:
            # 距离太近时保持当前方向, 不归零
            return

        # 判断 8 方向
        angle = math.degrees(math.atan2(-dy, dx))  # 数学坐标系角度
        # 将角度量化到最近的 45 度 (8 方向)
        idx = round(angle / 45.0) % 8
        # 0=右, 1=右上, 2=上, 3=左上, 4=左, 5=左下, 6=下, 7=右下
        dir_map = [
            (1, 0),     # 0: 右
            (1, -1),    # 1: 右上
            (0, -1),    # 2: 上
            (-1, -1),   # 3: 左上
            (-1, 0),    # 4: 左
            (-1, 1),    # 5: 左下
            (0, 1),     # 6: 下
            (1, 1),     # 7: 右下
        ]
        dir_x, dir_y = dir_map[idx]

        # 引线长度始终为短 (25px), 拖拽时不需要改变长度
        length = self.LEADER_LENGTHS[0]

        track.offset_x = dir_x * length
        track.offset_y = dir_y * length

    # ============== 测距功能 ==============
    def _resolve_measure_point(self, real_pt: RealPoint, track: Optional[RadarTrack]) -> RealPoint:
        """解析测距点: 如果绑定航迹, 返回航迹当前位置; 否则返回固定点"""
        if track and track.latitude != 0 and track.longitude != 0:
            result = RealPoint(track.latitude, track.longitude)
            # 调试日志：尽量不打印太多
            # print(f"[DEBUG] _resolve_measure_point: 航迹 {track.target_id or track.acid} -> ({result.lat:.4f}, {result.lon:.4f})")
            return result
        return real_pt

    def _handle_measure_click(self, mx: float, my: float) -> None:
        """处理中键测距点击"""
        track = self._find_track_at(mx, my)
        geo_pt = self.geo.pixel_to_real(mx, my)

        if not self._measure_active:
            # 第一次中键: 开始新的测距线
            self._measure_points = [(geo_pt, track)]
            self._measure_active = True
            self._measure_temp_end = None
        elif len(self._measure_points) == 1:
            # 第二次中键: 完成当前测距线
            self._measure_points.append((geo_pt, track))
            # 保存完成的测距线（最多20条）
            if len(self._completed_measure_lines) < 20:
                self._completed_measure_lines.append((self._measure_points[0], self._measure_points[1]))
            # 清空当前线，准备下一条
            self._measure_points.clear()
            self._measure_active = False
            self._measure_temp_end = None

    def _handle_measure_right_click(self) -> None:
        """右键取消/清空测距"""
        self._measure_points.clear()
        self._measure_active = False
        self._measure_temp_end = None
        # 右键可以选择清空所有线，改为只清空正在绘制的线
        # 如果需要全清，可以添加：self._completed_measure_lines.clear()

    def _distance_to_line_segment(self, px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> float:
        """计算点 (px, py) 到线段 (x1,y1)-(x2,y2) 的距离"""
        # 线段方向向量
        dx = x2 - x1
        dy = y2 - y1
        
        if dx == 0 and dy == 0:
            # 退化为点
            return math.sqrt((px - x1) ** 2 + (py - y1) ** 2)
        
        # 参数 t 表示点在线段方向上的投影
        t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
        
        # 线段上最近的点
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy
        
        # 返回距离
        return math.sqrt((px - closest_x) ** 2 + (py - closest_y) ** 2)

    def _get_measure_points_pixel(self) -> List[Tuple[float, float]]:
        """获取当前测距线的像素坐标列表 (动态更新航迹位置)"""
        pts = list(self._measure_points)
        if self._measure_active and self._measure_temp_end and len(pts) == 1:
            pts.append(self._measure_temp_end)

        result = []
        for real_pt, track in pts:
            resolved = self._resolve_measure_point(real_pt, track)
            px, py = self.geo.real_to_pixel(resolved)
            result.append((px, py))
        return result

    def _draw_measure(self, painter: QPainter) -> None:
        """绘制所有测距线和距离/方位信息"""
        white_pen = QPen(QColor(255, 255, 255), 1, Qt.PenStyle.SolidLine)
        painter.setPen(white_pen)
        painter.setFont(self.label_font)
        fm = self.label_font_metrics
        
        # 清空信息框位置列表
        self._measure_info_boxes.clear()
        
        # 绘制所有已完成的测距线
        for line_idx, (pt1, pt2) in enumerate(self._completed_measure_lines):
            self._draw_single_measure_line(painter, pt1, pt2, fm, line_idx)
        
        # 绘制正在绘制的临时线
        if self._measure_active and len(self._measure_points) >= 1:
            pts = self._get_measure_points_pixel()
            if len(pts) >= 2:
                x1, y1 = pts[0]
                x2, y2 = pts[1]
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
                
                # 端点标记 - 与航迹关联的用黄色，否则用白色
                painter.setPen(Qt.PenStyle.NoPen)
                
                # 起点标记
                if self._measure_points[0][1] is not None:  # 与航迹相关联
                    painter.setBrush(QColor(255, 255, 0))  # 黄色
                else:
                    painter.setBrush(QColor(255, 255, 255))  # 白色
                painter.drawEllipse(QPointF(x1, y1), 3, 3)
                
                # 终点标记
                temp_track = self._measure_temp_end[1] if self._measure_temp_end else None
                if temp_track is not None:  # 与航迹相关联
                    painter.setBrush(QColor(255, 255, 0))  # 黄色
                else:
                    painter.setBrush(QColor(255, 255, 255))  # 白色
                painter.drawEllipse(QPointF(x2, y2), 3, 3)
                
                # 显示距离/方位（临时线）
                src_list = list(self._measure_points)
                if self._measure_temp_end and len(src_list) == 1:
                    src_list.append(self._measure_temp_end)
                
                if len(src_list) == 2:
                    src_geo = self._resolve_measure_point(src_list[0][0], src_list[0][1])
                    dst_geo = self._resolve_measure_point(src_list[1][0], src_list[1][1])
                    dist_km = src_geo.distance_to(dst_geo) / 1000.0
                    bearing = src_geo.bearing_to(dst_geo, self.mag_var)
                    
                    mid_x = (x1 + x2) / 2
                    mid_y = (y1 + y2) / 2
                    info_text = f"{dist_km:.1f}km {bearing:.0f}°"
                    
                    painter.setPen(QColor(255, 255, 255))
                    text_w = fm.horizontalAdvance(info_text)
                    text_h = fm.height()
                    # 透明背景（不画背景）
                    painter.drawText(int(mid_x - text_w / 2), int(mid_y - text_h / 2), text_w, text_h, Qt.AlignmentFlag.AlignCenter, info_text)

    def _draw_single_measure_line(self, painter: QPainter, pt1: Tuple[RealPoint, Optional[RadarTrack]], pt2: Tuple[RealPoint, Optional[RadarTrack]], fm, line_idx: int) -> None:
        """绘制单条已完成的测距线
        如果端点与航迹关联，用黄色圆圈标记关联的端点
        """
        src_geo = self._resolve_measure_point(pt1[0], pt1[1])
        dst_geo = self._resolve_measure_point(pt2[0], pt2[1])
        
        px1, py1 = self.geo.real_to_pixel(src_geo)
        px2, py2 = self.geo.real_to_pixel(dst_geo)
        
        # 画线
        painter.drawLine(QPointF(px1, py1), QPointF(px2, py2))
        
        # 端点标记 - 与航迹关联的用黄色，否则用白色
        painter.setPen(Qt.PenStyle.NoPen)
        
        # 起点标记
        if pt1[1] is not None:  # 与航迹相关联
            painter.setBrush(QColor(255, 255, 0))  # 黄色
        else:
            painter.setBrush(QColor(255, 255, 255))  # 白色
        painter.drawEllipse(QPointF(px1, py1), 3, 3)
        
        # 终点标记
        if pt2[1] is not None:  # 与航迹相关联
            painter.setBrush(QColor(255, 255, 0))  # 黄色
        else:
            painter.setBrush(QColor(255, 255, 255))  # 白色
        painter.drawEllipse(QPointF(px2, py2), 3, 3)
        
        # 显示距离/方位信息，如果关联航迹则显示航班号
        dist_km = src_geo.distance_to(dst_geo) / 1000.0
        bearing = src_geo.bearing_to(dst_geo, self.mag_var)
        
        mid_x = (px1 + px2) / 2
        mid_y = (py1 + py2) / 2
        info_text = f"{dist_km:.1f}km {bearing:.0f}°"
        
        painter.setPen(QColor(255, 255, 255))
        text_w = fm.horizontalAdvance(info_text)
        text_h = fm.height()
        
        # 记录信息框位置用于双击检测
        box_x = mid_x - text_w / 2 - 2
        box_y = mid_y - text_h / 2 - 1
        self._measure_info_boxes.append((box_x, box_y, text_w + 4, text_h + 2))
        
        # 透明背景（不画背景，直接画文字）
        painter.drawText(int(mid_x - text_w / 2), int(mid_y - text_h / 2), text_w, text_h, Qt.AlignmentFlag.AlignCenter, info_text)

    # ============== 坐标获取 ==============
    def get_mouse_geo_str(self) -> Tuple[str, str]:
        """获取鼠标位置的经纬度字符串, 用于 GIW 显示"""
        lat = self._mouse_geo.lat
        lon = self._mouse_geo.lon

        # 格式: DD,MM,SS(N/S) / DDD,MM,SS(E/W) - 保留到秒，不要小数
        def fmt_lat(v: float) -> str:
            if v >= 0:
                s = 'N'
            else:
                v = -v
                s = 'S'
            d = int(v)
            m = int((v - d) * 60)
            sec = round(((v - d) * 60 - m) * 60)  # 四舍五入到整数秒
            return f"{d:02d},{m:02d},{sec:02d}{s}"

        def fmt_lon(v: float) -> str:
            if v >= 0:
                s = 'E'
            else:
                v = -v
                s = 'W'
            d = int(v)
            m = int((v - d) * 60)
            sec = round(((v - d) * 60 - m) * 60)  # 四舍五入到整数秒
            return f"{d:03d},{m:02d},{sec:02d}{s}"

        return fmt_lat(lat), fmt_lon(lon)
