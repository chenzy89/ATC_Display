"""
雷达数据回放引擎
对应 C# FrmReplay 的数据加载和回放逻辑

.rcd 文件格式 (参考 storage.py append_radar_payload):
  每帧 = 8字节OADate(小端double) + CAT062原始payload
"""
from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Tuple

logger = logging.getLogger("atc_display.replay")

# 默认雷达数据路径
DEFAULT_RADAR_DIR = Path(__file__).parent / "radarData"


def oa_date_to_datetime(oa_date: float) -> datetime:
    """OADate (double) → datetime (与 C# DateTime.FromOADate 完全一致)"""
    # OADate 的起点是 1899-12-30 00:00
    OA_EPOCH = datetime(1899, 12, 30)
    return OA_EPOCH + timedelta(days=oa_date)


def datetime_to_oa_date(dt: datetime) -> float:
    """datetime → OADate"""
    OA_EPOCH = datetime(1899, 12, 30)
    return (dt - OA_EPOCH).total_seconds() / 86400.0


class RadarFrame:
    """一个雷达帧 = 时间戳 + CAT062 payload"""
    __slots__ = ("timestamp", "payload")

    def __init__(self, timestamp: datetime, payload: bytes):
        self.timestamp = timestamp
        self.payload = payload


def load_radar_files(
    start_time: datetime,
    end_time: datetime,
    radar_dir: Path = DEFAULT_RADAR_DIR,
) -> List[RadarFrame]:
    """
    加载指定时间范围内的 .rcd 文件，返回时间排序后的帧列表。
    文件命名规则: RD{yyMMddHH}_{0|1}.rcd
      _0 = 前30分钟 (00~29), _1 = 后30分钟 (30~59)
    """
    frames: List[RadarFrame] = []

    # 计算需要扫描的小时范围
    current = start_time.replace(minute=0, second=0, microsecond=0)
    while current <= end_time:
        hour_str = current.strftime("%y%m%d%H")
        for suffix in (0, 1):
            path = radar_dir / f"RD{hour_str}_{suffix}.rcd"
            if path.exists():
                _parse_rcd_file(path, frames, start_time, end_time)
        current += timedelta(hours=1)

    # 按时间戳排序
    frames.sort(key=lambda f: f.timestamp)
    logger.info(
        "回放: 加载 %d 帧，时间范围 %s → %s",
        len(frames),
        start_time.strftime("%Y-%m-%d %H:%M:%S"),
        end_time.strftime("%Y-%m-%d %H:%M:%S"),
    )
    return frames


def _parse_rcd_file(
    path: Path,
    out: List[RadarFrame],
    start_time: datetime,
    end_time: datetime,
) -> None:
    """解析单个 .rcd 文件，将时间范围内的帧追加到 out"""
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("无法读取 %s: %s", path, exc)
        return

    pos = 0
    total = len(data)
    while pos + 8 <= total:
        # 读取 8 字节 OADate
        oa_bytes = data[pos:pos + 8]
        oa_val = struct.unpack_from("<d", oa_bytes)[0]
        pos += 8

        try:
            ts = oa_date_to_datetime(oa_val)
        except (OverflowError, ValueError, OSError):
            # 跳过损坏帧，尝试继续解析 (不严格: 逐字节会很慢, 直接 break)
            break

        # 读取 CAT062 payload: 先读长度
        # CAT062 帧头: 第1字节=CAT, 第2-3字节=长度 (大端)
        if pos + 3 > total:
            break
        cat = data[pos]
        pkt_len = data[pos + 1] * 256 + data[pos + 2]
        if pkt_len < 3 or pos + pkt_len > total:
            break

        payload = data[pos:pos + pkt_len]
        pos += pkt_len

        # 时间范围过滤
        if ts < start_time or ts > end_time:
            continue

        out.append(RadarFrame(timestamp=ts, payload=payload))


class ReplayEngine:
    """
    雷达回放引擎
    使用方:
      1. engine.load(start_time, duration_minutes) → True/False
      2. engine.start()
      3. engine.pause() / engine.resume()
      4. engine.stop()
      5. 每次 tick() → 返回当前应该显示的帧 payload 列表 + 当前回放时间
    """

    def __init__(
        self,
        radar_dir: Path = DEFAULT_RADAR_DIR,
        on_frame: Optional[Callable[[List[bytes], datetime], None]] = None,
        on_finished: Optional[Callable[[], None]] = None,
    ):
        self.radar_dir = radar_dir
        self.on_frame = on_frame       # 回调: (payloads, replay_time)
        self.on_finished = on_finished # 回调: 回放结束

        self._frames: List[RadarFrame] = []
        self._idx: int = 0
        self._replay_time: Optional[datetime] = None
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._speed: int = 1
        self._paused: bool = False
        self._running: bool = False
        self._loaded: bool = False

    # ── 属性 ──────────────────────────────────────────
    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def frame_count(self) -> int:
        return len(self._frames)

    @property
    def replay_time(self) -> Optional[datetime]:
        return self._replay_time

    @property
    def speed(self) -> int:
        return self._speed

    @speed.setter
    def speed(self, v: int) -> None:
        self._speed = max(1, int(v))

    # ── 控制 ──────────────────────────────────────────
    def load(self, start_time: datetime, duration_minutes: int) -> bool:
        """加载数据, 返回是否成功 (有数据则为 True)"""
        self._frames = []
        self._idx = 0
        self._loaded = False
        self._running = False
        self._paused = False

        end_time = start_time + timedelta(minutes=duration_minutes)
        self._start_time = start_time
        self._end_time = end_time
        self._replay_time = start_time

        try:
            self._frames = load_radar_files(start_time, end_time, self.radar_dir)
        except Exception as exc:
            logger.error("加载雷达数据失败: %s", exc)
            return False

        self._loaded = True
        return True  # 即使0帧也返回True (文件可能不存在)

    def start(self) -> None:
        """开始回放 (必须先 load)"""
        if not self._loaded:
            return
        self._idx = 0
        self._replay_time = self._start_time
        self._running = True
        self._paused = False

    def pause(self) -> None:
        """暂停"""
        if self._running:
            self._paused = True

    def resume(self) -> None:
        """继续"""
        if self._running:
            self._paused = False

    def stop(self) -> None:
        """停止"""
        self._running = False
        self._paused = False
        self._idx = 0
        self._replay_time = self._start_time

    def tick(self, elapsed_ms: int) -> Tuple[List[bytes], Optional[datetime]]:
        """
        定时器每次调用此方法，推进回放时间。
        elapsed_ms: 距离上次 tick 的毫秒数 (通常 = 定时器间隔)
        返回: (本次需要显示的 payload 列表, 当前回放时间)
        """
        if not self._running or self._paused or self._replay_time is None:
            return [], self._replay_time

        # 回放时间推进: elapsed_ms * speed
        advance_ms = elapsed_ms * self._speed
        self._replay_time += timedelta(milliseconds=advance_ms)

        # 收集所有时间戳 <= 当前回放时间的帧
        payloads: List[bytes] = []
        while self._idx < len(self._frames):
            frame = self._frames[self._idx]
            if frame.timestamp <= self._replay_time:
                payloads.append(frame.payload)
                self._idx += 1
            else:
                break

        # 检查是否结束
        if self._idx >= len(self._frames) and self._replay_time >= (self._end_time or self._replay_time):
            self._running = False
            if self.on_finished:
                self.on_finished()

        return payloads, self._replay_time
