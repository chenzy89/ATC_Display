"""
CAT062 ASTERIX 协议解码模块
将 UDP 组播报文解析为航迹数据
参考: C# CAT062.cs + 参考项目 atc_data_hub/parsers/cat062.py
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple


@dataclass
class RadarTrack:
    """单条航迹数据, 对应 C# Radar_FDRRecord"""
    # === 基本信息 ===
    track_number: int = -1
    target_id: str = ""       # 航班号 (CAT062 I245)
    acid: str = ""            # 下传航班号 (CAT062 I390 CSN)
    ssr: str = "0000"         # 应答机编码 (CAT062 I060)

    # === 位置/运动 ===
    latitude: float = 0.0
    longitude: float = 0.0
    speed_kmh: float = 0.0    # 速度 km/h
    heading_deg: float = 0.0  # 航向角 (度, 0-360)
    spdx_kmh: float = 0.0
    spdy_kmh: float = 0.0

    # === 高度 ===
    flight_level_m: float = 0.0       # 测量高度 (米)
    qnh_height_m: float = 0.0         # QNH 修正高度 (米)
    qnh_applied: bool = False
    selected_altitude_m: int = 0      # FSSA MCP/FCU 选择高度 (米)
    cfl_m: float = 0.0               # CFL 计划高度 (米)

    # === 飞行计划 ===
    aircraft_type: str = ""   # 机型
    wtc: str = ""             # 尾流等级
    adep: str = ""            # 起飞机场
    adst: str = ""            # 目的机场
    runway: str = ""          # 使用跑道
    sector_index: int = 0     # 当前扇区
    sid: str = ""             # 离场程序
    star: str = ""            # 进场程序
    flight_plan_correlated: int = 0  # 航班计划相关标志

    # === 其他 ===
    time_of_track: Optional[datetime] = None
    received_at: Optional[datetime] = None
    level_status: str = 'm'   # 高度状态: 'c'=上升, 'd'=下降, 'm'=保持

    # === 显示辅助 ===
    trail_points: List[Tuple[float, float]] = field(default_factory=list)  # 历史航迹点 [(lat, lon), ...]
    offset_x: float = 20.0    # 标牌偏移 X
    offset_y: float = -20.0   # 标牌偏移 Y
    selected: bool = False     # 左键选中状态
    dragging: bool = False     # 右键拖拽标牌状态
    last_update_time: Optional[datetime] = None  # 最后更新时间 (用于超时清理)
    
    # === 预计线 ===
    show_predict_line: bool = False  # 是否显示该航迹的预计线
    predict_lat: float = 0.0   # 预计点纬度
    predict_lon: float = 0.0   # 预计点经度


class Cat062ParseError(ValueError):
    pass


class _Cursor:
    """字节流读取游标"""
    def __init__(self, data: bytes, start: int, end: int):
        self.data = data
        self.idx = start
        self.end = end

    def remaining(self) -> int:
        return self.end - self.idx

    def skip(self, size: int) -> None:
        self._require(size)
        self.idx += size

    def _require(self, size: int) -> None:
        if self.idx + size > self.end:
            raise Cat062ParseError(
                f"数据不足: 需要 {size} 字节, 剩余 {self.remaining()} 字节"
            )

    def read(self, size: int) -> bytes:
        self._require(size)
        chunk = self.data[self.idx:self.idx + size]
        self.idx += size
        return chunk

    def read_u8(self) -> int:
        self._require(1)
        v = self.data[self.idx]
        self.idx += 1
        return v

    def read_u16(self) -> int:
        return int.from_bytes(self.read(2), "big", signed=False)

    def read_i16(self) -> int:
        return int.from_bytes(self.read(2), "big", signed=True)

    def read_u24(self) -> int:
        return int.from_bytes(self.read(3), "big", signed=False)

    def read_i32(self) -> int:
        return int.from_bytes(self.read(4), "big", signed=True)


