# ATC Display — 空管雷达态势显示系统

> 从 UDP 组播接收 CAT062 ASTERIX 数据，实时显示飞机航迹、飞行计划和气象云图

## 概述

ATC Display 是一个基于 PySide6 的空管雷达态势显示系统，用于接收和解码 CAT062 ASTERIX 格式的雷达报文，在地图背景上实时绘制飞机航迹、速度向量、计划高度等信息，并支持航迹回放和气象云图叠加。

典型部署于空管指挥席位，接收来自雷达数据网关的组播流，在屏幕上呈现实时空中态势。

## 技术栈

- **Python 3.10+**
- **PySide6 ≥ 6.6.0** — Qt for Python，跨平台 GUI 框架
- **CAT062 ASTERIX** — 欧洲标准雷达数据交换格式（ED-2B 定义）

## 窗口布局

```
┌─────────────────────────────────────────────┐ ← 屏幕顶部
│  GIW (General Information Widget) 54px       │ 雷达状态 · 模式切换 · VEL预计线
├─────────────────────────────────────────────┤
│                                             │
│     ASD (Air Situation Display)             │ 全屏背景 · 航迹 · 地图 · 云图
│                                             │ 覆盖系统任务栏，lower()置底
│                                             │
├─────────────────────────────────────────────┤ ← 屏幕底部
│  CLW (Control & Legend Widget) 30px           │ Quit退出 · Replay · Maps
└─────────────────────────────────────────────┘

ReplayWidget   — 浮动窗口（置顶），可加载回放文件并逐帧回放
MapsWidget     — 浮动窗口（置顶），地图文件选择与加载
```

## 核心模块

| 模块 | 说明 |
|------|------|
| `cat062.py` | CAT062 ASTERIX 协议解码器，将二进制报文解析为 `RadarTrack` 航迹对象 |
| `udp_receiver.py` | UDP 组播接收线程，绑定指定端口接收 CAT062 数据报 |
| `asd_widget.py` | 主态势显示窗口，双缓冲渲染：地图背景 + 航迹符号 + 标牌（航班号/高度/速度） |
| `giw_widget.py` | 顶部信息栏，显示雷达模式、实时时间、坐标、预计时间控制 |
| `clw_widget.py` | 底部控制栏，Quit/Replay/Maps 按钮 |
| `replay_widget.py` | 回放控制浮窗，加载离线数据文件进行历史回放 |
| `maps_widget.py` | 地图选择浮窗，切换叠加的地图图层 |
| `wx_map.py` | 气象云图管理，接收UDP气象文件名并加载PNG云图叠加到态势背景 |
| `config.py` | 配置管理，从 `config/ip_setting.json` / `config/map_setting.json` 读取参数 |
| `geometry.py` | 地理坐标转换：WGS84 经纬度 ↔ 屏幕像素 ↔ 墨卡托投影 |
| `map_data.py` | 地图数据加载，支持自定义地图图层（边界、航线、扇区等） |

## 开始运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

或使用 pyproject.toml：

```bash
pip install .
```

### 2. 配置

配置文件位于 `atc_display/config/` 目录，首次运行会自动生成默认文件。

**`config/ip_setting.json`** — 网络参数：

```json
{
  "multicast_ip": "228.28.28.28",
  "multicast_port": 8107,
  "bind_host": "",
  "interface_ip": "",
  "wx_port": 0
}
```

- `multicast_ip` / `multicast_port`：CAT062 组播地址和端口
- `wx_port`：气象云图 UDP 端口（0 = 禁用）

**`config/map_setting.json`** — 地图显示参数：

```json
{
  "scale": 188,
  "center_lat": 22.3302848747725,
  "center_lon": 113.689764264606,
  "magnetic_variation": 2,
  "map_data_dir": "atc_display/mapData",
  "map_files": ["draw_BORDER", "draw_SZ_A_15"],
  "wx_base_path": "/mnt/WXMap"
}
```

- `scale`：比例尺（米/像素），控制地图放大倍数
- `center_lat/lon`：地图中心经纬度（默认深圳地区）
- `map_files`：默认加载的地图图层列表

### 3. 运行

```bash
# 常规模式
python -m atc_display

# 调试模式（输出详细日志）
DEBUG=1 python -m atc_display
```

运行后自动打开四个窗口（ASD 覆盖全屏置于底层，GIW/CLW 置顶），开始接收组播数据。

### 4. 操作说明

| 操作 | 说明 |
|------|------|
| **实时/回放切换** | GIW 底部 Realtime / Replay 按钮 |
| **预计线（VEL）** | GIW 右侧 VEL 按钮开启/关闭，点击可设置预计时间（分钟） |
| **鼠标坐标** | 移动鼠标，GIW 实时显示当前地理坐标 |
| **回放加载** | Replay 浮窗中 Load 按钮加载回放文件 |
| **地图切换** | CLW Maps 按钮打开地图选择窗口，勾选图层后 ASD 自动刷新 |
| **退出程序** | CLW 底部 Quit 按钮 |

## 目录结构

```
ATC_Display/
├── atc_display/              # 主包
│   ├── __main__.py           # 入口文件
│   ├── __init__.py
│   ├── config/               # 配置文件（首次运行自动生成）
│   │   ├── ip_setting.json
│   │   └── map_setting.json
│   ├── mapData/               # 地图数据文件
│   ├── cat062.py             # CAT062 解码器
│   ├── udp_receiver.py       # UDP 组播接收
│   ├── asd_widget.py         # 主态势窗口（~1800行）
│   ├── giw_widget.py         # 顶部信息栏
│   ├── clw_widget.py         # 底部控制栏
│   ├── replay_widget.py      # 回放控制浮窗
│   ├── maps_widget.py        # 地图选择浮窗
│   ├── wx_map.py             # 气象云图
│   ├── geometry.py           # 地理坐标转换
│   └── map_data.py           # 地图数据加载
├── pyproject.toml
└── requirements.txt
```

## CAT062 数据字段

解析的航迹字段包括：

- **位置**：纬度、经纬度（WGS84）
- **运动**：速度（km/h）、航向角（°）、水平速度分量
- **高度**：测量高度、QNH 修正高度、MCP/FCU 选择高度、CFL 计划高度
- **识别**：SSR 应答机编码、航班号（Target ID / ACID）
- **飞行计划**：机型、尾流等级、起降机场、跑道、SID/STAR 进场离场程序
- **时间**：航迹时间、接收时间

## 已知问题 & 修复记录

项目根目录下的文档记录了开发过程中遇到的问题与修复：

- `BUGS_FIXED.md` — Bug 修复记录
- `CODE_IMPROVEMENTS.md` — 代码结构改进
- `FIXES_SUMMARY.md` — 修复总结
- `MODULE_NOT_FOUND_FIX.md` — 导入问题修复
- `MULTI_MEASURE_LINES.md` — 多测量线功能
- `OPTIMIZATION_II.md` — 性能优化
- `PREDICT_LINE_FEATURE.md` — 预计线功能设计
- `PREDICT_LINE_TEST_PLAN.md` — 预计线测试计划
- `TRACK_DIAGNOSTICS.md` — 航迹诊断文档

## 致谢

CAT062 解码逻辑参考了以下项目：

- C# `CAT062.cs` 原型实现
- `atc_data_hub/parsers/cat062.py` — Python 参考实现
