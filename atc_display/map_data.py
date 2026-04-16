"""
地图数据解析与渲染模块
解析 C# 项目自定义格式的 draw_*.txt 地图文件
支持: GTXT(文字), GV(线段), GST(定位点), GC(圆), GA(弧1), GAR(弧2), GR(航路), GP(多边形)
对应 C# MapRadar.cs 的 LoadMapData() + DrawBackGroundMap()
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple, Optional

from .geometry import RealPoint, GeoTransform, parse_dms_to_real

logger = logging.getLogger("atc_display.map")


@dataclass
class MapElement:
    """单个地图元素, 对应 C# TMap_BasicInfo"""
    color_index: int = 0       # 颜色索引 (对应 SysColor.LesColors)
    element_type: int = 0      # 类型: 0=Text 1=Vector 2=Fix 3=Circle 4=Arc1 5=Arc2 6=Route 7=Polygon
    style: int = 0             # 线型: 0=实线 1=长虚线 2=短虚线 3=点划线 4=双点划线
    width: int = 1             # 线宽
    name: str = ""             # 元素名称
    points: List[RealPoint] = field(default_factory=list)
    labels: List[str] = field(default_factory=list)
    rsv1: float = 0.0          # 保留字段1 (旋转角/半径/填充等)
    rsv2: float = 0.0          # 保留字段2
    rsv3: float = 0.0          # 保留字段3


def load_map_file(filepath: Path) -> List[MapElement]:
    """
    解析一个 draw_*.txt 地图文件
    对应 C# MapRadar.LoadMapData()
    """
    if not filepath.exists():
        logger.warning("地图文件不存在: %s", filepath)
        return []

    # 地图文件通常是 GBK 编码 (中文 Windows)
    for enc in ("utf-8-sig", "gbk", "utf-8"):
        try:
            with open(filepath, "r", encoding=enc) as f:
                lines = f.read().replace("\r", "").split("\n")
            break
        except UnicodeDecodeError:
            continue
    else:
        logger.warning("地图文件编码无法识别: %s", filepath)
        return []

    elements: List[MapElement] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("//"):
            i += 1
            continue

        element = _parse_line(line, lines, i)
        if element:
            elements.append(element)
            if element.element_type in (6, 7):  # GR/GP 有后续点行
                # 计算跳过的行数
                if line.startswith("GR"):
                    parts = line.split()
                    if len(parts) > 4:
                        point_count = int(parts[4])
                        i += point_count
                elif line.startswith("GP") and len(line) > 2 and line[2].isdigit():
                    parts = line.split()
                    if len(parts) > 4:
                        point_count = int(parts[4])
                        i += point_count
        i += 1

    logger.info("加载地图文件 %s: %d 个元素", filepath.name, len(elements))
    return elements


def _parse_line(line: str, lines: List[str], line_index: int) -> Optional[MapElement]:
    """解析单行地图数据"""
    if line.startswith("GTXT"):
        return _parse_gtxt(line)
    elif line.startswith("GV") and _is_gv_line(line):
        return _parse_gv(line)
    elif line.startswith("GST"):
        return _parse_gst(line)
    elif line.startswith("GC") and _is_gc_line(line):
        return _parse_gc(line)
    elif line.startswith("GA") and len(line) > 2 and line[2].isdigit():
        return _parse_ga(line)
    elif line.startswith("GAR"):
        return _parse_gar(line)
    elif line.startswith("GR"):
        return _parse_gr(line, lines, line_index)
    elif line.startswith("GP") and len(line) > 2 and line[2].isdigit():
        return _parse_gp(line, lines, line_index)
    return None


def _is_gv_line(line: str) -> bool:
    """区分 GV 和 GTXT/GAR 等前缀"""
    if not line.startswith("GV"):
        return False
    parts = line.split()
    if len(parts) >= 7:
        # GV 格式: GV<color> Lat Lon Lat Lon style width name str1 str2
        try:
            int(parts[0][2:])
            return True
        except ValueError:
            return False
    return False


def _is_gc_line(line: str) -> bool:
    if not line.startswith("GC"):
        return False
    parts = line.split()
    if len(parts) >= 7:
        try:
            int(parts[0][2:])
            return True
        except ValueError:
            return False
    return False


