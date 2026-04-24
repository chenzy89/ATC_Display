"""
GIW 窗体 - 底部信息栏
模仿旧项目 FrmGIW: 全屏宽度, 高度54px, 无边框
包含: 日期时间显示、鼠标经纬度、功能按钮区
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QGroupBox, QPushButton,
    QLineEdit, QListWidget, QFrame,
)


class GIWWidget(QWidget):
    """底部信息栏窗体, 对应 C# FrmGIW"""

    # 颜色常量 (与旧项目一致)
    COLOR_DARK_RED = "#8B0000"
    COLOR_NAVY = "#000080"
    COLOR_BROWN = "#8B4513"
    COLOR_BTN_OFF_BG = "#F0F0F0"  # 系统窗口色近似
    COLOR_BTN_OFF_FG = "#000080"  # Navy

    def __init__(self, parent=None):
        super().__init__(parent)

        # === 窗体属性 (无边框, 底部) ===
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedHeight(54)

        # === 字体 ===
        self.font_label = QFont("SimSun", 10)        # 宋体 10pt
        self.font_time = QFont("SimSun", 20, QFont.Weight.Bold)  # 宋体 20pt Bold（增大时间显示）
        self.font_btn = QFont("Verdana", 10)  # 按钮字体也增大

        # === 布局 ===
        self._build_ui()

        # === 定时器: 每秒更新时间 ===
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_clock)
        self._timer.start(1000)
        self._update_clock()

    def _build_ui(self) -> None:
        """构建 UI 布局"""
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(13, 4, 5, 4)
        main_layout.setSpacing(0)

        # ---------- 左侧: 工作模式 ----------
        self._build_work_mode(main_layout)

        # ---------- 分隔线 1 ----------
        main_layout.addWidget(self._make_separator())
        main_layout.addSpacing(10)

        # ---------- 中部: 日期时间 + 经纬度 ----------
        self._build_info_section(main_layout)

        # ---------- 分隔线 2 ----------
        main_layout.addWidget(self._make_separator())

        # ---------- 右侧: 功能按钮区 ----------
        self._build_button_section(main_layout)

        # ---------- 弹性空间 ----------
        main_layout.addStretch(1)

    def _build_work_mode(self, layout) -> None:
        """构建工作模式区域"""
        group = QGroupBox("Work Mode")
        group.setFixedWidth(240)  # 增大宽度以容纳更大的按钮
        group.setFont(QFont("SimSun", 7))

        group_layout = QHBoxLayout(group)
        group_layout.setContentsMargins(5, 5, 5, 5)

        self.rdb_realtime = QPushButton("Realtime")
        self.rdb_realtime.setCheckable(True)
        self.rdb_realtime.setChecked(True)
        self.rdb_realtime.setFont(self.font_btn)
        self.rdb_realtime.setFixedSize(100, 18)  # 增大按钮尺寸（宽x高）
        self._style_toggle_btn(self.rdb_realtime, active=True)

        self.rdb_replay = QPushButton("Replay")
        self.rdb_replay.setCheckable(True)
        self.rdb_replay.setFont(self.font_btn)
        self.rdb_replay.setFixedSize(100, 18)  # 增大按钮尺寸（宽x高）
        self._style_toggle_btn(self.rdb_replay, active=False)

        # 互斥: 模拟 RadioButton 行为
        self.rdb_realtime.clicked.connect(lambda: self._toggle_mode(True))
        self.rdb_replay.clicked.connect(lambda: self._toggle_mode(False))

        group_layout.addWidget(self.rdb_realtime)
        group_layout.addWidget(self.rdb_replay)

        layout.addWidget(group)

    def _build_info_section(self, layout) -> None:
        """构建日期时间 + 经纬度信息区域"""
        info_widget = QWidget()
        info_layout = QHBoxLayout(info_widget)
        info_layout.setContentsMargins(10, 0, 10, 0)
        info_layout.setSpacing(8)

        # 日期
        self.lbl_date = QLabel("26-04-07")
        self.lbl_date.setFont(self.font_label)
        self.lbl_date.setStyleSheet(f"color: {self.COLOR_DARK_RED};")
        info_layout.addWidget(self.lbl_date)

        # 时间 (大字)
        self.lbl_time = QLabel("00:00:00")
        self.lbl_time.setFont(self.font_time)
        self.lbl_time.setStyleSheet(f"color: {self.COLOR_DARK_RED};")
        info_layout.addWidget(self.lbl_time)

        # 空格
        info_layout.addSpacing(15)

        # 纬度
        self.lbl_lat = QLabel("22,33,02.26N")
        self.lbl_lat.setFont(self.font_label)
        self.lbl_lat.setStyleSheet(f"color: {self.COLOR_DARK_RED};")
        self.lbl_lat.setFixedWidth(120)
        info_layout.addWidget(self.lbl_lat)

        # 经度
        self.lbl_lon = QLabel("113,41,23.15E")
        self.lbl_lon.setFont(self.font_label)
        self.lbl_lon.setStyleSheet(f"color: {self.COLOR_DARK_RED};")
        self.lbl_lon.setFixedWidth(130)
        info_layout.addWidget(self.lbl_lon)

        info_layout.addStretch()
        layout.addWidget(info_widget, stretch=1)

    def _build_button_section(self, layout) -> None:
        """构建功能按钮区域"""
        btn_area = QWidget()
        btn_layout = QHBoxLayout(btn_area)
        btn_layout.setContentsMargins(5, 2, 5, 2)
        btn_layout.setSpacing(5)

        # VEL 按钮 + 时间输入
        self.btn_vel = QPushButton("VEL")
        self.btn_vel.setCheckable(True)
        self.btn_vel.setFont(self.font_btn)
        self.btn_vel.setFixedSize(75, 20)
        self._style_toggle_btn(self.btn_vel, active=False)

        self.tbx_vel = QLineEdit("1")
        self.tbx_vel.setFixedWidth(70)
        self.tbx_vel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tbx_vel.setFont(self.font_btn)

        vel_row_widget = QWidget()
        vel_row_layout = QHBoxLayout(vel_row_widget)
        vel_row_layout.setContentsMargins(0, 0, 0, 0)
        vel_row_layout.setSpacing(3)
        vel_row_layout.addWidget(self.btn_vel)
        vel_row_layout.addWidget(self.tbx_vel)

        # HIST 按钮 + 数量输入
        self.btn_hist = QPushButton("HIST")
        self.btn_hist.setCheckable(True)
        self.btn_hist.setFont(self.font_btn)
        self.btn_hist.setFixedSize(75, 20)
        self._style_toggle_btn(self.btn_hist, active=False)

        self.tbx_hist = QLineEdit("5")
        self.tbx_hist.setFixedWidth(70)
        self.tbx_hist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tbx_hist.setFont(self.font_btn)

        hist_row_widget = QWidget()
        hist_row_layout = QHBoxLayout(hist_row_widget)
        hist_row_layout.setContentsMargins(0, 0, 0, 0)
        hist_row_layout.setSpacing(3)
        hist_row_layout.addWidget(self.btn_hist)
        hist_row_layout.addWidget(self.tbx_hist)

        # WX 按钮
        self.btn_wx = QPushButton("WX")
        self.btn_wx.setCheckable(True)
        self.btn_wx.setChecked(True)
        self.btn_wx.setFont(self.font_btn)
        self.btn_wx.setFixedSize(75, 20)
        self._style_toggle_btn(self.btn_wx, active=True)

        # AL 按钮
        self.btn_al = QPushButton("AL")
        self.btn_al.setCheckable(True)
        self.btn_al.setFont(self.font_btn)
        self.btn_al.setFixedSize(75, 20)
        self._style_toggle_btn(self.btn_al, active=False)

        # AUDIO 按钮
        self.btn_audio = QPushButton("AUDIO")
        self.btn_audio.setCheckable(True)
        self.btn_audio.setFont(self.font_btn)
        self.btn_audio.setFixedSize(75, 20)
        self._style_toggle_btn(self.btn_audio, active=False)

        # FILTER 按钮 + 高度范围输入
        self.btn_filter = QPushButton("FILTER")
        self.btn_filter.setCheckable(True)
        self.btn_filter.setFont(self.font_btn)
        self.btn_filter.setFixedSize(75, 20)
        self._style_toggle_btn(self.btn_filter, active=False)

        self.tbx_filter_min = QLineEdit("0")
        self.tbx_filter_min.setFixedWidth(60)
        self.tbx_filter_min.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tbx_filter_min.setFont(self.font_btn)
        self.tbx_filter_min.setPlaceholderText("下限")

        self.tbx_filter_max = QLineEdit("10000")
        self.tbx_filter_max.setFixedWidth(60)
        self.tbx_filter_max.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tbx_filter_max.setFont(self.font_btn)
        self.tbx_filter_max.setPlaceholderText("上限")

        filter_widget = QWidget()
        filter_layout = QHBoxLayout(filter_widget)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(3)
        filter_layout.addWidget(self.tbx_filter_min)
        filter_layout.addWidget(self.btn_filter)
        filter_layout.addWidget(self.tbx_filter_max)

        # 排列按钮 (每列两个: 按钮在上, 输入框在下)
        col_vel_widget = QWidget()
        col_vel_layout = QVBoxLayout(col_vel_widget)
        col_vel_layout.setContentsMargins(0, 0, 0, 0)
        col_vel_layout.setSpacing(2)
        col_vel_layout.addWidget(self.btn_vel)
        col_vel_layout.addWidget(self.tbx_vel)

        col_hist_widget = QWidget()
        col_hist_layout = QVBoxLayout(col_hist_widget)
        col_hist_layout.setContentsMargins(0, 0, 0, 0)
        col_hist_layout.setSpacing(2)
        col_hist_layout.addWidget(self.btn_hist)
        col_hist_layout.addWidget(self.tbx_hist)

        col_wx_widget = QWidget()
        col_wx_layout = QVBoxLayout(col_wx_widget)
        col_wx_layout.setContentsMargins(0, 0, 0, 0)
        col_wx_layout.setSpacing(2)
        col_wx_layout.addWidget(self.btn_wx)
        spacer_label_wx = QLabel("")
        spacer_label_wx.setFixedHeight(20)
        col_wx_layout.addWidget(spacer_label_wx)

        # 右侧按钮列 (AL)
        col_right_widget = QWidget()
        col_right_layout = QVBoxLayout(col_right_widget)
        col_right_layout.setContentsMargins(0, 0, 0, 0)
        col_right_layout.setSpacing(2)
        col_right_layout.addWidget(self.btn_al)
        spacer_label_al = QLabel("")
        spacer_label_al.setFixedHeight(20)
        col_right_layout.addWidget(spacer_label_al)

        # FILTER 按钮列
        col_filter_widget = QWidget()
        col_filter_layout = QVBoxLayout(col_filter_widget)
        col_filter_layout.setContentsMargins(0, 0, 0, 0)
        col_filter_layout.setSpacing(2)
        col_filter_layout.addWidget(filter_widget)

        col_audio_widget = QWidget()
        col_audio_layout = QVBoxLayout(col_audio_widget)
        col_audio_layout.setContentsMargins(0, 0, 0, 0)
        col_audio_layout.setSpacing(2)
        col_audio_layout.addWidget(self.btn_audio)
        # 占位保持对齐
        spacer_label = QLabel("")
        spacer_label.setFixedHeight(20)
        col_audio_layout.addWidget(spacer_label)

        btn_layout.addWidget(col_vel_widget)
        btn_layout.addWidget(col_hist_widget)
        btn_layout.addWidget(col_wx_widget)
        btn_layout.addWidget(col_right_widget)
        btn_layout.addWidget(col_filter_widget)
        btn_layout.addWidget(col_audio_widget)

        layout.addWidget(btn_area)

    def _make_separator(self) -> QFrame:
        """创建棕色分隔线"""
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet(f"color: {self.COLOR_BROWN};")
        sep.setFixedWidth(1)
        return sep

    def _style_toggle_btn(self, btn: QPushButton, active: bool) -> None:
        """设置按钮的激活/非激活样式"""
        if active:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.COLOR_NAVY};
                    color: white;
                    border: 1px solid #333;
                    padding: 2px 5px;
                }}
            """)
        else:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {self.COLOR_BTN_OFF_BG};
                    color: {self.COLOR_BTN_OFF_FG};
                    border: 1px solid #999;
                    padding: 2px 5px;
                }}
            """)

    def _toggle_mode(self, realtime: bool) -> None:
        """切换工作模式"""
        self.rdb_realtime.setChecked(realtime)
        self.rdb_replay.setChecked(not realtime)
        self._style_toggle_btn(self.rdb_realtime, active=realtime)
        self._style_toggle_btn(self.rdb_replay, active=not realtime)

    def _update_clock(self) -> None:
        """更新系统时间显示 (回放模式时由外部驱动, 不覆盖)"""
        if getattr(self, '_replay_mode', False):
            return  # 回放模式: 时间由 set_replay_time 控制
        now = datetime.now()
        self.lbl_date.setText(now.strftime("%y-%m-%d"))
        self.lbl_time.setText(now.strftime("%H:%M:%S"))

    def set_replay_time(self, replay_dt: Optional[datetime]) -> None:
        """
        设置回放时间显示。
        replay_dt=None 表示退出回放模式, 恢复实时时间。
        """
        if replay_dt is None:
            self._replay_mode = False
            self._update_clock()
        else:
            self._replay_mode = True
            self.lbl_date.setText(replay_dt.strftime("%y-%m-%d"))
            self.lbl_time.setText(replay_dt.strftime("%H:%M:%S"))

    def update_coordinates(self, lat_str: str, lon_str: str) -> None:
        """更新鼠标位置坐标显示"""
        self.lbl_lat.setText(lat_str)
        self.lbl_lon.setText(lon_str)

    def get_predict_time_minutes(self) -> int:
        """获取预计时间（从 tbx_vel 读取，单位分钟）"""
        try:
            value = int(self.tbx_vel.text().strip())
            return max(1, min(value, 60))  # 限制在1-60分钟
        except (ValueError, AttributeError):
            return 1

    def is_predict_line_enabled(self) -> bool:
        """获取预计线开关状态（VEL 按钮是否被按下）"""
        return getattr(self.btn_vel, 'isChecked', lambda: False)()

    def is_wx_enabled(self) -> bool:
        """获取云图显示开关状态（WX 按钮是否被按下）"""
        return getattr(self.btn_wx, 'isChecked', lambda: False)()

    def get_filter_min_m(self) -> int:
        """获取高度过滤下限（米）"""
        try:
            return max(0, int(self.tbx_filter_min.text().strip()))
        except (ValueError, AttributeError):
            return 0

    def get_filter_max_m(self) -> int:
        """获取高度过滤上限（米）"""
        try:
            return max(0, int(self.tbx_filter_max.text().strip()))
        except (ValueError, AttributeError):
            return 10000

    def is_filter_enabled(self) -> bool:
        """获取 FILTER 开关状态"""
        return getattr(self.btn_filter, 'isChecked', lambda: False)()

    def resizeEvent(self, event) -> None:
        """窗口大小变化时"""
        super().resizeEvent(event)
        # 全屏宽度
        screen = self.screen().availableGeometry()
        self.setFixedWidth(screen.width())
