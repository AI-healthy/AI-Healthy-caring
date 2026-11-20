# LAN 工作包状态与验收证据

> 更新：2026-11-19 · 分支 `feat/lan-stackchan-control`
> 原则：模拟/协议层已完成的部分才打勾；真机未验证的一律标注“待实机”。

## 1. 总览

| 工作包 | 状态 | 说明 |
| --- | --- | --- |
| LAN-01 SKU/SDK 与硬件能力 | **部分完成（实机基础验证）** | K151 动作、语音唤醒、表情响应已实机验证（2026-11-19）；自检固件已提交；触摸/RGB/IMU/TTS 待补测 |
| LAN-02 白名单、过期、鉴权、回执、离线重试 | 完成（模拟层） | 服务端 + 设备运行时测试通过；固件同逻辑已写但未编译/上板 |
| LAN-03 运动引导、计时、触摸完成/拒绝 | 完成（模拟层） | 5 分钟伸展加速演示，confirm/decline 两条路径均验证；真机未验收 |

### 1.1 实机记录

| 日期 | 测试项 | 结果 | 说明 |
| --- | --- | --- | --- |
| 2026-11-19 | 头颈动作 | PASS | K151 现有固件；详见 [实机记录](STACKCHAN_HARDWARE_TEST_LOG.md) |
| 2026-11-19 | 语音唤醒 | PASS | K151 现有固件；本仓库固件未实现唤醒词 |
| 2026-11-19 | 表情响应 | PASS | K151 现有固件；本仓库表情映射待上板核对 |

> “已实机”不等于本仓库 `firmware/stackchan` 已编译或烧录；该固件仍未上板。

## 2. 可核验证据

### 2.1 自动化

```bash
cd services/api
python -m pytest -q -k "device or lan"     # 协议 + 运行时
python -m shiyi_api.lan_demo               # 5 分钟伸展演示（无需 uvicorn）
```

- `services/api/tests/test_devices.py`：原有设备命令闭环（6 项）
- `services/api/tests/test_lan_protocol.py`：六类命令、非法 payload、幂等冲突、触摸拒绝/确认、
  离线 spool 补发、ACK 后重启恢复、过期不执行（21 项）
- `.github/workflows/backend-ci.yml` 已加入 `python -m shiyi_api.lan_demo`

### 2.2 文档

- [STACKCHAN_DEVICE_PROFILE.md](STACKCHAN_DEVICE_PROFILE.md)：SKU、能力矩阵、舵机限幅、
  音频边界、上板 10 步清单
- [LAN_DEVICE_PROTOCOL.md](LAN_DEVICE_PROTOCOL.md)：六类命令、状态机、幂等/过期/重试、时序
- [STACKCHAN_OFFICIAL_INTEGRATION.md](STACKCHAN_OFFICIAL_INTEGRATION.md)：保留官方固件，
  通过本地 MCP（HTTP :8788 / USB）接入的接口改造方案

### 2.3 固件

- `firmware/stackchan/`：PlatformIO 工程、白名单解析、ACK/终态、NVS 恢复、自检模式
- **已编译（CI）**：Firmware CI 在 Ubuntu 上通过 pioarduino（Arduino core 3.x）编译
  `stackchan-k151` 与 `stackchan-selftest`
- **未上板**：尚未烧录到 K151，实机仅验证了设备现有固件的基础能力

## 3. 真机剩余项（K151 已到货，基础能力已验证）

| 项 | 状态 | 验收方式 |
| --- | --- | --- |
| 头颈动作 | 已实机 PASS | 现有固件已测；本仓库预设动作待上板 |
| 表情响应 | 已实机 PASS | 现有固件已测；本仓库三档表情待核对 |
| 语音唤醒 | 已实机 PASS | 现有固件已测；本仓库固件未实现唤醒词 |
| 三区触摸 | 待补测 | `pio run -e stackchan-selftest -t upload`，串口 PASS 报告 |
| 12 路 RGB | 待补测 | 自检灯序 + 亮度 |
| 提示音/TTS | 待补测/待选型 | 自检提示音；TTS 需预置音频或云端流 |
| IMU 摇晃/跌倒 | 待补测 | 自检读取 + 阈值试验 |
| 断网重连 | 待补测 | 拔网 60s，检查本地交互与重连补发 |
| 触摸完成/拒绝 | 待补测 | 运行引导，点按/长按，核对 `reason` |
| 30 分钟稳定性 | 待补测 | 连续命令/回执，记录内存与温度 |

## 4. 已知设计边界

- 机器人命令完成 ≠ 用户活动完成，活动仍由 App 用户确认；
- 不受理任意舵机角度/速度，只接受固定 `MOVE_HEAD_PRESET`；
- `SPEAK_TEXT` 只显示字幕并播提示音，不声称语音已接入；
- 固件当前 `setInsecure()`，生产必须改 TLS + 配对。

## 5. 提交记录

| commit | 内容 |
| --- | --- |
| `cd64e3e` | 六类白名单协议、设备运行时、27 项测试、LAN 文档 |
| `70c84a7` | K151 固件骨架、NVS 恢复、进程内 LAN demo + CI |
| `437cf02` | LAN-01 自检固件、触摸拒绝演示路径 |
| `4dec7c2` | LAN 验收状态与真机阻塞记录 |
| `a529938` | K151 实机记录（动作 / 语音唤醒 / 表情） |
| `d28bc2d` | Firmware CI（Linux） |
| `6986134` | 修复 Ruff 导入/异常检查 |
| `ddabc4a` | 切换到 Arduino core 3（pioarduino），固件 CI 编译通过 |

> 分支已推送到 GitHub：`origin/feat/lan-stackchan-control`（2026-11-19），PR #9。
> 后续以 PR 形式请求 review；接口变更需与 xu 同步。
>
> 本机 Windows 的 SCons/GCC 响应文件兼容问题只影响本地编译；Firmware CI 的 Ubuntu
> 环境已成功编译两个 env，证明固件源码可构建。上板仍需真机验证。
