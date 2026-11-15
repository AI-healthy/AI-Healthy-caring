# XU-01 · 活动任务与反馈 API（local MVP）

关联 Issue #1。仅允许本地合成/演示数据；尚非生产鉴权、正式穿戴接入或真机通信。

## 本地启动

在 services/api 中执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
export SHIYI_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export SHIYI_DEV_USERS="$(python -c 'import os,json; print(json.dumps({"demo-user":os.environ["SHIYI_TOKEN"]}))')"
export SHIYI_DB_PATH=private_data/shiyi.sqlite3
python -m pytest -q
python -m ruff check src tests
uvicorn shiyi_api.main:app --host 127.0.0.1 --port 8000
```

不自动加载 .env。默认没有身份，受保护接口失效关闭；可在 Swagger /docs 中使用 Bearer token。
仅为开发环境预配置随机令牌；不是生产登录、JWT、配对或正式授权系统。
不要暴露公网、提交令牌或录入真实健康数据。数据库目录 private_data 已被 Git 忽略。
重启服务时保留同一数据库路径和同一身份配置即可读回合成记录。
SQLite 标准库实现用于降低初期依赖，生产迁移/SQLAlchemy 与 Alembic 留待团队确认。

## 状态机

- CREATED → RUNNING → COMPLETED
- CREATED / RUNNING → CANCELLED
- CREATED / RUNNING → EXPIRED
- 终态不允许重新启动。重复调用同一目标状态返回既有记录。
- CREATED 在创建 30 分钟后逻辑过期；RUNNING 在活动时长 + 10 分钟后过期。
  根据服务端 UTC 时间，在查询或变更该会话时落库；暂无后台定时器。
- 时长和标题由服务端活动目录决定，不接受客户端伪造。
- 创建传入 client_request_id 可按身份幂等；同 key 不同活动返回 409。

## 请求说明

共同 Header：Authorization: Bearer <dev-token>

| 方法 | 路径（前缀 /api/v1/activities） | 请求 |
| --- | --- | --- |
| POST | /sessions | {"activity_id":"stretch","client_request_id":"demo-001"} |
| GET | /sessions/{session_id} | 无 |
| POST | /sessions/{session_id}/start | 无 |
| POST | /sessions/{session_id}/complete | 无 |
| POST | /sessions/{session_id}/cancel | 无 |
| POST | /feedback | {"session_id":"...","activity_id":"stretch","completed":true,"client_event_id":"feedback-001","enjoyment":4} |

SessionResponse 包含 session_id、activity_id、client_request_id、title、duration_minutes、
status、created_at、started_at、ended_at、expires_at、is_demo=true。
时间为带时区的 UTC ISO 8601。未开始/结束字段为 null。
反馈须与会话活动和终态匹配，每个会话仅一条反馈；按用户和 client_event_id 去重。
完全相同的重试返回 duplicate=true；改写相同事件或再次提交会话反馈返回 409。
兼容旧反馈请求（省略 session_id），仍需要身份，不建议新客户端使用。

HTTP 401：身份缺失/无效；404：活动未知或会话不存在（含他人会话）；
409：非法转移/重复键冲突/反馈不匹配；422：参数验证失败；503：身份配置无效。
OpenAPI 与 /docs 由 FastAPI 直接生成。

## 验收与剩余工作

测试覆盖创建、执行、取消、过期、持久化重开、身份隔离、重试及非法转换。
此 PR 不提交 App 代码或固件、不更新原生设备协议、不声称真实可穿戴数据或机器人已接通。
XU-02 仍需与 wu/lan 确认设备契约、模拟器联调；XU-03 需要真机与正式部署验证。
