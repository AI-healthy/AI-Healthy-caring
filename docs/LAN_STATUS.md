# LAN 工作包状态与验收证据

> 更新：2026-11-19 · 分支 `feat/lan-stackchan-control`
> 原则：模拟/协议层已完成的部分才打勾；真机未验证的一律标注“待实机”。

## 1. 总览

| 工作包 | 状态 | 说明 |
| --- | --- | --- |
| LAN-01 SKU/SDK 与硬件能力 | 部分完成 | K151/CoreS3/BSP 已确认，能力矩阵与自检固件已提交；**屏幕/舵机/音频/触摸未实机实测** |
| LAN-02 白名单、过期、鉴权、回执、离线重试 | 完成（模拟层） | 服务端 + 设备运行时测试通过；固件同逻辑已写但未编译/上板 |
| LAN-03 运动引导、计时、触摸完成/拒绝 | 完成（模拟层） | 5 分钟伸展加速演示，confirm/decline 两条路径均验证；真机未验收 |

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

### 2.3 固件

- `firmware/stackchan/`：PlatformIO 工程、白名单解析、ACK/终态、NVS 恢复、自检模式
- **未编译、未上板**：当前环境下载 PlatformIO 平台包被沙箱拦截，README 已如实标注

## 3. 真机剩余项（阻塞原因：无 K151 硬件）

| 项 | 验收方式 |
| --- | --- |
| 屏幕/触摸/IMU | `pio run -e stackchan-selftest -t upload`，串口 PASS 报告 |
| 舵机中位/极限/异响 | 自检 + `HomeCalibration`，记录 X/Y 实测范围 |
| 音频 | 自检提示音；TTS 方案仍需选型（预置音频/云端流） |
| 断网重连 | 拔网 60s，检查本地交互与重连补发 |
| 触摸完成/拒绝 | 运行引导，点按/长按，核对 `reason` |
| 30 分钟稳定性 | 连续命令/回执，记录内存与温度 |

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

> 分支尚未推送到 GitHub：本机沙箱无法取得 GitHub 凭据（`401`/GCM 无凭据）。
> 推送后应以 PR 形式请求 review；接口变更需与 xu 同步。
