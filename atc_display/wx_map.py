"""
云图 (Weather Map) 模块
参照旧项目 MapRadar.cs 中的云图功能:
  - LoadWxImg(): 启动时查找最新云图
  - LoadWXPNG(name): 按文件名加载云图
  - DrawWeatherImage(): 绘制到背景图

云图路径: X:\\{MMdd}\\{HHmm}.PNG
锚点坐标: N26-36-19.35, E103-58-31 (贵州/云南交界, 气象雷达拼图左上角)
源图裁剪区域: 1000x850, 宽高比 100:85
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor

logger = logging.getLogger("atc_display.wx_map")

# ── 常量 ──
WX_ANCHOR_LAT = 26.0 + 36.0 / 60 + 19.35 / 3600   # N26°36'19.35"
WX_ANCHOR_LON = 103.0 + 58.0 / 60 + 31.0 / 3600    # E103°58'31"
WX_COVERAGE_METERS = 10_000_000                      # 覆盖宽度 (米)
WX_ASPECT_RATIO = 0.85                               # 宽高比 (85/100)
WX_SRC_W = 1000                                      # 源图裁剪宽度
WX_SRC_H = 850                                       # 源图裁剪高度

# 地球参数 (与 geometry.py 保持一致)
EARTH_RADIUS = 6371000  # 地球半径 (米)
METERS_PER_DEGREE = 2 * 3.14159265358979323846 * EARTH_RADIUS / 360  # 每度对应的米数


class WXMapManager(QObject):
    """云图管理器: 加载、存储、绘制信号"""

    # 新云图加载成功后发出, 由主线程连接到 ASD 标记 _bg_dirty
    wx_updated = Signal()

    def __init__(self, wx_base_path: str = "/mnt/WXMap", parent=None):
        super().__init__(parent)
        self._base_path = Path(wx_base_path)
        self._pixmap: Optional[QPixmap] = None
        self._current_name: str = ""

    @property
    def pixmap(self) -> Optional[QPixmap]:
        return self._pixmap

    @property
    def current_name(self) -> str:
        return self._current_name

    @property
    def has_image(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    # ── 启动加载 (LoadWxImg) ──
    def load_latest(self) -> bool:
        """
        启动时查找最新云图:
        扫描当日云图目录 {base_path}\\{MMdd}\\，按文件名排序取最新的 HHmm.PNG
        """
        today = datetime.now()
        dir_name = today.strftime("%m%d")  # MMdd
        wx_dir = self._base_path / dir_name

        if not wx_dir.exists():
            logger.warning("云图目录不存在: %s", wx_dir)
            return False

        # 查找所有 .PNG 文件，按文件名排序取最新
        png_files = sorted(wx_dir.glob("*.PNG"))
        if not png_files:
            logger.warning("当日云图目录无 PNG 文件: %s", wx_dir)
            return False

        latest_file = png_files[-1]  # 文件名排序后最后一个即最新
        name = dir_name + latest_file.stem  # MMdd + HHmm

        return self.load_png(name)

    # ── 按名加载 (LoadWXPNG) ──
    def load_png(self, name: str) -> bool:
        """
        加载云图文件. name 格式: 'MMddHHmm' (8位)
        路径: {base_path}\\{MMdd}\\{HHmm}.PNG
        """
        if len(name) < 8:
            return False

        dir_name = name[:4]     # MMdd
        file_name = name[4:] + ".PNG"  # HHmm.PNG
        filepath = self._base_path / dir_name / file_name

        if not filepath.exists():
            logger.debug("云图文件不存在: %s", filepath)
            return False

        try:
            img = QImage(str(filepath))
            if img.isNull():
                logger.warning("云图加载失败 (空图像): %s", filepath)
                return False

            self._pixmap = QPixmap.fromImage(img)
            self._current_name = name
            logger.info("云图加载成功: %s (%dx%d)", filepath, img.width(), img.height())
            return True
        except Exception as exc:
            logger.error("云图加载异常: %s -> %s", filepath, exc)
            return False

    # ── 绘制 (DrawWeatherImage) ──
    def draw(self, painter: QPainter, geo: "GeoTransform") -> None:
        """
        在 painter 上绘制云图 (仿旧项目 DrawWeatherImage).
        锚点: WX_ANCHOR_LAT / WX_ANCHOR_LON
        宽度: 根据当前比例尺动态计算
        """
        if not self.has_image:
            return

        from .geometry import RealPoint

        # 锚点转像素坐标
        px, py = geo.real_to_pixel(RealPoint(WX_ANCHOR_LAT, WX_ANCHOR_LON))

        # 动态宽度 (米 → 像素), 与旧项目一致:
        # wid = 10000000 / (MetPerDegree * DegreePerPixel * 7)
        met_per_degree = METERS_PER_DEGREE
        degree_per_pixel = geo.degree_per_pixel
        wid = int(WX_COVERAGE_METERS / (met_per_degree * degree_per_pixel * 7))
        hei = int(wid * WX_ASPECT_RATIO)

        # 缩放到目标尺寸后绘制
        scaled = self._pixmap.scaled(
            wid, hei,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap(int(px), int(py), scaled)

        # 绘制文件名标注 (蓝色文字)
        painter.setPen(QColor(0, 0, 255))
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(int(px), int(py) - 5, self._current_name)

    def clear(self) -> None:
        """清空云图"""
        self._pixmap = None
        self._current_name = ""
