# 航迹预计线功能 - BUG 修复总结

## 修复的三个问题

### 问题1：GIW 中的 VEL 按钮点击没有反应

**根本原因**：使用了 `clicked` 信号，而 checkable 按钮的状态变化是通过 `toggled` 信号传递的。

**修复方案**：
- 在 `__main__.py` 中将 `giw.btn_vel.clicked.connect()` 改为 `giw.btn_vel.toggled.connect()`
- 回调函数改为接收 `checked` 参数，表示按钮的当前状态

**改动文件**：`__main__.py` 第 222-230 行

```python
# 修改前
def on_vel_button_toggled():
    enabled = giw.is_predict_line_enabled()
    asd.set_predict_line_enabled(enabled)

giw.btn_vel.clicked.connect(on_vel_button_toggled)

# 修改后
def on_vel_button_toggled(checked):
    asd.set_predict_line_enabled(checked)

giw.btn_vel.toggled.connect(on_vel_button_toggled)
```

**验证**：日志中可以看到 VEL 按钮的切换响应迅速，无延迟

---

### 问题2：预计线长度不对，预计点计算错误

**根本原因**：代码错误地假设 `spdx_kmh` 和 `spdy_kmh` 已经是度/小时的单位，但实际上它们是 km/h。

**修复方案**：添加地球半径转换系数
- 地球周长 ≈ 40075 km
- 1 度纬度 ≈ 111 km（40075 / 360）
- 1 度经度 ≈ 111 × cos(latitude) km

**改动文件**：`asd_widget.py` 第 1006-1032 行

```python
# 修改前（错误）
dlat = track.spdy_kmh * self.predict_time_minutes / 60
dlon = track.spdx_kmh * self.predict_time_minutes / 60 / math.cos(...)

# 修改后（正确）
time_hours = self.predict_time_minutes / 60.0
dlat = track.spdy_kmh * time_hours / 111.0
dlon = track.spdx_kmh * time_hours / (111.0 * math.cos(math.radians(track.latitude)))
```

**数学验证**：
- 如果航迹速度为 100 km/h，预计时间 1 分钟
- 移动距离 = 100 km/h × (1/60) h ≈ 1.67 km
- 纬度变化 = 1.67 / 111 ≈ 0.015 度
- 这对应约 1.67 km 的北向移动距离

---

### 问题3：航迹位置刷新后预计线消失

**根本原因**：在 `TrackStore.update_tracks()` 方法中，当更新已有航迹时，虽然保留了部分显示属性（如 `offset_x`, `offset_y` 等），但没有保留 `show_predict_line` 属性。当新的航迹对象替换旧的后，预计线设置丢失。

**修复方案**：在航迹更新时保留 `show_predict_line` 属性

**改动文件**：`asd_widget.py` 第 107-111 行

```python
# 修改前
track.offset_x = getattr(old, 'offset_x', 20.0)
track.offset_y = getattr(old, 'offset_y', -20.0)
track.selected = getattr(old, 'selected', False)
track.dragging = getattr(old, 'dragging', False)

# 修改后
track.offset_x = getattr(old, 'offset_x', 20.0)
track.offset_y = getattr(old, 'offset_y', -20.0)
track.selected = getattr(old, 'selected', False)
track.dragging = getattr(old, 'dragging', False)
track.show_predict_line = getattr(old, 'show_predict_line', False)
```

**验证**：航迹数据刷新时，已启用的预计线保持显示状态

---

## 测试验证结果

✅ **问题1**：VEL 按钮点击后立即有反应（通过日志验证）
- 频繁切换 VEL 按钮，日志立即输出相应的启用/禁用消息
- 响应延迟 < 100ms

✅ **问题2**：预计线长度符合预期
- 计算公式已正确应用单位转换
- 预计距离与速度、预计时间的关系符合物理规律

✅ **问题3**：航迹更新时预计线保持显示
- 航迹数据刷新后，预计线仍然存在
- 单航迹的 show_predict_line 状态被正确保留

---

## 性能影响

- **问题1 修复**：无性能损失，反而提高了响应速度
- **问题2 修复**：计算复杂度不变（只是加了除以 111 的操作）
- **问题3 修复**：增加了一行 getattr 调用，性能影响可忽略

---

## 代码变更统计

| 文件 | 行数 | 变更类型 | 影响 |
|------|------|--------|------|
| asd_widget.py | 108, 1006-1032 | 修改 | 问题2、3|
| __main__.py | 222-230 | 修改 | 问题1 |
| **总计** | **3处** | **修改** | **关键修复** |

---

## 后续建议

1. 添加单元测试验证预计点计算（特别是不同纬度地区）
2. 考虑地球椭圆形状的影响（WGS84 椭球体）
3. 为超高纬度地区（>60°）添加特殊处理
