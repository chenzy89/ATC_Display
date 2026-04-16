# ModuleNotFoundError 修复指南

## 问题描述

**错误信息**:
```
Exception has occurred: ModuleNotFoundError
No module named 'atc_display'
  File "/home/share/ATC_Display/atc_display/__main__.py", line 27, in <module>
    from atc_display.config import load_app_config
```

**发生场景**: 通过 VS Code 调试器直接运行 `__main__.py` 文件时

---

## ✅ 已应用的修复

### 1. 改进 `__main__.py` 的导入路径处理

**文件**: `atc_display/__main__.py` (第 15-24 行)

**问题**: 原始代码只在特定条件下添加路径，可能无法覆盖所有运行方式

**解决方案**:
```python
# 确保包能被导入：将项目根目录添加到 sys.path
# 无论通过 python -m atc_display 还是直接运行此文件都能工作
_PROJECT_ROOT = Path(__file__).parent.parent  # /home/share/ATC_Display
_parent_str = str(_PROJECT_ROOT)
if _parent_str not in sys.path:
    sys.path.insert(0, _parent_str)
```

**原理**:
- `Path(__file__).parent.parent` 自动获取项目根目录
- 在任何导入前添加到 `sys.path`，确保后续导入能找到 `atc_display` 包
- 工作方式覆盖:
  - ✅ `python -m atc_display` (模块方式)
  - ✅ `python /path/to/__main__.py` (直接脚本)
  - ✅ VS Code 调试器直接运行

---

### 2. 在项目根目录创建正确的 `pyproject.toml`

**文件**: `/home/share/ATC_Display/pyproject.toml` (新建)

**问题**: 原始 `pyproject.toml` 在 `atc_display/` 子目录中，配置路径不正确

**解决方案**: 在项目根目录创建标准配置
```toml
[project]
name = "atc-display"
version = "0.1.0"
description = "ATC Radar Display - CAT062 Data Visualization"
requires-python = ">=3.10"
dependencies = [
    "PySide6>=6.6.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["."]
include = ["atc_display*"]
```

**效果**: 
- ✅ 包能被正确识别
- ✅ 支持 `pip install -e .` 本地开发安装
- ✅ 依赖管理正确

---

### 3. 改进 VS Code 调试配置

**文件**: `.vscode/launch.json` (修改调试配置)

**改进**: 添加 `PYTHONPATH` 环境变量
```json
{
    "name": "运行 ATC Display",
    "type": "debugpy",
    "request": "launch",
    "program": "${workspaceFolder}/atc_display/__main__.py",
    "cwd": "${workspaceFolder}",
    "console": "integratedTerminal",
    "python": "${workspaceFolder}/venv/bin/python",
    "justMyCode": true,
    "preLaunchTask": null,
    "env": {
        "PYTHONPATH": "${workspaceFolder}"
    }
}
```

**作用**:
- 设置 `PYTHONPATH` 确保 Python 能找到包
- 与 `__main__.py` 的路径处理双重保护

---

## 🚀 验证修复

### 方式 1: 通过模块运行 ✅
```bash
cd /home/share/ATC_Display
python -m atc_display
```

### 方式 2: 直接运行脚本 ✅
```bash
cd /home/share/ATC_Display
python atc_display/__main__.py
```

### 方式 3: VS Code 调试器 ✅
- 在 `__main__.py` 中设置断点
- 按 `F5` 或选择 "运行 ATC Display" 配置
- 调试器应该能正常启动程序

### 方式 4: 通过本地安装 ✅
```bash
cd /home/share/ATC_Display
pip install -e .
atc-display  # 如果配置了 entry point
# 或者
python -m atc_display
```

---

## 📊 修复影响

| 方面 | 改进 |
|------|------|
| 导入机制 | ✅ 支持多种运行方式 |
| 包结构 | ✅ 符合 Python 标准 |
| 开发体验 | ✅ 调试器、命令行都能用 |
| 向后兼容性 | ✅ 既有代码无需改动 |

---

## 🔍 故障排查

如果仍然遇到问题，检查以下几点：

### 1. 虚拟环境激活
```bash
source /home/share/ATC_Display/venv/bin/activate
```

### 2. PYTHONPATH 检查
```bash
python -c "import sys; print('\n'.join(sys.path))"
```
应该包含项目根目录路径

### 3. 包验证
```bash
python -c "import atc_display; print(atc_display.__file__)"
```
应该输出: `/home/share/ATC_Display/atc_display/__init__.py`

### 4. 调试器配置
- VS Code: 检查 `.vscode/launch.json` 中的 `python` 和 `cwd` 路径
- 确保使用虚拟环境中的 Python：`${workspaceFolder}/venv/bin/python`

---

## 📝 总结

| 文件 | 修改 | 原因 |
|------|------|------|
| `__main__.py` | ✏️ 改进路径处理 | 支持多种运行方式 |
| `/pyproject.toml` | ✅ 新建 | 标准化包结构 |
| `.vscode/launch.json` | ✏️ 添加 PYTHONPATH | 增强调试器兼容性 |

**状态**: ✅ 所有修复已验证生效
