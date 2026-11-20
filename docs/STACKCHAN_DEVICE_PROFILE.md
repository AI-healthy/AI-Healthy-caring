# LAN-01 · Stack-chan 设备能力与硬件验证

状态：**规格确认完成，实机验证待执行**。本文是 `firmware/stackchan/` 的能力基线，
不声称已经上板跑通。所有“待实机”项必须在 K151 到货后按第 6 节逐条签字。

## 1. 目标机型

| 项 | 结论 |
| --- | --- |
| SKU | M5Stack **StackChan K151** |
| 主控 | CoreS3（ESP32-S3，240MHz，16MB Flash / 8MB PSRAM） |
| 官方 SDK | [M5Stack StackChan-BSP](https://github.com/m5stack/StackChan-BSP)（Arduino/PlatformIO） |
| 备选 | 小智 StackChan 固件 / ESPHome；仅作对照，不作为本项目主路径 |
| 采购/资料 | <https://docs.m5stack.com/en/StackChan> |

选择 K151 的理由：官方 BSP 已封装屏幕、双舵机、12 路 RGB、三区触摸、IMU 与电池计，
可以把 LAN 的工作集中在**白名单协议、交互状态机、断网重试**，而不是重复写驱动。

## 2. 能力矩阵

| 能力 | 硬件/接口 | 本项目用法 | 状态 |
| --- | --- | --- | --- |
| 320×240 屏幕 | CoreS3 显示屏 | 表情、字幕、计时 | 规格确认；表情已实机 |
| 表情 | 固件本地绘制 | `SET_EXPRESSION`：happy / neutral / sleepy | **已实机**（基础表情响应，2026-11-19） |
| 头颈动作 | 2× SCS 总线舵机 | `MOVE_HEAD_PRESET`：nod / shake / tilt / look_around / greet | **已实机**（动作正常；限位待记录） |
| 12 路 RGB | 机身 IO 扩展 | 状态灯、告警、呼吸 | 规格确认；待实机 |
| 三区触摸 | Si12T（front/middle/back） | 触摸确认/拒绝、唤醒 | 规格确认；待实机 |
| 扬声器 | 1W 喇叭 | 提示音；语音内容待 TTS 方案 | **部分待定**（见第 4 节） |
| 语音唤醒 | CoreS3 麦克风 + 设备现有固件 | 仅现有固件验证；本仓库固件未实现唤醒词 | **已实机**（现有固件） |
| 9 轴 IMU | CoreS3 | 摇晃/跌倒检测（后续） | 规格确认；待实机 |
| 麦克风/摄像头 | CoreS3 | **MVP 不使用**，不上传音频/图像 | 明确排除（语音唤醒除外） |
| NFC/红外 | 机身 | MVP 不使用 | 明确排除 |

> 实机记录与证据边界见 [STACKCHAN_HARDWARE_TEST_LOG.md](STACKCHAN_HARDWARE_TEST_LOG.md)。
> “已实机”指 K151 现有固件的基础能力验证，不代表本仓库固件已编译/烧录。

## 3. 舵机安全约定

BSP 角度单位 0.1°；物理范围 X `-1280..1280`、Y `0..900`。固件侧统一限幅：

| 轴 | 物理范围 | 固件限幅 | 说明 |
| --- | --- | --- | --- |
| X（yaw） | -128°~128° | **-120°~120°** | 支持连续旋转，但预设动作不跨越限位 |
| Y（pitch） | 0°~90° | **5°~85°** | 0° 朝下、90° 朝上，避免顶死 |

`MOVE_HEAD_PRESET` 只映射到固定关键帧，**不接受客户端角度/速度参数**，也不允许模型生成任意舵机指令。

| 预设 | 关键帧（yaw, pitch） | 用途 |
| --- | --- | --- |
| `nod` | (0,78°) → (0,26°) → (0,78°) → 中位 | 同意、收到 |
| `shake` | (-46°,62°) ↔ (46°,62°) ×2 → 中位 | 拒绝、不知道 |
| `tilt` | (-40°,64°) 保持 0.9s → 中位 | 倾听、疑惑 |
| `look_around` | (-72°,54°) → (72°,54°) → 中位 | 寻找、环顾 |
| `greet` | 抬头 0° → 仰视 82° ×2 → 中位 | 打招呼、告别 |

## 4. 语音能力边界（重要）

K151 有 1W 扬声器，但**官方 BSP 不提供离线 TTS**。因此 `SPEAK_TEXT` 在 LAN-02 中定义为：

- 传输层只传**受控文案**（≤200 字），由设备端选择播放方式；
- 首版可选方案：预置提示音 + 屏幕字幕；或服务端下发预生成的短音频片段；
- 若接入云 TTS，必须使用短期音频 URL/流，不把云密钥写入固件；
- 当前 Python 运行时只模拟时长与回执，不产生音频，也不声称“语音已跑通”。

这条边界是为了避免把“协议支持 SPEAK_TEXT”误写成“真机语音已完成”。

## 5. 传输与安全

| 项 | MVP | 生产待办 |
| --- | --- | --- |
| 传输 | 本地 REST（轮询） | WebSocket/MQTT + TLS |
| 设备身份 | 独立 Bearer token（开发用） | 配对、短期凭据、轮换 |
| 指令 | 六类白名单 | 同一白名单 + 签名 |
| 过期 | 60s，且不超过活动会话截止 | 设备时钟同步 |
| 频率 | 单活动串行命令 | 限频、去重、审计 |
| 参数 | Pydantic 严格校验 | 设备端二次校验 |

## 6. 上板验证清单（LAN-01 验收）

2026-11-19 已完成现有固件的动作、语音唤醒、表情响应实机验证（见
[STACKCHAN_HARDWARE_TEST_LOG.md](STACKCHAN_HARDWARE_TEST_LOG.md)）。以下为本仓库固件的完整验收清单：

1. 烧录 `firmware/stackchan`（`pio run -e stackchan-selftest -t upload`），确认屏幕、舵机、RGB、触摸、IMU 自检输出。
2. 跑 `Servo/BasicMovement`，记录 X/Y 实际极限，校准中位（必要时用 `HomeCalibration`）。
3. 跑 `RGB_LED`，确认 12 颗灯序号与左右分布。
4. 跑 `TouchSensor`，记录 front/middle/back 三区与实际触摸位置对应关系。
5. 播放 1kHz 提示音，确认音量档位与静音。
6. 烧录 `stackchan-k151` 环境，验证 `SET_EXPRESSION` 三档表情。
7. 验证 `MOVE_HEAD_PRESET` 五个动作，确认无顶限位、无异响。
8. 断网 60s，验证本地表情/触摸仍可用，重连后补发回执。
9. 触摸确认/拒绝，核对 `COMMAND_COMPLETED/FAILED` 的 `reason`。
10. 连续 30 分钟跑命令/回执，记录内存、温度、舵机漂移。

## 7. 与 LAN-02/LAN-03 的对应

- 协议：[docs/LAN_DEVICE_PROTOCOL.md](LAN_DEVICE_PROTOCOL.md)
- 设备运行时：`services/api/src/shiyi_api/device_runtime.py`
- 固件骨架：`firmware/stackchan/`（PlatformIO + BSP；**Linux CI 已编译，未上板**）
- 演示：`python -m shiyi_api.lan_demo`（进程内）或 `bash scripts/demo_lan.sh`（HTTP）
- 未完成项：上板实机验证、音频/TTS 方案、跌倒检测、配对与 TLS。
