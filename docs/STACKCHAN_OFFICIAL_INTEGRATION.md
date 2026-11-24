# LAN-02 · 与官方 StackChan 固件对接（推荐路线）

## 1. 现状与结论

官方 StackChan 固件基于 XiaoZhi（开源），已经具备：唤醒词 → 对话模式、顶部触摸可爱表情、
摇晃头晕表情、AVATAR/CAMERA/MOTION/DANCE；手机通过 Wi-Fi 或 USB 连接。

**不建议为了接自己的软件而刷掉官方固件**——会丢失唤醒词、摄像头、官方 App 能力。
推荐保留官方固件，通过社区补丁暴露的**本地 MCP**接入：

| 路线 | 保留官方能力 | 本地事件上传 | 工作量 | 结论 |
| --- | --- | --- | --- | --- |
| A. 官方固件 + 小智云 MCP | ✅ | ❌ 依赖云端/账号 | 低 | 只能做“机器人主动调工具”，不适合本地闭环 |
| **B. 社区固件 + 本地 MCP（HTTP :8788 / USB）** | ✅ | ✅ 可轮询/订阅 | 中（刷一次） | **推荐** |
| C. 本仓库自研 BSP 固件 | ❌ 丢失唤醒/摄像头/AVATAR | ✅ 完全可控 | 高 | 后续产品化再考虑 |

社区参考实现：

- [heavenchenggong/stackchan-paimon](https://github.com/heavenchenggong/stackchan-paimon)：在 XiaoZhi 固件上加
  `GET /tools`、`POST /mcp`、USB 串口 JSON-RPC，并保留 19+ 个板卡工具。
- [kisaragi-mochi/stackchan-mcp](https://github.com/kisaragi-mochi/stackchan-mcp)：WebSocket MCP 网关，
  工具名更语义化（`set_avatar`、`move_head`、`get_touch_state`、`stackchan/event` 通知）。

## 2. 目标拓扑

```
时宜 App ──HTTP──> 时宜后端（设备命令队列 / 事件存储）
                        ▲                │ pending
                        │ sensor events  │ commands
                 ┌──────┴────────────────▼──────┐
                 │  StackChan Gateway（本仓库）  │
                 │  REST ⇄ MCP 翻译 / 事件轮询   │
                 └──────┬───────────────┬───────┘
                        │ HTTP :8788/mcp │ USB serial JSON
                 ┌──────▼───────────────▼───────┐
                 │  官方 StackChan 固件 + 本地 MCP │
                 └───────────────────────────────┘
```

- **Wi-Fi**：设备与后端同网段，Gateway 访问 `http://<device-ip>:8788`。
- **USB**：设备通过 USB-C 数据口接电脑/手机，Gateway 用串口 JSON-RPC；不依赖网段。
- 官方 App 仍可继续使用；两条控制通道互不破坏（同一时刻建议只由一方下发动作）。

## 3. 接口修改（固件侧，刷一次）

采用 paimon 的 `feature/integration`（或 stackchan-mcp 固件），不要用官方未改版固件——它没有局域网 MCP。

| 接口 | 方法 | 说明 |
| --- | --- | --- |
| `/tools` | GET | 列出设备工具（可用于自检和版本探测） |
| `/mcp` | POST | JSON-RPC 2.0：`tools/call`，也支持简写 `{"tool":"...","arguments":{}}` |
| `/healthz` | GET | 存活/是否启用 MCP |
| USB | 串口 | 一行 JSON 请求，设备回 `__MCP_RESULT__{...}` |

请求示例：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"self.head.nod","arguments":{}}}
```

限制：局域网内无 TLS；生产需放进可信 Wi-Fi/VPN，并给 `/mcp` 增加 token（社区补丁可加，默认无鉴权）。

## 4. 接口修改（时宜后端）

新增 [stackchan_bridge.py](../services/api/src/shiyi_api/stackchan_bridge.py)：

- `HttpMcpTransport`：`POST /mcp`、`GET /tools`，可选 Bearer token；
- `UsbMcpTransport`：串口请求/`__MCP_RESULT__` 解析，pyserial 可选；
- `OfficialStackChan`：把时宜六类命令翻译成白名单 MCP 工具调用。

| 时宜命令 | 默认 MCP 工具 | 说明 |
| --- | --- | --- |
| `SET_EXPRESSION` | `self.face.expression` | happy / neutral / sleepy |
| `SPEAK_TEXT` | `self.audio_speaker.play_text` | 由设备或网关 TTS 发声 |
| `PLAY_GUIDE` | `self.face.expression(thinking)` + `play_text(title)` | 计时仍由网关/后端负责 |
| `SHOW_TIMER` | `self.face.expression(thinking)` + `play_text(label)` | 同上 |
| `MOVE_HEAD_PRESET` | `self.head.nod/shake/tilt/move` | 固定预设，不接受任意角度 |
| `CANCEL_TASK` | `self.head.center` + `self.face.expression(idle)` | 停止当前动作 |

工具名会随社区固件版本变化，因此映射支持 **profile 覆盖**：

```python
from shiyi_api.stackchan_bridge import HttpMcpTransport, OfficialStackChan, McpCall

