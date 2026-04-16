"""
MAPS WINDOW 窗体
仿旧项目 FrmMaps:
  - 从 MapData/AllMaps.txt 读取可用地图列表
  - 动态生成 Checkbox 控件 (5列网格布局)
  - CurrentMaps.txt 保存/加载默认显示地图
  - OK 按钮保存勾选状态并隐藏窗体
  - 关闭按钮仅隐藏窗体
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QFrame, QScrollArea, QGridLayout
)

logger = logging.getLogger("atc_display.maps_widget")

# 常量
MAP_DATA_DIR = Path(__file__).parent / "mapData"
ALL_MAPS_FILE = "AllMaps.txt"
CURRENT_MAPS_FILE = "CurrentMaps.txt"


class MapsWidget(QWidget):
    """地图选择窗体, 对应 C# FrmMaps"""

    # 地图选择变化信号 (勾选或取消勾选时触发)
    maps_changed = Signal(list)  # List[str] 当前选中的地图名称列表

    def __init__(
        self,
        map_data_dir: Optional[Path] = None,
        on_maps_changed: Optional[Callable[[List[str]], None]] = None,
        parent=None
    ):
        super().__init__(parent)

        self._map_data_dir = map_data_dir or MAP_DATA_DIR
        self._all_maps: List[str] = []      # 所有可用地图
        self._current_maps: List[str] = []  # 当前选中的地图
        self._checkboxes: dict[str, QCheckBox] = {}

        # 回调函数
        self._on_maps_changed = on_maps_changed

        # === 窗体属性 ===
        self.setWindowTitle("MAPS WINDOW")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(560, 482)

        # === 构建 UI ===
        self._build_ui()

        # === 加载数据 ===
        self._load_all_maps()
        self._load_current_maps()
        self._create_checkboxes()

    def _build_ui(self) -> None:
        """构建 UI 布局"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── 标题栏 (panel1) ──
        self.panel_title = QFrame()
        self.panel_title.setFixedHeight(31)
        self.panel_title.setStyleSheet("background-color: #A9A9A9;")  # AppWorkspace
        title_layout = QHBoxLayout(self.panel_title)
        title_layout.setContentsMargins(4, 4, 4, 4)

        self.lbl_caption = QLabel("MAPS WINDOW")
        self.lbl_caption.setFont(QFont("宋体", 12))
        self.lbl_caption.setStyleSheet("color: #800000;")  # Maroon
        title_layout.addStretch(1)
        title_layout.addWidget(self.lbl_caption)
        title_layout.addStretch(1)

        # 关闭按钮
        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(28, 22)
        self.btn_close.setStyleSheet("""
            QPushButton {
                color: gray;
                background-color: transparent;
                border: none;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                color: red;
            }
        """)
        self.btn_close.clicked.connect(self.hide)
        title_layout.addWidget(self.btn_close)

        main_layout.addWidget(self.panel_title)

        # ── Checkbox 容器 (panel2) ──
        self.panel_content = QFrame()
        self.panel_content.setStyleSheet("background-color: #B0B0B0; border: 1px solid #808080;")
        content_layout = QVBoxLayout(self.panel_content)
        content_layout.setContentsMargins(10, 10, 10, 10)

        # ScrollArea 用于容纳大量地图
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border: none; background-color: transparent;")

        self.scroll_widget = QWidget()
        self.grid_layout = QGridLayout(self.scroll_widget)
        self.grid_layout.setSpacing(5)
        self.grid_layout.setColumnStretch(5, 1)  # 第6列拉伸

        scroll.setWidget(self.scroll_widget)
        content_layout.addWidget(scroll)

        # OK 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setFixedSize(100, 29)
        self.btn_ok.clicked.connect(self._on_ok)
        btn_layout.addWidget(self.btn_ok)
        content_layout.addLayout(btn_layout)

        main_layout.addWidget(self.panel_content, stretch=1)

        # 标题栏支持拖动
        self.panel_title.mousePressEvent = self._title_mouse_press
        self.panel_title.mouseMoveEvent = self._title_mouse_move
        self.lbl_caption.mousePressEvent = self._title_mouse_press
        self.lbl_caption.mouseMoveEvent = self._title_mouse_move

    def _title_mouse_press(self, event) -> None:
        """标题栏鼠标按下"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def _title_mouse_move(self, event) -> None:
        """标题栏拖动"""
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    # ── 数据加载 ──
    def _load_all_maps(self) -> None:
        """从 AllMaps.txt 加载所有可用地图"""
        filepath = self._map_data_dir / ALL_MAPS_FILE
        if not filepath.exists():
            logger.warning("AllMaps.txt 不存在: %s", filepath)
            return

        try:
            text = filepath.read_text(encoding="utf-8")
            # 移除回车符, 按换行分割
            lines = text.replace("\r", "").split("\n")
            # 过滤空行
            self._all_maps = [line.strip() for line in lines if line.strip()]
            logger.info("加载 %d 个可用地图", len(self._all_maps))
        except Exception as exc:
            logger.error("读取 AllMaps.txt 失败: %s", exc)

    def _load_current_maps(self) -> None:
        """从 CurrentMaps.txt 加载默认显示的地图"""
        filepath = self._map_data_dir / CURRENT_MAPS_FILE
        if not filepath.exists():
            logger.info("CurrentMaps.txt 不存在, 使用空列表")
            return

        try:
            text = filepath.read_text(encoding="utf-8")
            lines = text.replace("\r", "").split("\n")
            self._current_maps = [line.strip() for line in lines if line.strip()]
            logger.info("加载 %d 个默认显示地图", len(self._current_maps))
        except Exception as exc:
            logger.error("读取 CurrentMaps.txt 失败: %s", exc)

    def _save_current_maps(self) -> None:
        """保存当前选中的地图到 CurrentMaps.txt"""
        filepath = self._map_data_dir / CURRENT_MAPS_FILE
        try:
            # 按 AllMaps 顺序排序
            sorted_maps = sorted(
                self._current_maps,
                key=lambda x: self._all_maps.index(x) if x in self._all_maps else 9999
            )
            text = "\r\n".join(sorted_maps)
            filepath.write_text(text, encoding="utf-8")
            logger.info("保存 CurrentMaps.txt: %d 个地图", len(sorted_maps))
        except Exception as exc:
            logger.error("保存 CurrentMaps.txt 失败: %s", exc)

    def _create_checkboxes(self) -> None:
        """动态创建 Checkbox 控件 (5列布局)"""
        # 清除旧控件
        for cb in self._checkboxes.values():
            cb.deleteLater()
        self._checkboxes.clear()

        font = QFont("宋体", 10)
        
        # Checkbox 样式表
        checkbox_style = """
            QCheckBox {
                spacing: 4px;
                padding: 4px;
                color: #000000;
                margin: 2px;
            }
            QCheckBox::indicator {
                width: 6px;
                height: 6px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #FFFFFF;
                border: 2px solid #808080;
                border-radius: 2px;
            }
            QCheckBox::indicator:checked {
                background-color: #0078D4;
                border: 2px solid #0078D4;
                border-radius: 2px;
                color: white;
            }
        """

        for i, map_name in enumerate(self._all_maps):
            cb = QCheckBox(map_name)
            cb.setFont(font)
            cb.setChecked(map_name in self._current_maps)
            cb.setStyleSheet(checkbox_style)
            cb.stateChanged.connect(self._on_checkbox_changed)

            # 5列网格: row = i // 5, col = i % 5
            row = i // 5
            col = i % 5
            self.grid_layout.addWidget(cb, row, col)
            self._checkboxes[map_name] = cb

    def _on_checkbox_changed(self, state) -> None:
        """Checkbox 状态变化处理"""
        sender = self.sender()
        if not isinstance(sender, QCheckBox):
            return

        map_name = sender.text()
        if state == Qt.CheckState.Checked.value:
            if map_name not in self._current_maps:
                self._current_maps.append(map_name)
                self._sort_current_maps()
        else:
            if map_name in self._current_maps:
                self._current_maps.remove(map_name)

        # 触发回调和信号
        self._notify_maps_changed()

    def _sort_current_maps(self) -> None:
        """按 AllMaps 顺序排序 CurrentMaps"""
        self._current_maps.sort(
            key=lambda x: self._all_maps.index(x) if x in self._all_maps else 9999
        )

    def _notify_maps_changed(self) -> None:
        """通知地图选择变化"""
        self.maps_changed.emit(self._current_maps.copy())
        if self._on_maps_changed:
            self._on_maps_changed(self._current_maps.copy())

    def _on_ok(self) -> None:
        """OK 按钮: 保存并隐藏"""
        self._save_current_maps()
        self.hide()

    # ── 公共接口 ──
    def get_current_maps(self) -> List[str]:
        """获取当前选中的地图列表"""
        return self._current_maps.copy()

    def set_map_visible(self, map_name: str, visible: bool) -> None:
        """设置指定地图的显示状态 (外部调用)"""
        if map_name in self._checkboxes:
            self._checkboxes[map_name].setChecked(visible)

    def refresh_checkboxes(self) -> None:
        """刷新 Checkbox 状态 (重新加载 CurrentMaps)"""
        self._load_current_maps()
        for name, cb in self._checkboxes.items():
            cb.setChecked(name in self._current_maps)
