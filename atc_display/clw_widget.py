"""
CLW 窗体 - 底部命令工具栏
模仿旧项目 FrmCLW: 全屏宽度, 高度30px, 无边框, 屏幕底部
包含: Quit / Radar / Setup / Speech / FPL / Maps / Graphic / Replay / Location / AFTN / Trail
"""
from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QApplication


class CLWWidget(QWidget):
    """底部命令工具栏窗体, 对应 C# FrmCLW"""

    # 颜色常量 (与旧项目一致)
    COLOR_NAVY = "#000080"

    def __init__(self, parent=None):
        super().__init__(parent)

        # === 窗体属性 (无边框, 置顶) ===
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool           # 不在任务栏显示
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFixedHeight(30)

        # === 字体 ===
        self.font_btn = QFont("Verdana", 8)

        # === 构建 UI ===
        self._build_ui()

    def _build_ui(self) -> None:
        """构建按钮布局"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(34, 2, 0, 2)
        layout.setSpacing(5)

        # 按钮列表: (名称, 显示文字)
        buttons = [
            ("btn_quit",     "Quit"),
            ("btn_radar",    "Radar"),
            ("btn_setup",    "Setup"),
            ("btn_speech",   "Speech"),
            ("btn_fpl",      "FPL"),
            ("btn_maps",     "Maps"),
            ("btn_graphic",  "Graphic"),
            ("btn_replay",   "Replay"),
            ("btn_location", "Location"),
            ("btn_aftn",     "AFTN"),
            ("btn_trail",    "Trail"),
        ]

        for attr_name, text in buttons:
            btn = QPushButton(text)
            btn.setFont(self.font_btn)
            btn.setFixedSize(87, 26)
            btn.setStyleSheet(f"""
                QPushButton {{
                    color: {self.COLOR_NAVY};
                    background-color: #F0F0F0;
                    border: 1px solid #AAAAAA;
                    padding: 2px 4px;
                }}
                QPushButton:pressed {{
                    background-color: #C8C8C8;
                }}
                QPushButton:hover {{
                    background-color: #E0E0E0;
                }}
            """)
            setattr(self, attr_name, btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        # Quit 按钮连接退出逻辑
        self.btn_quit.clicked.connect(self._on_quit)

    def _on_quit(self) -> None:
        """退出程序"""
        QApplication.quit()

    def resizeEvent(self, event) -> None:
        """窗口大小变化时保持全屏宽"""
        super().resizeEvent(event)
        screen = self.screen().geometry()   # 使用 geometry (不去掉任务栏) 获取真实屏幕宽度
        self.setFixedWidth(screen.width())
