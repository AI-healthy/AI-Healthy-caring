# 用户中心与健康数据中心 · V0.4 本地 MVP

## 边界

此版本用于合成数据开发及 Android 接口联调。不是生产账号服务、医学数据系统或已接通的穿戴设备。
必须使用测试用户名、独立测试密码和合成观测。仅监听本机（Android 模拟器可用 10.0.2.2）。
不公开部署；启用真实数据前需要 TLS、登录限流、密码重置与账号注销、正式隐私同意与保留/删除策略、
加密存储/备份、设备与厂商 SDK 实测。默认拒绝真实上传；受控真机测试开关和新版授权见 [WEARABLE_INTEGRATION.md](WEARABLE_INTEGRATION.md)。

## 账户

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | /api/v1/users/register | username、password、可选 display_name；201 |
| POST | /api/v1/users/login | username、password；返回 access_token、expires_at、user |
| GET | /api/v1/users/me | 当前账号 |
| PATCH | /api/v1/users/me | display_name |
| POST | /api/v1/users/logout | 撤销当前令牌；204 |

用户名 3–32 个 ASCII 字母/数字/下划线，不区分大小写；测试密码 12–128 字符。
随机盐 PBKDF2-HMAC-SHA256 600000 次，令牌随机生成且仅保存 SHA-256 摘要，24 小时过期。
不要在日志或应用源码记录密码/Token。已登录用户使用 Authorization: Bearer <access_token>，
已有活动 API 可直接使用该身份。原有 SHIYI_DEV_USERS 供自动化演示保留；usr_ 和 shiyi_ 为保留前缀。
真实机器人绑定尚未实现，注册账号可创建独立的模拟设备。旧的静态预配置仅用于原有自动化演示。

## 采集授权

GET /api/v1/health/consents
PUT /api/v1/health/consents/{source}/{metric}

请求：{"granted":true,"policy_version":"local-demo-v1"}。
按用户、数据来源和指标单独授权，默认拒绝。授权事件有本地审计记录。
撤回时设置 granted=false，事务保证后续请求停止入库；已有历史仍可供本人审阅/删除；V0.5 Harness 读取前再次校验有效授权，撤回即停止使用该类记录。
这是后端合成数据采集开关，不等于 Health Connect 系统权限。Android 仍需验证授权及撤销。

## 观测上传

POST /api/v1/health/observations，单批 1–100 条，原子写入。

```json
{
  "observations": [
    {
      "client_sample_id": "synthetic-steps-001",
      "source": "health_connect",
      "metric": "steps",
      "value": 1200,
      "interval_start": "2026-01-01T07:00:00+08:00",
      "observed_at": "2026-01-01T08:00:00+08:00",
      "is_demo": true
    }
  ]
}
```

source: demo / self_report / health_connect / vendor_sdk；
health_connect/vendor_sdk 在此版本仅表示合成数据的目标适配器，不证明真实来源。
metric: sleep_minutes、steps、energy_level、resting_heart_rate_bpm。
单位分别为分钟、步、1–5 自评分、bpm；范围仅为输入校验，不是健康诊断阈值。
步数、睡眠必须携带起止时刻（最多24小时）；精力和静息心率为点观测。
精力只允许自评或演示，不从心率推断情绪。所有时间带时区；服务器保存 UTC 和 recorded_at。
缺失记录 value=null 且提供 missing_reason（not_available/not_worn/sensor_error/not_reported），
不得把缺失数据填成 0。重复键为 user+source+metric+client_sample_id；同内容返回 duplicate，
不同内容返回 409。403 未授权；422 类型、时间或来源不合法；整批失败不写入部分记录。

## 历史查询与删除

GET /api/v1/health/observations?source=health_connect&metric=steps&limit=50&offset=0
返回 items 与 next_offset（null 表示末页）。按 observed_at、observation_id 倒序；
分页适合本地测试，若同步时继续写入可能分页移动。无跨账号查询参数。
DELETE /api/v1/health/observations/{observation_id}：删除本人观测，204；他人或不存在 404。
撤回授权不等于删除历史；删除后重新上传同一合成 ID 会重建记录（仍需授权）。
没有账号删除、批量清除、保留期自动清理、正式审计导出或生产数据恢复能力。

## 本地验证

```bash
cd services/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,mcp]'
python -m pytest -q
python -m ruff check src tests
uvicorn shiyi_api.main:app --host 127.0.0.1 --port 8000
```

进入 /docs → register → login → Authorize → consent → observations。
默认模式不读取真实穿戴数据；V0.5 Harness 可在明确开启后使用最小合成自评记录，且不外发记录至小智/LLM，
不安装 Android 或修改固件。后续 Agent Harness 应只通过经过授权的聚合查询读取最小必要数据。


## 注册账号的模拟设备

- POST /api/v1/users/me/simulated-devices {"name":"Synthetic StackChan"}：201，返回模拟设备及一次性发放的 device_token。
- GET /api/v1/users/me/simulated-devices：本人设备列表，不返回令牌。
- DELETE /api/v1/users/me/simulated-devices/{device_id}：撤销设备令牌，取消未结束命令；204。
- 可使用该 device_id 和独立令牌运行 shiyi_api.simulator，走已有设备队列流程。
- sim_、simtok_ 为此模拟协议保留前缀。此功能不是物理 K151 配对，不允许借其控制真实机器人。
