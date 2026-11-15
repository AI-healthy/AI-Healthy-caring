# 跨端协议

演示 API 见 `services/api` 中的 /docs 与 /openapi.json。

- GET /api/v1/health
- GET /api/v1/seasons/current（固定节气示例）
- POST /api/v1/recommendations（规则演示）
- POST /api/v1/activities/feedback（SQLite 持久化、按身份幂等）

设备消息示例仅是草案，**未验证实机通信**。正式版本必须增加设备身份校验、配对、授权、消息过期处理和参数白名单。当前演示服务不可直接暴露公网。


## 活动会话接口（本地 MVP）

- POST /api/v1/activities/sessions
- GET /api/v1/activities/sessions/{session_id}
- POST /api/v1/activities/sessions/{session_id}/start
- POST /api/v1/activities/sessions/{session_id}/complete
- POST /api/v1/activities/sessions/{session_id}/cancel
- POST /api/v1/activities/feedback

上述接口均要求 Authorization: Bearer <dev-token>，身份由服务端配置决定。
推荐、节气及健康检查保持原有演示契约。新活动反馈建议包含 session_id；
旧客户端可暂时省略，但不属于活动状态闭环。前端不要将开发令牌写入源码或安装包。

详细字段、错误约定及本地联调见 [活动 API 说明](../../docs/ACTIVITY_API.md)；
以运行服务的 OpenAPI 为准。设备回执契约仍待 lan 联调确认。


## 本地模拟设备命令（0.1-draft）

REST: POST /api/v1/devices/commands; GET /api/v1/devices/commands/{command_id}
使用开发用户身份。GET /api/v1/devices/{device_id}/pending 与 POST
/api/v1/devices/{device_id}/events 使用独立设备令牌。当前只允许 SET_EXPRESSION
三个预设；命令必须绑定运行中的活动会话，60 秒内有效（不超过会话截止）。
ACK 与完成/失败事件按事件 ID 去重。活动完成由用户确认，不能由机器人表达回执代替。
所有消息 is_demo=true。这不是 M5Stack 原生协议，也不是生产设备绑定。
详见 [XU-02 联调指南](../../docs/INTEGRATION.md) 和 OpenAPI。
