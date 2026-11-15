# ShiYi V0.7 Memory Harness

## 分层

- 短期状态：原有当前明确自评优先；授权自评最多6小时；未知不回填。无新增原始健康存储。
- 显式偏好：用户直接设置的活动偏好标签和活动屏蔽；不自动推断心理特征。
- 体验事件：以现有 activity_feedback + COMPLETED 会话为真值；仅有效 enjoyment 评分，不采纳未完成、伪造机器人回执或不带会话的旧反馈。
- 行为记忆：独立 use_behavior_memory 开关，只看近48小时用户确认完成的会话；不根据取消或拒绝推断不喜欢。默认关闭。

记忆从既有 SQLite 业务记录按需重建，不复制原始记录，不使用向量数据库或对话摘要。

## 选择与预算

先应用时间、屏蔽及本轮跳过条件，得到候选活动集合 C。反馈检索按活动分别取最近4条合法评分，近30天且在授权窗口内，再合并按时间倒序取最多 memory_budget 条（默认12，1–20）。行为检索按每候选最多4条，整体最多12条。没有跨活动语义泛化。GET /memory 可选 available_minutes 做时间过滤；不含本轮 skip，因此不是特定 run 的完整回放。

日期按 UTC 日桶计算，半衰期7天：
w_i = 2^(-age_days/7)
M(a) = sum_i(w_i * (rating_i - 3)) / (2 + sum_i(w_i))
B(a) = min(1, 0.25 * recent_completed_count)
D(a) = M(a) - B(a)

M 为偏好证据，B 是保守的重复惩罚（启用行为记忆后才使用）；不是医学推断，也不是用户厌恶标签。
默认所有记忆关闭；本地规则将 D 加入原有候选排序。模型只获得聚合 D，不获得评分事件、时间、身份或原始健康数据。
模型仍可不同意排序偏好，但不能选候选之外活动；最终用户确认。4条/活动、预算及权重为待验证的工程基线，不声称优于其他算法。

## API 及生命周期

PUT /api/v1/harness/settings（完整替换）新增 use_behavior_memory=false、memory_budget=12。
GET /api/v1/harness/memory?available_minutes=5 返回 enabled（反馈）、behavior_enabled、
budget、recalled_events、behavior_events、entries，其中每条包含 activity_id/count/score、
effective_weight/recent_completions/repetition_penalty/decision_score。返回列表含行为记忆独有条目。
POST /api/v1/harness/memory/reset 无请求体，重置当前用户的两类检索窗口，保留开关、
显式偏好、业务记录和历史运行记录，未确认方案失效。不是账号数据物理删除。
采用时间与 SQLite rowid 高水位排除旧记录，即使同一时间戳也不会重新纳入。
行为记忆开启或重置后只纳入新建且完成的会话；反馈可纳入此后新提交的有效反馈。
旧版已开启的反馈记忆沿用原 memory_since，缺省 rowid 下界0，兼容旧数据。
当前业务记录无单独删除功能；若日后增加删除/迁移，需同步维护高水位策略和外键。
快照重新读取与 revision 保证推理期间重置或设置变更后旧排序不被提交，
已确认活动不取消；已发往本机模型的请求无法撤回。

所有内容只限合成数据。本版不处理自由文本、医疗推断、真实穿戴、云推理或主动推送。
