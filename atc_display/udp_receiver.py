"""
UDP 组播接收模块
共享端口方式接收 CAT062 数据报
参考: 参考项目的 _create_socket() 实现
"""
from __future__ import annotations

import logging
import socket
import struct
from typing import Callable, Optional

from .cat062 import Cat062Parser, RadarTrack

logger = logging.getLogger("atc_display.udp")


def create_multicast_receiver(
    multicast_ip: str,
    multicast_port: int,
    bind_host: str = "",
    interface_ip: str = "",
) -> socket.socket:
    """
    创建 UDP 组播接收 socket, 支持端口共享
    使用 SO_REUSEADDR 允许多个进程同时绑定同一端口

    :param multicast_ip: 组播地址, 如 "228.28.28.28"
    :param multicast_port: 组播端口, 如 8107
    :param bind_host: 绑定地址, 空字符串表示绑定所有接口
    :param interface_ip: 网卡 IP, 用于指定从哪个网卡接收组播数据
    """
    # 参数验证
    if not (0 < multicast_port < 65536):
        raise ValueError(f"Invalid multicast_port: {multicast_port}, must be 1-65535")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    # Windows 不支持 SO_REUSEPORT, 但 SO_REUSEADDR 在 Windows 上
    # 已经允许多个 socket 绑定同一 UDP 端口
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError) as exc:
        logger.debug("SO_REUSEPORT not supported (platform-specific): %s", exc)

    try:
        sock.bind((bind_host, multicast_port))
    except OSError as exc:
        # 回退: 尝试绑定到空地址
        try:
            sock.bind(("", multicast_port))
            logger.warning("无法绑定 %s:%d, 已回退到绑定所有接口", bind_host, multicast_port)
        except OSError as bind_exc:
            sock.close()
            raise OSError(f"Failed to bind to {bind_host}:{multicast_port} or all interfaces: {bind_exc}") from bind_exc

    if multicast_ip:
        membership = struct.pack(
            "=4s4s",
            socket.inet_aton(multicast_ip),
            socket.inet_aton(interface_ip or "0.0.0.0"),
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
        logger.info("已加入组播组 %s:%d (网卡: %s)", multicast_ip, multicast_port, interface_ip or "0.0.0.0")

    sock.setblocking(False)
    return sock


class CAT062Receiver:
    """CAT062 组播数据接收器"""

    def __init__(
        self,
        multicast_ip: str,
        multicast_port: int,
        bind_host: str = "",
        interface_ip: str = "",
        on_tracks: Optional[Callable[[list[RadarTrack]], None]] = None,
    ):
        """
        :param on_tracks: 收到航迹数据时的回调函数
        """
        self.parser = Cat062Parser()
        self.on_tracks = on_tracks
        self._sock: Optional[socket.socket] = None
        self._running = False
        self._multicast_ip = multicast_ip
        self._multicast_port = multicast_port
        self._bind_host = bind_host
        self._interface_ip = interface_ip

    def start(self) -> None:
        """启动接收"""
        if self._running:
            return
        self._sock = create_multicast_receiver(
            self._multicast_ip,
            self._multicast_port,
            self._bind_host,
            self._interface_ip,
        )
        self._running = True
        logger.info("CAT062 接收器已启动")

    def stop(self) -> None:
        """停止接收"""
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        logger.info("CAT062 接收器已停止")

    def poll(self) -> int:
        """
        非阻塞轮询一次 socket, 返回收到的报文数
        由 UI 定时器调用
        """
        if not self._sock or not self._running:
            return 0

        received_count = 0
        while True:
            try:
                payload, addr = self._sock.recvfrom(65535)
            except BlockingIOError:
                break
            except OSError as exc:
                logger.warning("recv 失败: %s", exc)
                break

            received_count += 1
            logger.debug("收到 CAT062 报文 #%d, 大小: %d 字节", received_count, len(payload))
            try:
                tracks = self.parser.parse_datagram(payload)
                if tracks:
                    logger.debug("解析 CAT062 报文成功: 包含 %d 条航迹", len(tracks))
                    if self.on_tracks:
                        self.on_tracks(tracks)
                else:
                    logger.debug("解析 CAT062 报文: 不包含航迹数据")
            except Exception as exc:
                logger.error("解析 CAT062 报文失败: %s", exc)

        if received_count > 0:
            logger.debug("轮询完成: 本次收到 %d 个报文", received_count)
        return received_count
