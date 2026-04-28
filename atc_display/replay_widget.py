"""
Replay 窗体 (回放控制台)
参照旧项目 FrmReplay 布局:
  - 顶部标题栏 (可拖拽)
  - 时间输入 / 持续时长 / 回放速度
  - Load / Start / Pause / Stop 按钮
  - 底部状态栏
置顶, 无任务栏图标; 点击 X 只隐藏不退出
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QColor, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QGroupBox, QRadioButton, QCheckBox,
    QStatusBar, QFrame, QSizePolicy,
)

from .radar_replay import ReplayEngine, DEFAULT_RADAR_DIR

logger = logging.getLogger("atc_display.replay")

# 回放定时器间隔 (ms) — 控制时间精度, 200ms 足够
REPLAY_TICK_MS = 200


class ReplayWidget(QWidget):
    """
    回放控制台窗体
    on_load_start  : 回调 — 用户点 Load, 通知外部暂停 UDP、清空航迹
    on_stop        : 回调 — 回放停止 (Stop/结束), 通知外部恢复 UDP
    on_frame       : 回调(payloads, replay_time) — 每帧要显示的雷达数据
    on_time_update : 回调(datetime) — 通知 GIW 更新时间显示
    """

    # 标题栏高度
    TITLE_H = 30
    # 面板背景色 (ActiveBorder 风格灰)
    PANEL_BG = "#D0D0D0"
    TITLE_BG = "#808080"

    def __init__(
        self,
        on_load_start: Optional[Callable[[], None]] = None,
        on_stop: Optional[Callable[[], None]] = None,
        on_frame: Optional[Callable] = None,
        on_time_update: Optional[Callable[[datetime], None]] = None,
        radar_dir: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.on_load_start = on_load_start
        self.on_stop = on_stop
        self.on_frame = on_frame
        self.on_time_update = on_time_update

        # 回放引擎
        self.engine = ReplayEngine(
            radar_dir=radar_dir or DEFAULT_RADAR_DIR,
            on_finished=self._on_replay_finished,
        )

        # 回放 tick 定时器
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(REPLAY_TICK_MS)
        self._tick_timer.timeout.connect(self._on_tick)

        # 窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool   # 不在任务栏显示
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedSize(463, 400)
        self.setStyleSheet(f"background-color: {self.PANEL_BG};")

        # 拖拽辅助
        self._drag_pos: Optional[QPoint] = None

        self._build_ui()
        self._update_buttons(loaded=False, running=False)

    # ── UI 构建 ────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_title_bar())
        root.addWidget(self._build_body())

    def _build_title_bar(self) -> QWidget:
        bar = QWidget(self)
        bar.setFixedHeight(self.TITLE_H)
        bar.setStyleSheet(f"background-color: {self.TITLE_BG};")
        bar.mousePressEvent = self._title_mouse_press
        bar.mouseMoveEvent = self._title_mouse_move

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 0, 8, 0)

        title = QLabel("REPLAY WINDOW")
        title.setFont(QFont("SimSun", 12))
        title.setStyleSheet("color: #800000; background: transparent;")  # Maroon
        title.mousePressEvent = self._title_mouse_press
        title.mouseMoveEvent = self._title_mouse_move
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addStretch(1)

        btn_close = QPushButton("×")
        btn_close.setFixedSize(22, 22)
        btn_close.setStyleSheet(
            "QPushButton { color: #CCCCCC; background: transparent; border: none; font-size: 14px; }"
            "QPushButton:hover { color: white; }"
        )
        btn_close.clicked.connect(self.hide)
        layout.addWidget(btn_close)
        return bar

    def _build_body(self) -> QWidget:
        body = QFrame(self)
        body.setFrameShape(QFrame.Shape.StyledPanel)
        body.setStyleSheet(f"background-color: {self.PANEL_BG};")

        v = QVBoxLayout(body)
        v.setContentsMargins(12, 10, 12, 4)
        v.setSpacing(8)

        # — 时间输入 —
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Time From:"))
        self.edt_time = QLineEdit(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self.edt_time.setFixedWidth(180)
        self.edt_time.setFont(QFont("SimSun", 10))
        self.edt_time.setToolTip("格式: YYYY-MM-DD HH:MM:SS，双击填入当前时间")
        self.edt_time.mouseDoubleClickEvent = self._fill_current_time
        row1.addWidget(self.edt_time)
        row1.addStretch(1)
        v.addLayout(row1)

        # — 持续时长 —
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Duration:"))
        self.edt_duration = QLineEdit("30")
        self.edt_duration.setFixedWidth(70)
        self.edt_duration.setFont(QFont("SimSun", 10))
        row2.addWidget(self.edt_duration)
        row2.addWidget(QLabel("(minutes)"))
        row2.addStretch(1)
        v.addLayout(row2)

        # — 速度 —
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Speed:"))
        self.cbx_speed = QComboBox()
        self.cbx_speed.addItems(["1", "2", "4", "8", "10", "20", "50"])
        self.cbx_speed.setCurrentIndex(0)
        self.cbx_speed.setFixedWidth(80)
        self.cbx_speed.setFont(QFont("SimSun", 10))
        self.cbx_speed.currentTextChanged.connect(self._on_speed_changed)
        row3.addWidget(self.cbx_speed)
        row3.addStretch(1)
        v.addLayout(row3)

        # — 数据路径 (Local/Remote) —
        grp = QGroupBox("Data Source")
        grp.setFont(QFont("SimSun", 10))
        grp_layout = QHBoxLayout(grp)
        self.rdb_local = QRadioButton("Local")
        self.rdb_remote = QRadioButton("Remote (/mnt/Radar)")
        self.rdb_local.setChecked(True)
        grp_layout.addWidget(self.rdb_local)
        grp_layout.addWidget(self.rdb_remote)
        grp_layout.addStretch(1)
        v.addWidget(grp)

        # — 按钮区 —
        btn_row1 = QHBoxLayout()
        self.btn_load = QPushButton("Load")
        self.btn_start = QPushButton("Start")
        self.btn_pause = QPushButton("Pause")
        self.btn_stop = QPushButton("Stop")
        for btn in (self.btn_load, self.btn_start, self.btn_pause, self.btn_stop):
            btn.setFixedSize(100, 30)
            btn.setFont(QFont("SimSun", 10))
        btn_row1.addStretch(1)
        btn_row1.addWidget(self.btn_load)
        btn_row1.addWidget(self.btn_start)
        btn_row1.addStretch(1)
        v.addLayout(btn_row1)

        btn_row2 = QHBoxLayout()
        btn_row2.addStretch(1)
        btn_row2.addWidget(self.btn_pause)
        btn_row2.addWidget(self.btn_stop)
        btn_row2.addStretch(1)
        v.addLayout(btn_row2)

        # 信号连接
        self.btn_load.clicked.connect(self._on_load)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_pause.clicked.connect(self._on_pause)
        self.btn_stop.clicked.connect(self._on_stop)

        # — 状态栏 —
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet(
            "background-color: #F0F0F0; border-top: 1px solid #AAAAAA; padding: 2px 4px;"
        )
        self.status_label.setFixedHeight(22)
        v.addWidget(self.status_label)

        return body

    # ── 事件 ───────────────────────────────────────────────────
    def _title_mouse_press(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event: QMouseEvent) -> None:
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def _fill_current_time(self, event=None) -> None:
        self.edt_time.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # ── 按钮逻辑 ───────────────────────────────────────────────
    def _on_load(self) -> None:
        """Load: 解析输入、加载文件、通知外部暂停 UDP"""
        try:
            start_time = datetime.strptime(self.edt_time.text().strip(), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            self._set_status("时间格式错误，请使用 YYYY-MM-DD HH:MM:SS")
            return
        try:
            duration = int(self.edt_duration.text().strip())
            if duration <= 0:
                raise ValueError
        except ValueError:
            self._set_status("持续时长必须为正整数（分钟）")
            return

        # 确定数据路径
        radar_dir = self.engine.radar_dir
        if self.rdb_remote.isChecked():
            radar_dir = Path("/") / "mnt" / "Radar"
        else:
            radar_dir = DEFAULT_RADAR_DIR
        self.engine.radar_dir = radar_dir

        self._set_status("正在加载数据...")
        # 通知外部: 暂停 UDP, 清空 ASD 航迹
        if self.on_load_start:
            self.on_load_start()

        # 加载数据 (同步，数据量不大，通常 < 1s)
        ok = self.engine.load(start_time, duration)
        if ok:
            frame_count = self.engine.frame_count
            self._set_status(f"就绪 - 已加载雷达数据 {frame_count} 条")
            self._update_buttons(loaded=True, running=False)
        else:
            self._set_status("加载失败，请检查数据目录和时间范围")
            self._update_buttons(loaded=False, running=False)

    def _on_start(self) -> None:
        """Start: 启动回放"""
        self.engine.speed = int(self.cbx_speed.currentText())
        self.engine.start()
        self._tick_timer.start()
        self._update_buttons(loaded=True, running=True)
        self._set_status("已开始")

    def _on_pause(self) -> None:
        """Pause/Continue 切换"""
        if self.engine.paused:
            self.engine.resume()
            self.btn_pause.setText("Pause")
            self._set_status("已开始")
        else:
            self.engine.pause()
            self.btn_pause.setText("Continue")
            self._set_status("已暂停")

    def _on_stop(self) -> None:
        """Stop: 停止回放，通知外部恢复 UDP"""
        self._tick_timer.stop()
        self.engine.stop()
        self.btn_pause.setText("Pause")
        self._update_buttons(loaded=False, running=False)
        self._set_status("已停止")
        if self.on_stop:
            self.on_stop()

    def _on_speed_changed(self, text: str) -> None:
        try:
            self.engine.speed = int(text)
        except ValueError:
            pass

    def _on_replay_finished(self) -> None:
        """回放自动结束: 清空ASD，保持replay状态，Load激活，Start/Pause/Stop禁用"""
        self._tick_timer.stop()
        self.btn_pause.setText("Pause")
        # Load 激活，Start/Pause/Stop 禁用 (保持 replay 状态)
        self.btn_load.setEnabled(True)
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self._set_status("回放结束")
        # 通知外部清空ASD，保持replay状态
        if self.on_stop:
            self.on_stop(finished=True)

    def _on_tick(self) -> None:
        """定时器回调: 推进回放时间, 分发帧数据"""
        payloads, replay_time = self.engine.tick(REPLAY_TICK_MS)
        if replay_time and self.on_time_update:
            self.on_time_update(replay_time)
        if payloads and self.on_frame:
            self.on_frame(payloads, replay_time)

    # ── 辅助 ───────────────────────────────────────────────────
    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _update_buttons(self, loaded: bool, running: bool) -> None:
        self.btn_load.setEnabled(not running and not loaded)
        self.btn_start.setEnabled(loaded and not running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running or loaded)

    def show_at_top_left(self, offset_y: int = 60) -> None:
        """显示在屏幕左上角 GIW 下方"""
        screen = self.screen().geometry()
        self.move(screen.left() + 5, screen.top() + offset_y + 5)
        self.show()
        self.raise_()