def _parse_gtxt(line: str) -> MapElement:
    """GTXT - 文字元素"""
    parts = line.split()
    elem = MapElement()
    elem.element_type = 0  # Text
    elem.color_index = int(parts[0][4:])  # GTXT<color>
    if len(parts) > 1:
        elem.points.append(parse_dms_to_real(parts[1]))
    if len(parts) > 2:
        elem.points.append(parse_dms_to_real(parts[2]))  # lon
        elem.points[0] = RealPoint(
            _parse_single_dms(parts[1]),
            _parse_single_dms(parts[2])
        )
    if len(parts) > 3:
        elem.name = parts[3].strip('"')
    if len(parts) > 4:
        elem.labels.append(parts[4].strip('"'))
    if len(parts) > 5:
        elem.rsv1 = float(parts[5])  # 旋转角度
    if len(parts) > 6:
        elem.rsv2 = float(parts[6])  # 填充
    return elem


def _parse_gv(line: str) -> MapElement:
    """GV - 线段元素"""
    parts = line.split()
    elem = MapElement()
    elem.element_type = 1  # Vector
    elem.color_index = int(parts[0][2:])
    if len(parts) >= 5:
        elem.points = [
            RealPoint(_parse_single_dms(parts[1]), _parse_single_dms(parts[2])),
            RealPoint(_parse_single_dms(parts[3]), _parse_single_dms(parts[4])),
        ]
    if len(parts) > 5:
        elem.style = int(parts[5])
    if len(parts) > 6:
        elem.width = int(parts[6])
    if len(parts) > 7:
        elem.name = parts[7]
    if len(parts) > 9:
        elem.labels = [parts[8], parts[9]]
    return elem


def _parse_gst(line: str) -> MapElement:
    """GST - 定位点元素"""
    parts = line.split()
    elem = MapElement()
    elem.element_type = 2  # Fix
    elem.color_index = int(parts[0][3:])
    if len(parts) >= 3:
        elem.points.append(
            RealPoint(_parse_single_dms(parts[1]), _parse_single_dms(parts[2]))
        )
    if len(parts) > 3:
        elem.name = parts[3].strip('"')
    if len(parts) > 4:
        elem.labels.append(parts[4].strip('"'))
    if len(parts) > 5:
        elem.style = int(parts[5])
    return elem


def _parse_gc(line: str) -> MapElement:
    """GC - 圆元素"""
    parts = line.split()
    elem = MapElement()
    elem.element_type = 3  # Circle
    elem.color_index = int(parts[0][2:])
    if len(parts) >= 5:
        elem.points = [
            RealPoint(_parse_single_dms(parts[1]), _parse_single_dms(parts[2])),
            RealPoint(_parse_single_dms(parts[3]), _parse_single_dms(parts[4])),
        ]
    if len(parts) > 5:
        elem.style = int(parts[5])
    if len(parts) > 6:
        elem.width = int(parts[6])
    if len(parts) > 10:
        elem.rsv1 = float(parts[10])  # filled
    return elem


def _parse_ga(line: str) -> MapElement:
    """GA - 弧1 (三点定弧)"""
    parts = line.split()
    elem = MapElement()
    elem.element_type = 4  # Arc1
    elem.color_index = int(parts[0][2:])
    if len(parts) >= 7:
        elem.points = [
            RealPoint(_parse_single_dms(parts[1]), _parse_single_dms(parts[2])),
            RealPoint(_parse_single_dms(parts[3]), _parse_single_dms(parts[4])),
            RealPoint(_parse_single_dms(parts[5]), _parse_single_dms(parts[6])),
        ]
    if len(parts) > 7:
        elem.style = int(parts[7])
    if len(parts) > 8:
        elem.width = int(parts[8])
    if len(parts) > 13:
        elem.rsv1 = float(parts[13])
    return elem


def _parse_gar(line: str) -> MapElement:
    """GAR - 弧2 (圆心+半径+角度)"""
    parts = line.split()
    elem = MapElement()
    elem.element_type = 5  # Arc2
    elem.color_index = int(parts[0][3:])
    if len(parts) >= 3:
        elem.points.append(
            RealPoint(_parse_single_dms(parts[1]), _parse_single_dms(parts[2]))
        )
    if len(parts) > 3:
        elem.rsv1 = float(parts[3])  *  100 # 半径: C# 项目中单位为度, 乘以 100 转换为百分度 (与 GA 的点距半径保持一致)
    if len(parts) > 4:
        elem.rsv2 = float(parts[4])  # 起始角
    if len(parts) > 5:
        elem.rsv3 = float(parts[5])  # 终止角
    if len(parts) > 6:
        elem.style = int(parts[6])
    if len(parts) > 10:
        elem.width = int(parts[10])
    if len(parts) > 8:
        elem.name = parts[8]
    if len(parts) > 9:
        elem.labels.append(parts[9])
    return elem


