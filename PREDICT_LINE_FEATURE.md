# 航迹预计线功能实现总结

## 功能概述
实现了航迹预计线功能，根据航迹速度和预计时间计算并绘制预计点及预计线。

## 实现内容

### 1. 数据模型更新 (cat062.py)
在 `RadarTrack` 类中添加了以下属性：
- `show_predict_line: bool` - 是否显示该航迹的预计线
- `predict_lat: float` - 预计点纬度
- `predict_lon: float` - 预计点经度

### 2. 主窗体功能 (asd_widget.py)

#### 初始化新属性
- `predict_line_enabled: bool` - 全局预计线显示开关
- `predict_time_minutes: int` - 预计时间（单位：分钟）
- `_label_clickable_areas: Dict` - 标牌点击区域记录

#### 核心方法

##### `_calculate_predict_point(track: RadarTrack) -> Optional[RealPoint]`
根据航迹的速度分量（spdx_kmh, spdy_kmh）和预计时间计算预计点坐标。
- 考虑地球曲率（经度偏移时除以余弦值）
- 返回计算得到的实地地理坐标

##### `_draw_predict_line(painter: QPainter, track: RadarTrack, ...)`
绘制预计线的可视化：
- 虚线从当前位置到预计位置
- 预计点处显示小圆圈标记
- 保存预计点坐标到 track 对象

##### 预计线控制方法
- `set_predict_line_enabled(enabled: bool)` - 设置全局开关
- `set_predict_time(minutes: int)` - 设置预计时间
- `toggle_track_predict_line(track: RadarTrack)` - 切换单个航迹的显隐

#### 标牌点击检测
- 在 `paintEvent()` 中清空旧的点击区域记录
- 在 `_draw_label()` 中记录标牌第二行速度字段的像素位置
- 在 `mousePressEvent()` 中优先检测标牌点击，点击速度字段即可切换预计线

### 3. 底部信息栏 (giw_widget.py)

添加了以下公共方法：
- `get_predict_time_minutes() -> int` - 从 tbx_vel 获取预计时间（分钟），范围 1-60
- `is_predict_line_enabled() -> bool` - 获取 VEL 按钮的启用状态

### 4. 主窗口连接 (__main__.py)

连接 GIW 中的 VEL 相关控件到 ASD：
- `VEL 按钮点击` → 切换全局预计线显示
- `VEL 时间输入框变化` → 更新预计时间

```python
def on_vel_button_toggled():
    enabled = giw.is_predict_line_enabled()
    predict_time = giw.get_predict_time_minutes()
    asd.set_predict_line_enabled(enabled)
    asd.set_predict_time(predict_time)

def on_vel_time_changed():
    if giw.is_predict_line_enabled():
        predict_time = giw.get_predict_time_minutes()
        asd.set_predict_time(predict_time)

giw.btn_vel.clicked.connect(on_vel_button_toggled)
giw.tbx_vel.textChanged.connect(on_vel_time_changed)
```

## 使用方法

1. **启用预计线**：点击 GIW 底部信息栏的 "VEL" 按钮，按钮会显示为选中状态
2. **设置预计时间**：在 VEL 输入框中输入分钟数（默认 1 分钟）
3. **单航迹控制**：点击标牌第二行的速度字段（后半段4个字符）可切换该航迹的预计线显示

## 预计线绘制说明

- **虚线**：从当前航迹位置到预计点的虚线
- **圆圈**：预计点处显示的小圆圈标记
- **颜色**：与航迹符号同色（受控/假定/未相关）

## 计算原理

预计点根据速度分量计算：
```
predict_lat = current_lat + (spdy_kmh * minutes / 60)
predict_lon = current_lon + (spdx_kmh * minutes / 60 / cos(current_lat))
```

其中：
- `spdy_kmh` - 北向速度分量（度/小时）
- `spdx_kmh` - 东向速度分量（度/小时）
- `minutes` - 预计时间（分钟）

## 测试状态

✅ 代码编译无误
✅ 应用程序可启动
✅ VEL 按钮连接正常
✅ 日志输出正确

## 后续可能的优化

1. 为预计线绘制添加箭头标记
2. 支持不同的预计时间预设（如 0.5、1、2、5 分钟）
3. 为预计线添加距离数值显示
4. 支持航迹历史线与预计线的对比