bridge = OfficialStackChan(
    HttpMcpTransport("http://192.168.1.50:8788"),
    profile={"SET_EXPRESSION": [McpCall("my.face.set", {"name": "{preset}"})]},
)
bridge.execute(command)
```

示例见 `packages/contracts/stackchan-mcp-profile.example.json`。

> 工具差异：官方 `hal_mcp.cpp` 只注册 `self.robot.get_head_angles`、`set_head_angles`、
> `set_led_color`、`create_reminder`、`get_reminders`、`stop_reminder`；`self.face.*`、`self.head.nod`
> 等来自社区补丁。接真机前必须 `GET /tools` 核对，按实际工具名改 profile。

## 5. 信息上传（触摸/摇晃/唤醒）

MCP 的 `tools/call` 是请求/响应，不是事件流。两种做法：

| 方式 | 适用 | 说明 |
| --- | --- | --- |
| 轮询 `get_touch_state` / `get_device_info` | HTTP 固件 | Gateway 每秒读一次，检测按下/释放沿；摇晃/唤醒需固件状态字段 |
| 订阅 `stackchan/event` | WebSocket MCP 固件 | stackchan-mcp 网关会推送 touch/wake 通知，最完整 |
| 固件自定义上报 | 长期 | 固件内 `POST /api/v1/devices/{id}/sensor-events`，最可靠但需改固件 |

**建议的时宜接口（下一步实现）**：

```
POST /api/v1/devices/{device_id}/sensor-events   (设备 Bearer)
{
  "schema_version":"0.1-draft",
  "event_id":"evt-...",
  "device_id":"stackchan-001",
  "type":"TOUCH|SHAKE|WAKE|FACE",
  "occurred_at":"2026-11-20T11:00:00Z",
  "payload":{"zone":"top","expression":"happy"},
  "is_demo":true
}
```

后端按 `event_id` 幂等入库，App 可查询；事件只作交互记录，不改变活动完成状态。

## 6. 落地步骤

1. 备份原机固件（16MB），刷社区本地 MCP 固件；确认串口日志出现 `HTTP MCP server on port 8788`。
2. 配好 Wi-Fi（设备与后端同网段），记录 IP；或在电脑上确认 USB 串口设备名。
3. 用 `GET /tools` 核对工具名，填/调整 profile。
4. 用 `OfficialStackChan` 依次验证表情、点头、摇头、说话（先短文本）。
5. 接入后端命令队列：Gateway 认领 `pending` → `tools/call` → ACK/COMPLETED。
6. 事件上传：先轮询触摸；需要摇晃/唤醒实时性时改 WebSocket 或固件上报。
7. 真机验收：动作限位、断网重连、连续命令 30 分钟、官方 App 与自研软件不并发冲突。

## 7. 安全边界

- 局域网 MCP 默认无鉴权：不要暴露公网；生产加 token/mTLS。
- 只允许固定工具与参数；不把模型输出直接当舵机角度或 shell。
- 固件/配对密钥不进仓库；不采集摄像头/麦克风原始数据。
- 机器人回执 ≠ 用户活动完成，活动仍由 App 用户确认。

## 8. 与当前自研固件的关系

`firmware/stackchan/` 继续保留为**产品化备选**：完全可控、可做 NVS 幂等与离线队列，
但当前不实现唤醒词/CAMERA/AVATAR。比赛演示优先走本地 MCP 路线，避免丢失官方卖点。

## 9. 官方 App 到底怎么连（源码核对）

官方 App（Flutter）不是直接调 MCP：

- 手机端 `LocalAreaNetworkService` 起一个 **WebSocket `/ws` 服务**；固件作为客户端连上来。
- 端点通过远程 XiaoZhi 通道的 `AppLanAddress` 消息告知固件，未连接时每 3 秒重发。
- 局域网帧头固定 20 字节：`SC` + version + type + flags + session + sequence + length。
- 表情/动作/RGB 是二进制帧内的 **`ExpressionData` JSON**：
  `leftEye/rightEye/mouth` 各含 `x/y/rotation/weight/size`，因此官方 App 可以画任意新表情。
- BLE 通道也有一套 `bleAvatar`/`bleMotion` 数据。

含义：**官方 App 的“更多表情”走 AVATAR 协议，不走 MCP**。如果我们的后端只接 MCP，
能控制头/灯/提醒/内置表情，但要做全新的眼睛/嘴形，需要下面三条之一：

1. 社区 MCP 固件提供 `self.face.overlay`（心形、害羞、汗、头晕等装饰）；
2. 给社区固件加一个 MCP 工具，接收 `ExpressionData` JSON 并应用（推荐，改动小）；
3. 后端完整模拟官方 App 的 LAN WebSocket + 端点通告（最复杂，且要拿远程通道）。

## 10. Gateway 运行方式

```bash
export SHIYI_API_URL=http://127.0.0.1:8000
export SHIYI_SIM_DEVICE_ID=stackchan-001
export SHIYI_SIM_DEVICE_TOKEN=<设备 token>
export SHIYI_STACKCHAN_MCP_URL=http://192.168.1.50:8788
# 可选：export SHIYI_STACKCHAN_MCP_TOKEN=...
python -m shiyi_api.stackchan_gateway
```

流程：轮询后端 `pending` → 发 ACK → `OfficialStackChan` 调 MCP → 按动作时长等待 →
发 `COMMAND_COMPLETED`。它不处理触摸（HTTP MCP 没有事件流），触摸/摇晃上传需第 5 节的
WebSocket 或轮询方案。

## 11. 自定义表情的接口预留

- 内置情绪（官方 `Emotion`）：`Neutral / Happy / Angry / Sad / Doubt / Sleepy`；
- 装饰（decorators）：`angry / dizzy / heart / shy / sweat`，社区固件可映射为
  `self.face.overlay`；
- 当前 MCP 适配层已有 `OfficialStackChan.show_overlay(name)`，可直接调用；
- **已实现** `SET_FACE` 命令：`{"expression":"happy","overlay":"heart","duration_ms":3000}`；
  适配层依次调用 `self.face.expression` 与 `self.face.overlay`，未知 overlay 由固件返回错误；
- 若要画全新五官（而非装饰叠加），需要固件侧新增 `self.face.set_expression(ExpressionData JSON)` 工具。
