# Stack-chan 固件接入（K151）

**状态：硬件规格已确认，固件骨架未上板验证。** 本目录现在包含可编译方向的 PlatformIO 工程，
但当前环境没有 ESP32 工具链，**未执行 `pio run`，也未在 K151 实机运行**。请按
[设备能力与上板清单](../../docs/STACKCHAN_DEVICE_PROFILE.md) 逐项验收后再标记完成。

## 文件

| 路径 | 作用 |
| --- | --- |
| `platformio.ini` | CoreS3 + StackChan-BSP + ArduinoJson |
| `include/board_config.h` | 轮询周期、限位、文本上限 |
| `include/device_protocol.h` / `src/device_protocol.cpp` | 白名单解析、payload 二次校验、事件构造 |
| `src/main.cpp` | Wi-Fi + REST 轮询、ACK/终态、触摸、NVS 恢复 |
| `src/selftest.cpp` | LAN-01 硬件自检（屏幕/舵机/12 灯/喇叭/三区触摸/IMU） |
| `include/secrets.example.h` | Wi-Fi SSID/密码、设备 token |

## 构建

```bash
cd firmware/stackchan
cp include/secrets.example.h include/secrets.h   # 填写 Wi-Fi 与设备 token
pio run
pio run -t upload
pio device monitor -b 115200
```

`secrets.h` 已在根 `.gitignore` 中，不要提交。

## LAN-01 硬件自检

不需要 Wi-Fi，串口打印 PASS/FAIL，按提示触摸三个区域：

```bash
pio run -e stackchan-selftest -t upload
pio device monitor -b 115200
```

自检覆盖：屏幕颜色/文字、X/Y 舵机往返、12 路 RGB、喇叭双音、front/middle/back 三区触摸、
IMU 加速度读取。把串口输出贴进上板记录即可作为 LAN-01 的手工验收证据。

## 已实现

- `GET /api/v1/devices/{id}/pending` 轮询，`POST .../events` 回执；
- 六类白名单命令：表情、字幕+提示音、引导计时、倒计时、头颈预设、取消；
- 触摸：点按 = 提前完成（`touch_confirmed`），长按 1.5s = 停止（`user_declined`）；
- NVS 记录已 ACK 命令与终态：重启后不重复执行物理动作，只补发终态；
- 舵机角度硬限幅（X ±1200、Y 50–850），预设动作结束回中；
- 设备端二次校验：非法 payload 直接 `FAILED(invalid_payload)`。

## 明确未完成

- **未编译、未上板**：PlatformIO/ESP32 工具链与真机均未验证；
- **语音**：`SPEAK_TEXT` 只显示字幕并播放提示音，没有 TTS/音频流；
- **TLS**：当前 `setInsecure()` 仅用于本地联调，生产必须固定 CA 并做设备配对；
- **离线队列**：HTTP 失败会重试 3 次并依赖 NVS 重放终态，但尚无容量受限的磁盘队列；
- **物理动作幂等**：NVS 只保存最后一条命令；连续多命令下的断电恢复仍需实机测试；
- **跌倒检测**：未实现（后续 LAN 任务）。

设备端只执行六类白名单指令，不接受任意舵机角度/速度、任意文本或模型生成的底层指令。
机器人回执不代表用户完成活动。

参考：<https://docs.m5stack.com/en/StackChan>
