# 跨端协议

演示 API 见 `services/api` 中的 /docs 与 /openapi.json。

- GET /api/v1/health
- GET /api/v1/seasons/current（固定节气示例）
- POST /api/v1/recommendations（规则演示）
- POST /api/v1/activities/feedback（进程内幂等）

设备消息示例仅是草案，**未验证实机通信**。正式版本必须增加设备身份校验、配对、授权、消息过期处理和参数白名单。当前演示服务不可直接暴露公网。
