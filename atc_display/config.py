"""
配置管理模块
从 JSON 文件读取 CAT062 网络配置和地图参数
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 项目根目录 (E:\ATC_Display\atc_display)
PROJECT_ROOT = Path(__file__).parent

# 默认配置文件路径
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_IP_SETTING = DEFAULT_CONFIG_DIR / "ip_setting.json"
DEFAULT_MAP_SETTING = DEFAULT_CONFIG_DIR / "map_setting.json"


@dataclass
class NetworkConfig:
    """CAT062 组播网络配置"""
    multicast_ip: str = "228.28.28.28"
    multicast_port: int = 8107
    bind_host: str = ""          # 绑定地址, 空表示绑定所有接口
    interface_ip: str = ""        # 网卡 IP, 用于加入组播组; 空则用 INADDR_ANY
    wx_port: int = 0             # 气象云图 UDP 接收端口 (0=禁用)


@dataclass
class MapConfig:
    """地图显示配置"""
    scale: int = 188             # 地图比例尺 (米/像素)
    center_lat: float = 22.3302848747725
    center_lon: float = 113.689764264606
    magnetic_variation: int = 2   # 磁差 (度)
    map_data_dir: str = str(PROJECT_ROOT / "mapData")
    map_files: list[str] = field(default_factory=lambda: ["draw_BORDER", "draw_SZ_A_15"])
    wx_base_path: str = "/mnt/WXMap"  # 云图文件根目录


@dataclass
class AppConfig:
    """应用总配置"""
    network: NetworkConfig = field(default_factory=NetworkConfig)
    map: MapConfig = field(default_factory=MapConfig)


def load_json_config(path: Path) -> dict[str, Any]:
    """读取 JSON 配置文件"""
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_default_configs() -> None:
    """生成默认配置文件 (如果不存在)"""
    DEFAULT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not DEFAULT_IP_SETTING.exists():
        default_ip = {
            "multicast_ip": "228.28.28.28",
            "multicast_port": 8107,
            "bind_host": "",
            "interface_ip": ""
        }
        with open(DEFAULT_IP_SETTING, "w", encoding="utf-8") as f:
            json.dump(default_ip, f, indent=2, ensure_ascii=False)

    if not DEFAULT_MAP_SETTING.exists():
        default_map = {
            "scale": 188,
            "center_lat": 22.3302848747725,
            "center_lon": 113.689764264606,
            "magnetic_variation": 2,
            "map_data_dir": str(PROJECT_ROOT / "mapData"),
            "map_files": ["draw_BORDER", "draw_SZ_A_15"]
        }
        with open(DEFAULT_MAP_SETTING, "w", encoding="utf-8") as f:
            json.dump(default_map, f, indent=2, ensure_ascii=False)


def _resolve_map_dir(path: str) -> str:
    """解析地图目录路径，兼容相对路径（相对于 PROJECT_ROOT）和绝对路径"""
    p = Path(path)
    if p.is_absolute():
        return path
    # 相对路径 → 基于 PROJECT_ROOT (atc_display/) 解析
    resolved = PROJECT_ROOT / path
    return str(resolved.resolve())


def _validate_config(config: AppConfig) -> None:
    """验证配置值的有效性"""
    # 网络配置验证
    if not (0 < config.network.multicast_port < 65536):
        raise ValueError(f"Invalid multicast_port: {config.network.multicast_port}, must be 1-65535")
    
    if config.network.wx_port < 0 or config.network.wx_port >= 65536:
        raise ValueError(f"Invalid wx_port: {config.network.wx_port}, must be 0 or 1-65535")
    
    # 坐标验证 (WGS84 范围)
    if not (-90 <= config.map.center_lat <= 90):
        raise ValueError(f"Invalid center_lat: {config.map.center_lat}, must be in [-90, 90]")
    if not (-180 <= config.map.center_lon <= 180):
        raise ValueError(f"Invalid center_lon: {config.map.center_lon}, must be in [-180, 180]")
    
    # 地图配置验证
    if config.map.scale <= 0:
        raise ValueError(f"Invalid scale: {config.map.scale}, must be > 0")
    
    map_data_path = Path(config.map.map_data_dir)
    if not map_data_path.exists():
        raise FileNotFoundError(f"Map data directory does not exist: {config.map.map_data_dir}")


def load_app_config() -> AppConfig:
    """加载完整应用配置"""
    save_default_configs()

    ip_data = load_json_config(DEFAULT_IP_SETTING)
    map_data = load_json_config(DEFAULT_MAP_SETTING)

    config = AppConfig(
        network=NetworkConfig(
            multicast_ip=ip_data.get("multicast_ip", "228.28.28.28"),
            multicast_port=ip_data.get("multicast_port", 8107),
            bind_host=ip_data.get("bind_host", ""),
            interface_ip=ip_data.get("interface_ip", ""),
            wx_port=ip_data.get("wx_port", 0),
        ),
        map=MapConfig(
            scale=map_data.get("scale", 188),
            center_lat=map_data.get("center_lat", 22.3302848747725),
            center_lon=map_data.get("center_lon", 113.689764264606),
            magnetic_variation=map_data.get("magnetic_variation", 2),
            map_data_dir=_resolve_map_dir(map_data.get("map_data_dir", str(PROJECT_ROOT / "mapData"))),
            map_files=map_data.get("map_files", ["draw_BORDER", "draw_SZ_A_15"]),
            wx_base_path=map_data.get("wx_base_path", "/mnt/WXMap"),
        ),
    )
    
    # 验证配置值
    _validate_config(config)
    return config