def _parse_gr(line: str, lines: List[str], line_index: int) -> MapElement:
    """GR - 航路 (多点连线)"""
    parts = line.split()
    elem = MapElement()
    elem.element_type = 6  # Route
    elem.color_index = int(parts[0][2:])
    if len(parts) > 1:
        elem.name = parts[1]
    if len(parts) > 2:
        elem.style = int(parts[2])
    if len(parts) > 3:
        elem.width = int(parts[3])
    point_count = int(parts[4]) if len(parts) > 4 else 0

    for j in range(point_count):
        pt_idx = line_index + 1 + j
        if pt_idx < len(lines):
            pt_parts = lines[pt_idx].split()
            if len(pt_parts) >= 3:
                elem.points.append(
                    RealPoint(_parse_single_dms(pt_parts[1]), _parse_single_dms(pt_parts[2]))
                )
                if len(pt_parts) > 3:
                    elem.labels.append(pt_parts[3])
    return elem


def _parse_gp(line: str, lines: List[str], line_index: int) -> MapElement:
    """GP - 多边形"""
    parts = line.split()
    elem = MapElement()
    elem.element_type = 7  # Polygon
    elem.color_index = int(parts[0][2:])
    if len(parts) > 1:
        elem.name = parts[1]
    if len(parts) > 2:
        elem.style = int(parts[2])
    if len(parts) > 3:
        elem.rsv1 = float(parts[3])  # 填充
    point_count = int(parts[4]) if len(parts) > 4 else 0
    if len(parts) > 5:
        elem.width = int(parts[5])

    for j in range(point_count):
        pt_idx = line_index + 1 + j
        if pt_idx < len(lines):
            pt_parts = lines[pt_idx].split()
            if len(pt_parts) >= 3:
                elem.points.append(
                    RealPoint(_parse_single_dms(pt_parts[1]), _parse_single_dms(pt_parts[2]))
                )
                if len(pt_parts) > 3:
                    elem.labels.append(pt_parts[3])
    return elem


def _parse_single_dms(s: str) -> float:
    """
    解析单个 DMS 坐标值
    支持: 22,33,32N  113,55,29E  22,33,32.5N  等格式
    """
    import re
    s = s.strip().strip('"').strip("'")

    # 格式1: 22,33,32N 或 22,33,32.5N (度,分,秒)
    m = re.match(r'^(\d+),(\d+),([\d.]+)([NSEW])$', s)
    if m:
        return _dms_to_decimal(float(m[1]), float(m[2]), float(m[3]), m[4])

    raise ValueError(f"无法解析坐标: {s}")


def _dms_to_decimal(deg: float, min_: float, sec: float, direction: str) -> float:
    val = deg + min_ / 60.0 + sec / 3600.0
    if direction in ('S', 'W'):
        val = -val
    return val


# =============== 渲染颜色表 ===============
# 对应 C# SysColor.LesColors[31]
LES_COLORS = [
    (110, 110, 110),   # 0  - 背景色
    (200, 200, 200),   # 1
    (69, 110, 86),     # 2
    (129, 145, 145),   # 3
    (0, 0, 254),       # 4
    (254, 0, 254),     # 5
    (254, 0, 254),     # 6
    (75, 94, 97),      # 7
    (104, 86, 0),      # 8
    (69, 110, 86),     # 9
    (3, 197, 206),     # 10
    (0, 254, 210),     # 11
    (82, 142, 186),    # 12
    (59, 249, 52),     # 13
    (229, 0, 0),       # 14
    (126, 117, 46),    # 15
    (254, 180, 196),   # 16
    (110, 110, 110),   # 17
    (159, 159, 159),   # 18
    (0, 0, 0),         # 19
    (255, 255, 255),   # 20
    (254, 0, 0),       # 21
    (0, 254, 0),       # 22
    (0, 0, 254),       # 23
    (192, 224, 179),   # 24
    (254, 0, 254),     # 25
    (0, 254, 254),     # 26
    (254, 172, 49),    # 27
    (149, 79, 143),    # 28
    (39, 79, 114),     # 29
    (255, 255, 0),     # 30
]

# 航迹显示颜色
COLOR_CONTROLLED = (1, 1, 156)        # 蓝色 - 管控状态
COLOR_ASSUMED = (181, 255, 181)      # 浅绿 - 假相关
COLOR_UNCONTROLLED = (41, 41, 41)    # 深灰 - 未管
COLOR_BACKGROUND = (110, 110, 110)   # 背景色


def get_qcolor(color_index: int):
    """根据索引获取颜色, 返回 Qt 颜色对象 (由调用方使用)"""
    if 0 <= color_index < len(LES_COLORS):
        r, g, b = LES_COLORS[color_index]
        return r, g, b
    return 200, 200, 200
