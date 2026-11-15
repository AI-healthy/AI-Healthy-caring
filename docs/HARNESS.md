# ShiYi Agent Harness V0.6 · 本地模型适配与受约束决策

这是有界、结构化智能体运行框架，允许可选本机模型参与候选排序，不是通用聊天系统。所有输入为合成测试数据。
模块：harness/contracts.py、engine.py、repository.py、api.py。xu 维护运行时与工具边界，
fu 可在可信本地代码中实现 Ranker.rank(context, candidates)；默认规则，不要求 API key。
当前不执行外部云 LLM/RAG、后台常驻调度或真实机器人指令；MCP 仍保留无身份的只读演示工具。

## 决策循环

触发与设置 → 安全门（用户主动声明忙/不适、主动陪伴开关、勿扰和冷却） →
最小授权感知 → 反馈记忆 → 候选目录过滤 → 策略排序 → 验证输出 →
等待用户确认 → 原子创建 CREATED 活动会话 → 现有 Activity API 执行及反馈。

- 仅当前请求明确的精力自评，或开启 use_observations 后本人已授权、6 小时内最新的
  self_report/energy_level 合成记录。缺失即未知，不回填、不把心率解释为心理状态；
  睡眠/步数暂不进入排序，避免没有依据的健康阈值。
- 偏好标签与手动屏蔽活动由用户设置；反馈记忆默认关闭。
  只聚合开启之后、近30天最近100条已完成活动的有效 enjoyment 评分，按活动计算
  score = sum(rating-3)/(count+2)。关闭/重新开启会重置记忆使用窗口，不删除业务反馈。
  评分仅用于排序，不做心理画像或医疗判断。
- Ranker 只能返回候选 ID（最多3个）；未知/重复/空/异常输出回退本地规则。
  标题、时长、解释均来自服务端，不执行任意工具。当前策略必须快速、无副作用、仅本地运行；
  服务端策略依赖 harness.api.get_ranker 可在本地启动配置/测试中替换，前端不能提交执行代码。
  V0.6 将推理移到 SQLite 事务外，并在提交前重新获取设置、授权、记忆、候选和主动触发条件；上下文变化时丢弃旧提议，按最新状态使用规则重算。
- 10 分钟内可确认；同一 run 同一选择重试返回同一会话，不同选择 409。
  用户确认只创建 CREATED 会话，不启动、不向设备发送指令、不自动记录用户完成。
  设置修改、撤回采集授权或删除健康记录会使尚未确认的计划失效；不追溯取消已确认活动。
- scheduled_check 仅生成主动陪伴建议（非通知送达）：默认关闭；时区默认 Asia/Shanghai；
  默认勿扰 22:00–08:00、至少4小时冷却、滚动24小时最多2次建议。
  等值勿扰起止视为全天勿扰；有未过期的活动或待确认方案时不生成主动建议；主动请求不受勿扰限制。计数按已生成建议而非通知送达；
  状态返回 NO_ACTION 时不要发送通知。没有后台 worker，需要客户端主动调用评估。
- 持久化运行记录：状态、候选、有限 trace、时间、请求去重摘要；不保存原始自评或完整上下文。
  trace 是可检查的阶段结果而非模型思维链。仅合成数据，摘要不作为隐私保证。
  历史运行记录尚无保留清理/账号删除功能。

## API

均使用 Authorization: Bearer <access-token>，支持现有本地登录及开发身份。

| Method | /api/v1/harness | 说明 |
| --- | --- | --- |
| GET / PUT | /settings | 查询/完整替换设置 |
| GET | /memory | 查看开启状态及聚合分数 |
| POST | /runs | 生成有界方案，client_request_id 幂等 |
| GET | /runs/{run_id} | 查询状态及可解释 trace |
| POST | /runs/{run_id}/confirm | {"activity_id":"stretch"} |
| POST | /runs/{run_id}/dismiss | 拒绝，不创建任务 |

示例设置（PUT /settings）：
```json
{"use_observations":true,"use_feedback_memory":true,"preference_tags":["music"],
 "blocked_activity_ids":[],"proactive_enabled":false,"timezone":"Asia/Shanghai",
 "quiet_start":"22:00:00","quiet_end":"08:00:00"}
```
示例请求（POST /runs）：
```json
{"client_request_id":"demo-run-1","available_minutes":8,"trigger":"user_request",
 "availability":"ready","energy_level":2,"skip_activity_ids":[]}
```
不提供 energy_level 时才尝试读取授权状态。NO_ACTION 时 options=[]，reason 为可机器处理的原因；
AWAITING_CONFIRMATION 才能调用 confirm，返回 run 与 session。之后沿用现有
/activities/sessions/{session_id}/start、/complete、/cancel 及 /feedback。
所有状态和输出均只限本地测试，不代表真的通知或使用了真实健康数据。

## 里程碑与验证

bash scripts/demo_backend.sh 从真实本地 HTTP 走完整登录、Harness 规划、确认、模拟设备、活动反馈及记忆查询。
单元/HTTP 测试检查授权、缺失/陈旧记录、自评优先、记忆开关、排序回退、确认幂等、
用户隔离、过期、撤销导致失效、主动陪伴勿扰和冷却。后续需与 fu 评审决策契约、
与 wu 联调用户确认，与 lan 验证实际设备。拟议后续：经审核的 RAG 工具、异步模型适配器、
独立用户授权的设备端工具、主动提醒 worker/投递幂等、保留删除策略及对照实验。

本机 LLM、工具路由、预算与威胁边界详见 [MODEL_ADAPTER.md](MODEL_ADAPTER.md)。
