# LAN-02 · 设备协议与网络传输（0.2-draft）

本文冻结 `lan` 负责的设备白名单协议。传输为本地 REST 轮询（模拟器/真机适配器可替换为
WebSocket 或 MQTT，语义不变）。所有消息 `is_demo=true`，只用于合成数据演示。

> 设备只执行**六类白名单命令**，不接受任意角度、任意文本或 shell 指令。
> 机器人命令完成 ≠ 用户活动完成；活动完成仍必须由用户在 App 确认。

## 1. 端点与身份

| 方向 | 方法/路径 | 身份 |
| --- | --- | --- |
| 用户端创建命令 | `POST /api/v1/devices/commands` | 用户 Bearer |
| 用户端查询命令 | `GET /api/v1/devices/commands/{command_id}` | 用户 Bearer |
| 设备拉取待处理 | `GET /api/v1/devices/{device_id}/pending` | 设备 Bearer |
| 设备上报回执 | `POST /api/v1/devices/{device_id}/events` | 设备 Bearer |

设备令牌来自 `SHIYI_DEV_DEVICES`（静态）或注册账号创建的 `sim_` 设备；生产必须增加配对、
TLS、短期凭据与限频，本文件不把它们标为已完成。

## 2. 命令

请求公共字段：

```json
{
  "session_id": "活动会话 UUID",
  "device_id": "sim",
  "client_request_id": "调用方幂等键",
  "command_type": "PLAY_GUIDE",
  "payload": {}
}
```

`preset` 是 0.1-draft 的兼容字段，仅用于 `SET_EXPRESSION`；新调用方使用 `payload`。

| `command_type` | `payload` | 设备行为 | 能力依赖 |
| --- | --- | --- | --- |
| `SET_EXPRESSION` | `{"preset":"happy\|neutral\|sleepy"}` | 切换表情 | 屏幕 |
| `SPEAK_TEXT` | `{"text":"≤200字","emotion":"预设"}` | 字幕/提示音；音频方案待定 | 屏幕 + 扬声器 |
| `PLAY_GUIDE` | `{"guide_id":"...","title":"...","duration_seconds":30-900,"steps":["..."]}` | 播放引导 + 计时；触摸可提前结束 | 屏幕 + 触摸 |
| `SHOW_TIMER` | `{"duration_seconds":10-3600,"label":"..."}` | 显示倒计时 | 屏幕 |
| `MOVE_HEAD_PRESET` | `{"preset":"nod\|shake\|tilt\|look_around\|greet"}` | 固定关键帧动作 | 双舵机 |
| `CANCEL_TASK` | `{"reason":"user_cancel\|session_cancelled\|timeout"}` | 停止当前动作并清屏 | 全部 |

服务端在入队前用 Pydantic 严格校验（`extra=forbid`）；设备端执行前用同一套模型再校验一次。
未知类型、越界时长、超长文本、额外字段一律 422，不进入队列。

命令返回示例：

```json
{
  "schema_version": "0.1-draft",
  "command_id": "uuid",
  "correlation_id": "活动会话 UUID",
  "device_id": "sim",
  "type": "PLAY_GUIDE",
  "payload": {"guide_id":"stretch-5min","title":"5 分钟肩颈放松","duration_seconds":300,"steps":["坐直","抬肩"]},
  "expires_at": "2026-11-18T13:00:00+00:00",
  "is_demo": true,
  "status": "QUEUED",
  "created_at": "2026-11-18T12:59:00+00:00"
}
```

## 3. 状态与回执

```
QUEUED ──ACK──► ACKNOWLEDGED ──COMPLETED──► COMPLETED
   │                  │
   │                  └──FAILED────────────► FAILED
   ├──活动结束/会话非 RUNNING──► CANCELLED
   └──超过 expires_at──────────► EXPIRED
```

设备事件：

```json
{
  "schema_version": "0.1-draft",
  "event_id": "cmd:<id>:completed:touch_confirmed",
  "device_id": "sim",
  "type": "COMMAND_COMPLETED",
  "command_id": "...",
  "occurred_at": "2026-11-18T13:00:05+00:00",
  "is_demo": true,
  "reason": "touch_confirmed",
  "elapsed_seconds": 90
}
```

| `type` | `reason` 约定 | 含义 |
| --- | --- | --- |
| `COMMAND_ACKNOWLEDGED` | `accepted` | 设备已接收，即将执行 |
| `COMMAND_COMPLETED` | `timer_elapsed` / `touch_confirmed` | 正常结束 / 用户触摸提前结束 |
| `COMMAND_FAILED` | `user_declined` / `invalid_payload` / `unsupported_command` | 用户拒绝 / 设备二次校验失败 |

`reason`、`elapsed_seconds` 仅用于诊断与演示，不改变活动会话状态。

## 4. 幂等、过期与重试

- **命令幂等**：`client_request_id` 在用户维度唯一；相同键 + 相同命令返回原命令，
  相同键 + 不同 payload/type 返回 `409`。
- **事件幂等**：`event_id` 在设备维度唯一；完全相同的重发返回 `duplicate=true`，
  同 ID 不同内容返回 `409`。
- **过期**：命令 60 秒有效，且不超过活动会话截止；过期后 `pending` 不再返回，查询为 `EXPIRED`。
- **ACK 先行**：设备未收到 ACK 成功前不执行动作；ACK 可安全重发。
- **离线重试**：终态事件发送失败时写入本地 spool（JSON），下次启动/轮询先回放；
  回放使用同一 `event_id`，由服务端去重。
- **重启恢复**：设备收到 `ACKNOWLEDGED` 后不重复执行，直接补发终态；真实固件还必须持久化
  `command_id` 并做物理动作幂等（LAN-02 剩余实机项）。

## 5. 典型时序（5 分钟伸展，演示加速）

```
App/用户  ──POST /commands(PLAY_GUIDE)──►  API
设备      ──GET /pending────────────────►  API   → QUEUED
设备      ──POST /events(ACK)───────────►  API   → ACKNOWLEDGED
设备      本地播放引导/计时（演示可用 speed 加速）
用户触摸确认 ──► 设备 POST /events(COMMAND_COMPLETED, reason=touch_confirmed)
App/用户  ──POST /activities/sessions/{id}/complete──► API → COMPLETED
```

小智/云语音不直接调用设备；它只能通过同一白名单命令间接影响设备。

## 6. 测试覆盖（LAN-02 验收）

`services/api/tests/test_lan_protocol.py`：

- 六类命令的入队/执行/完成；
- 兼容旧 `preset` 字段；
- 非法 payload/类型/越界/额外字段 → 422；
- 同一 `client_request_id` 改 payload → 409；
- 触摸拒绝 → `FAILED(user_declined)`；触摸确认 → `COMPLETED(touch_confirmed)`；
- 终态事件离线 spool → 回放补发；
- ACK 后重启恢复；
- 过期命令不执行。

## 7. 未完成（不得写成已完成）

- K151 固件骨架已提交（`firmware/stackchan/`），但**尚未编译、未上板**；
- TLS、设备配对、短期凭据、限频；
- WebSocket/MQTT 适配器；
- 离线队列的磁盘持久化与容量上限（Python 运行时已有 spool，固件待做）；
- 语音 TTS/音频流方案（见 [STACKCHAN_DEVICE_PROFILE.md](STACKCHAN_DEVICE_PROFILE.md) 第 4 节）。