class Cat062Parser:
    """CAT062 数据报解析器"""

    def parse_datagram(self, payload: bytes) -> List[RadarTrack]:
        """
        解析一个完整的 CAT062 UDP 数据报
        payload[0] = Category (0x3E = 62)
        payload[1:3] = 长度
        """
        if len(payload) < 3:
            return []
        declared_length = int.from_bytes(payload[1:3], "big", signed=False)
        total_length = min(len(payload), declared_length) if declared_length >= 3 else len(payload)

        records: List[RadarTrack] = []
        index = 3
        while index < total_length:
            try:
                track, next_index = self._parse_record(payload, index, total_length)
            except Cat062ParseError:
                break
            if next_index <= index:
                break
            index = next_index
            if track.track_number >= 0 or track.target_id:
                records.append(track)
        return records

    def _parse_record(self, payload: bytes, start: int, end: int) -> tuple:
        cursor = _Cursor(payload, start, end)
        fspecs = self._read_fspecs(cursor)

        fs1 = fspecs[0] if len(fspecs) > 0 else 0
        fs2 = fspecs[1] if len(fspecs) > 1 else 0
        fs3 = fspecs[2] if len(fspecs) > 2 else 0
        fs4 = fspecs[3] if len(fspecs) > 3 else 0
        fs5 = fspecs[4] if len(fspecs) > 4 else 0

        track = RadarTrack(received_at=datetime.now())

        # FSPEC1 位解析
        bit010 = (fs1 & 0x80) >> 7
        bit015 = (fs1 & 0x20) >> 5
        bit070 = (fs1 & 0x10) >> 4
        bit105 = (fs1 & 0x08) >> 3
        bit100 = (fs1 & 0x04) >> 2
        bit185 = (fs1 & 0x02) >> 1

        # FSPEC2 位解析
        bit210 = (fs2 & 0x80) >> 7
        bit060 = (fs2 & 0x40) >> 6
        bit245 = (fs2 & 0x20) >> 5
        bit380 = (fs2 & 0x10) >> 4
        bit040 = (fs2 & 0x08) >> 3
        bit080 = (fs2 & 0x04) >> 2
        bit290 = (fs2 & 0x02) >> 1

        # FSPEC3 位解析
        bit200 = (fs3 & 0x80) >> 7
        bit295 = (fs3 & 0x40) >> 6
        bit136 = (fs3 & 0x20) >> 5
        bit130 = (fs3 & 0x10) >> 4
        bit135 = (fs3 & 0x08) >> 3
        bit220 = (fs3 & 0x04) >> 2
        bit390 = (fs3 & 0x02) >> 1

        # FSPEC4 位解析
        bit270 = (fs4 & 0x80) >> 7
        bit300 = (fs4 & 0x40) >> 6
        bit110 = (fs4 & 0x20) >> 5
        bit120 = (fs4 & 0x10) >> 4
        bit510 = (fs4 & 0x08) >> 3
        bit500 = (fs4 & 0x04) >> 2
        bit340 = (fs4 & 0x02) >> 1

        # === 按位读取数据 ===
        if bit010:
            cursor.skip(2)  # I010 Data Source Identifier
        if bit015:
            cursor.skip(1)  # I015 Service Identifier

        if bit070:
            seconds = cursor.read_u24() / 128.0
            track.time_of_track = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            from datetime import timedelta
            track.time_of_track += timedelta(seconds=seconds)

        if bit105:
            track.latitude = cursor.read_i32() * 180.0 / 33554432.0
            track.longitude = cursor.read_i32() * 180.0 / 33554432.0

        if bit100:
            cursor.skip(6)  # 笛卡尔坐标, 不使用

        if bit185:
            vx_raw = cursor.read_i16()
            vy_raw = cursor.read_i16()
            speed_x = vx_raw * 0.25 * 3.6
            speed_y = vy_raw * 0.25 * 3.6
            track.spdx_kmh = speed_x
            track.spdy_kmh = speed_y
            track.speed_kmh = math.sqrt(speed_x ** 2 + speed_y ** 2)
            track.heading_deg = self._cal_heading(speed_x, speed_y)

        if bit210:
            cursor.skip(2)

        if bit060:
            track.ssr = self._read_ssr(cursor)

        if bit245:
            cursor.skip(1)  # SPI 位
            track.target_id = self._decode_ia5_callsign(cursor.read(6)).strip()

        if bit380:
            self._parse_380(cursor, track)

        if bit040:
            track.track_number = cursor.read_u16()

        if bit080:
            track.flight_plan_correlated = self._parse_080(cursor)

        if bit290:
            self._parse_290(cursor)

        if bit200:
            cursor.skip(1)

        if bit295:
            self._parse_295(cursor)

        if bit136:
            track.flight_level_m = cursor.read_i16() * 25 * 0.3048

        if bit130:
            cursor.skip(2)

        if bit135:
            value = cursor.read_u16()
            track.qnh_applied = bool(value & 0x8000)
            track.qnh_height_m = (value & 0x7FFF) * 25 * 0.3048

        if bit220:
            cursor.skip(2)

        if bit390:
            self._parse_390(cursor, track)

        if bit270:
            self._parse_270(cursor)

        if bit300:
            cursor.skip(1)

        if bit110:
            self._parse_110(cursor)

        if bit120:
            cursor.skip(2)

        if bit510:
            self._parse_510(cursor)

        if bit500:
            self._parse_500(cursor)

        if bit340:
            self._parse_340(cursor)

        if track.time_of_track is None:
            track.time_of_track = track.received_at

        return track, cursor.idx

    # === FSPEC 读取 ===
    def _read_fspecs(self, cursor: _Cursor) -> list:
        fspecs = []
        while True:
            value = cursor.read_u8()
            fspecs.append(value)
            if value & 0x01 == 0:
                break
            if len(fspecs) >= 5:
                break
        return fspecs

    # === 子项解析 ===
    def _parse_080(self, cursor: _Cursor) -> int:
        correlated = 0
        fx1 = cursor.read_u8() & 0x01
        if fx1:
            second = cursor.read_u8()
            correlated = (second & 0x10) >> 4
            fx2 = second & 0x01
            if fx2:
                third = cursor.read_u8()
                if third & 0x01:
                    cursor.skip(1)
        return correlated

    def _parse_290(self, cursor: _Cursor) -> None:
        octet1 = cursor.read_u8()
        flags1 = [
            (octet1 & 0x80, 1), (octet1 & 0x40, 1), (octet1 & 0x20, 1),
            (octet1 & 0x10, 1), (octet1 & 0x08, 2), (octet1 & 0x04, 1),
            (octet1 & 0x02, 1),
        ]
        fx1 = octet1 & 0x01
        octet2 = cursor.read_u8() if fx1 else None
        if octet2 is not None:
            for mask, size in [(0x80, 1), (0x40, 1), (0x20, 1)]:
                if octet2 & mask:
                    cursor.skip(size)
        for enabled, size in flags1:
            if enabled:
                cursor.skip(size)

    def _parse_295(self, cursor: _Cursor) -> None:
        octets = []
        while True:
            octet = cursor.read_u8()
            octets.append(octet)
            if octet & 0x01 == 0:
                break
            if len(octets) >= 5:
                break
        size_map = [[1]*7, [1]*7, [1]*7, [1]*7, [1,1,1]]
        for idx, octet in enumerate(octets):
            sizes = size_map[idx]
            bits = [0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02][:len(sizes)]
            for mask, size in zip(bits, sizes, strict=False):
                if octet & mask:
                    cursor.skip(size)

    def _parse_270(self, cursor: _Cursor) -> None:
        octet = cursor.read_u8()
        if octet & 0x01:
            octet = cursor.read_u8()
            if octet & 0x01:
                octet = cursor.read_u8()
                if octet & 0x01:
                    cursor.skip(1)

    def _parse_110(self, cursor: _Cursor) -> None:
        octet = cursor.read_u8()
        for mask, size in [(0x80,1),(0x40,4),(0x20,6),(0x10,2),(0x08,2),(0x04,1),(0x02,1)]:
            if octet & mask:
                cursor.skip(size)

    def _parse_510(self, cursor: _Cursor) -> None:
        chunk = cursor.read(3)
        if chunk[2] & 0x01:
            cursor.skip(3)

    def _parse_500(self, cursor: _Cursor) -> None:
        octets = []
        while True:
            octet = cursor.read_u8()
            octets.append(octet)
            if octet & 0x01 == 0:
                break
            if len(octets) >= 2:
                break
        size_map = [[4,2,4,1,1,2,2], [1]]
        for idx, octet in enumerate(octets):
            sizes = size_map[idx]
            bits = [0x80,0x40,0x20,0x10,0x08,0x04,0x02][:len(sizes)]
            for mask, size in zip(bits, sizes, strict=False):
                if octet & mask:
                    cursor.skip(size)

    def _parse_340(self, cursor: _Cursor) -> None:
        octet = cursor.read_u8()
        for mask, size in [(0x80,2),(0x40,4),(0x20,2),(0x10,2),(0x08,2),(0x04,1)]:
            if octet & mask:
                cursor.skip(size)

    def _parse_380(self, cursor: _Cursor, track: RadarTrack) -> None:
        octets = []
        while True:
            octet = cursor.read_u8()
            octets.append(octet)
            if octet & 0x01 == 0:
                break
            if len(octets) >= 4:
                break

        sets = []
        for i, octet in enumerate(octets):
            s = {}
            if i == 0:
                s = {"ADR":0x80,"ID":0x40,"MHG":0x20,"IAS":0x10,
                     "TAS":0x08,"SAL":0x04,"FSS":0x02}
            elif i == 1:
                s = {"TIS":0x80,"TID":0x40,"COM":0x20,"SAB":0x10,
                     "ACS":0x08,"BVR":0x04,"GVR":0x02}
            elif i == 2:
                s = {"RAN":0x80,"TAR":0x40,"TAN":0x20,"GSP":0x10,
                     "VUN":0x08,"MET":0x04,"EMC":0x02}
            elif i == 3:
                s = {"POS":0x80,"GAL":0x40,"PUN":0x20,"MB":0x10,
                     "IAR":0x08,"MAC":0x04,"BPS":0x02}
            sets.append({k: bool(octet & v) for k, v in s.items()})

        if len(sets) > 0:
            first = sets[0]
            if first.get("ADR"):
                cursor.skip(3)
            if first.get("ID"):
                callsign = self._decode_ia5_callsign(cursor.read(6)).strip()
                if not track.target_id:
                    track.target_id = callsign
            if first.get("MHG"):
                cursor.skip(2)
            if first.get("IAS"):
                cursor.skip(2)
            if first.get("TAS"):
                cursor.skip(2)
            if first.get("SAL"):
                cursor.skip(2)
            if first.get("FSS"):
                value = cursor.read_u16()
                track.selected_altitude_m = int((value & 0x1FFF) * 25 * 0.3048)

        if len(sets) > 1:
            second = sets[1]
            if second.get("TIS"): cursor.skip(1)
            if second.get("TID"):
                rep = cursor.read_u8()
                cursor.skip(15 * rep)
            if second.get("COM"): cursor.skip(2)
            if second.get("SAB"): cursor.skip(2)
            if second.get("ACS"): cursor.skip(7)
            if second.get("BVR"): cursor.skip(2)
            if second.get("GVR"): cursor.skip(2)

        if len(sets) > 2:
            third = sets[2]
            if third.get("RAN"): cursor.skip(2)
            if third.get("TAR"): cursor.skip(2)
            if third.get("TAN"): cursor.skip(2)
            if third.get("GSP"): cursor.skip(2)
            if third.get("VUN"): cursor.skip(1)
            if third.get("MET"): cursor.skip(8)
            if third.get("EMC"): cursor.skip(1)

        if len(sets) > 3:
            fourth = sets[3]
            if fourth.get("POS"): cursor.skip(6)
            if fourth.get("GAL"): cursor.skip(2)
            if fourth.get("PUN"): cursor.skip(1)
            if fourth.get("MB"):
                rep = cursor.read_u8()
                cursor.skip(8 * rep)
            if fourth.get("IAR"): cursor.skip(2)
            if fourth.get("MAC"): cursor.skip(2)
            if fourth.get("BPS"): cursor.skip(2)

    def _parse_390(self, cursor: _Cursor, track: RadarTrack) -> None:
        octets = []
        while True:
            octet = cursor.read_u8()
            octets.append(octet)
            if octet & 0x01 == 0:
                break
            if len(octets) >= 3:
                break

        def bits(octet, masks):
            return [bool(octet & m) for m in masks]

        first_keys = ["TAG","CSN","IFI","FCT","TAC","WTC","DEP"]
        second_keys = ["DST","RDS","CFL","CTL","TOD","AST","STS"]
        third_keys = ["STD","STA","PEM","PEC"]

        first_bits = bits(octets[0], [0x80,0x40,0x20,0x10,0x08,0x04,0x02]) if len(octets) > 0 else [False]*7
        second_bits = bits(octets[1], [0x80,0x40,0x20,0x10,0x08,0x04,0x02]) if len(octets) > 1 else [False]*7
        third_bits = bits(octets[2], [0x80,0x40,0x20,0x10]) if len(octets) > 2 else [False]*4

        first = dict(zip(first_keys, first_bits))
        second = dict(zip(second_keys, second_bits))
        third = dict(zip(third_keys, third_bits))

        if first["TAG"]: cursor.skip(2)
        if first["CSN"]:
            track.acid = cursor.read(7).decode("utf-8", errors="ignore").strip()
        if first["IFI"]: cursor.skip(4)
        if first["FCT"]: cursor.skip(1)
        if first["TAC"]:
            track.aircraft_type = cursor.read(4).decode("utf-8", errors="ignore").strip()
        if first["WTC"]:
            track.wtc = chr(cursor.read_u8()).strip()
        if first["DEP"]:
            track.adep = cursor.read(4).decode("utf-8", errors="ignore").strip()
        if second["DST"]:
            track.adst = cursor.read(4).decode("utf-8", errors="ignore").strip()
        if second["RDS"]:
            track.runway = cursor.read(3).decode("utf-8", errors="ignore").strip()
        if second["CFL"]:
            track.cfl_m = cursor.read_i16() * 25 * 0.3048
        if second["CTL"]:
            cursor.skip(1)  # first byte
            track.sector_index = cursor.read_u8()
        if second["TOD"]:
            rep = cursor.read_u8()
            cursor.skip(rep * 4)
        if second["AST"]: cursor.skip(6)
        if second["STS"]: cursor.skip(1)
        if third["STD"]:
            track.sid = cursor.read(7).decode("utf-8", errors="ignore").strip()
        if third["STA"]:
            track.star = cursor.read(7).decode("utf-8", errors="ignore").strip()
        if third["PEM"]: cursor.skip(2)
        if third["PEC"]: cursor.skip(7)

    # === 辅助方法 ===
    def _read_ssr(self, cursor: _Cursor) -> str:
        b1 = cursor.read_u8() & 0x0F
        b2 = cursor.read_u8()
        value = b1 * 256 + b2
        digits = []
        for _ in range(4):
            digits.append(str(value & 0x07))
            value >>= 3
        return "".join(reversed(digits))

    def _decode_ia5_callsign(self, payload: bytes) -> str:
        if len(payload) != 6:
            return ""
        codes = [
            (payload[0] & 0xFC) >> 2,
            ((payload[0] & 0x03) << 4) | ((payload[1] & 0xF0) >> 4),
            ((payload[1] & 0x0F) << 2) | ((payload[2] & 0xC0) >> 6),
            payload[2] & 0x3F,
            (payload[3] & 0xFC) >> 2,
            ((payload[3] & 0x03) << 4) | ((payload[4] & 0xF0) >> 4),
            ((payload[4] & 0x0F) << 2) | ((payload[5] & 0xC0) >> 6),
            payload[5] & 0x3F,
        ]
        return "".join(self._ia5_to_ascii(c) for c in codes)

    @staticmethod
    def _ia5_to_ascii(value: int) -> str:
        if value == 0:
            return " "
        if value <= 26:
            return chr(value + 64)
        return chr(value)

    @staticmethod
    def _cal_heading(speed_x: float, speed_y: float) -> float:
        if speed_x == 0 and speed_y == 0:
            return 0.0
        return (math.degrees(math.atan2(speed_x, speed_y)) + 360.0) % 360.0
