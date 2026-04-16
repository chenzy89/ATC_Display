"""
地理/坐标转换模块
实现 WGS84 经纬度 ↔ 屏幕像素、距离/方位角计算
对应 C# 项目的 Geography.cs + RealPoint/DDPoint
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

# 地球半径 (米), 与 C# ConREarth 一致
EARTH_RADIUS_M = 6_371_182
# 每度对应的米数
METERS_PER_DEGREE = 2 * math.pi * EARTH_RADIUS_M / 360.0


@dataclass
class RealPoint:
    """WGS84 地理坐标 (经纬度)"""
    lat: float = 0.0  # 纬度, 正=北
    lon: float = 0.0  # 经度, 正=东

    def distance_to(self, other: RealPoint) -> float:
        """Haversine 公式计算两点间距离 (米)"""
        dlat = math.radians(other.lat - self.lat)
        dlon = math.radians(other.lon - self.lon)
        lat1 = math.radians(self.lat)
        lat2 = math.radians(other.lat)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return EARTH_RADIUS_M * c

    def bearing_to(self, other: RealPoint, mag_var: float = 0.0) -> float:
        """计算到另一点的方位角 (度, 0-360), 含磁差修正"""
        lat1 = math.radians(self.lat)
        lat2 = math.radians(other.lat)
        dlon = math.radians(other.lon - self.lon)
        y = math.sin(dlon) * math.cos(lat2)
        x = (math.cos(lat1) * math.sin(lat2) -
             math.sin(lat1) * math.cos(lat2) * math.cos(dlon))
        bearing = math.degrees(math.atan2(y, x))
        return (bearing + 360 + mag_var) % 360

    def destination(self, bearing_deg: float, distance_m: float, mag_var: float = 0.0) -> RealPoint:
        """根据方位角和距离计算目标点 (球面三角法)"""
        angular_dist = distance_m / EARTH_RADIUS_M
        lat1 = math.radians(self.lat)
        lon1 = math.radians(self.lon)
        brng = math.radians(bearing_deg - mag_var)
        lat2 = math.asin(
            math.sin(lat1) * math.cos(angular_dist) +
            math.cos(lat1) * math.sin(angular_dist) * math.cos(brng)
        )
        lon2 = lon1 + math.atan2(
            math.sin(brng) * math.sin(angular_dist) * math.cos(lat1),
            math.cos(angular_dist) - math.sin(lat1) * math.sin(lat2)
        )
        return RealPoint(math.degrees(lat2), math.degrees(lon2))


class GeoTransform:
    """
    经纬度 ↔ 屏幕像素 转换器
    对应 C# Geography 类的静态成员
    """
    def __init__(self, center: RealPoint, scale: int, screen_w: int, screen_h: int):
        """
        :param center: 屏幕中心对应的地理坐标
        :param scale: 地图比例尺 (米/像素)
        :param screen_w: 屏幕宽度 (像素)
        :param screen_h: 屏幕高度 (像素)
        """
        self.center = center
        self.scale = scale
        self.screen_cx = screen_w / 2.0
        self.screen_cy = screen_h / 2.0
        self.degree_per_pixel = scale / METERS_PER_DEGREE
        self.screen_w = screen_w
        self.screen_h = screen_h

    def update_screen_size(self, w: int, h: int) -> None:
        self.screen_w = w
        self.screen_h = h
        self.screen_cx = w / 2.0
        self.screen_cy = h / 2.0

    def set_center(self, center: RealPoint) -> None:
        """设置地图中心点"""
        self.center = center

    def set_scale(self, scale: int) -> None:
        """设置比例尺 (米/像素)"""
        self.scale = scale
        self.degree_per_pixel = scale / METERS_PER_DEGREE

    def real_to_pixel(self, pt: RealPoint) -> Tuple[float, float]:
        """
        经纬度 → 屏幕像素
        对应 C# RealPoint.ToPixelPt()
        """
        dy = (pt.lat - self.center.lat) / self.degree_per_pixel
        dx = ((pt.lon - self.center.lon) / self.degree_per_pixel *
              math.cos(math.radians(self.center.lat)))
        px = self.screen_cx + dx
        py = self.screen_cy - dy
        return (px, py)

    def pixel_to_real(self, px: float, py: float) -> RealPoint:
        """
        屏幕像素 → 经纬度
        对应 C# Geography.PixelPtToRealPt()
        """
        dy = (py - self.screen_cy) * self.degree_per_pixel
        dx = ((px - self.screen_cx) * self.degree_per_pixel /
              math.cos(math.radians(self.center.lat)))
        return RealPoint(self.center.lat - dy, self.center.lon + dx)

    def distance_to_pixels(self, dist_m: float) -> float:
        """实际距离 (米) → 屏幕像素距离"""
        return dist_m / (METERS_PER_DEGREE * self.degree_per_pixel)


def cal_angle(x: float, y: float) -> float:
    """
    根据 X/Y 速度分量计算航向角 (度, 0-360)
    对应 C# CommonFun.CalAngle()
    X>0 Y>0 → 第一象限 (NE)
    """
    if x == 0 and y > 0:
        return 0.0
    elif x == 0 and y < 0:
        return 180.0
    elif x > 0 and y == 0:
        return 90.0
    elif x < 0 and y == 0:
        return 270.0
    elif x > 0 and y > 0:
        return 90.0 - math.degrees(math.atan(y / x))
    elif x > 0 and y < 0:
        return 90.0 + math.degrees(math.atan(abs(y) / x))
    elif x < 0 and y < 0:
        return 270.0 - math.degrees(math.atan(abs(y) / abs(x)))
    elif x < 0 and y > 0:
        return 270.0 + math.degrees(math.atan(y / abs(x)))
    return 0.0


def pixel_point_from_pixel(px: float, py: float, angle: float, distance: int) -> Tuple[float, float]:
    """
    从像素点出发, 按方位角和像素距离求另一像素点
    对应 C# Geography.GetPixelPtFromPixelPt()
    角度: 正北顺时针 (0=北, 90=东)
    """
    converted = _convert_angle(angle)
    x = distance * math.cos(math.radians(converted))
    y = distance * math.sin(math.radians(converted))
    return (px + x, py - y)


def _convert_angle(angle: float) -> float:
    """正北顺时针 → 正东逆时针 (用于 cos/sin 计算)"""
    return 90.0 - angle if angle <= 90 else 450.0 - angle


def parse_dms_to_real(dms_str: str) -> RealPoint:
    """
    解析 DMS 格式坐标字符串为 RealPoint
    支持: (22,33,32N  113,55,29E) 和 (N222332  E1135529) 等格式
    """
    import re

    parts = dms_str.strip().split()
    if len(parts) >= 2:
        return RealPoint(
            _parse_single_dms(parts[0]),
            _parse_single_dms(parts[1])
        )
    raise ValueError(f"无法解析 DMS 坐标: {dms_str}")


def _parse_single_dms(s: str) -> float:
    """解析单个 DMS 坐标值 (如 22,33,32N 或 N223332)"""
    import re
    s = s.strip().strip('"').strip("'")

    # 格式1: 22,33,32N 或 22,33,32.5N
    m = re.match(r'^(\d+),(\d+),([\d.]+)([NSEW])$', s)
    if m:
        return _dms_to_decimal(float(m[1]), float(m[2]), float(m[3]), m[4])

    # 格式2: N223332
    m = re.match(r'^([NSEW])(\d{2,3})(\d{2})(\d{2})$', s)
    if m:
        direction = m[1]
        d, mn, sec = m[2], m[3], m[4]
        return _dms_to_decimal(float(d), float(mn), float(sec), direction)

    raise ValueError(f"无法解析坐标: {s}")


def _dms_to_decimal(deg: float, min_: float, sec: float, direction: str) -> float:
    val = deg + min_ / 60.0 + sec / 3600.0
    if direction in ('S', 'W'):
        val = -val
    return val
