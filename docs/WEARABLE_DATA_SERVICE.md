# 统一穿戴数据接口（后端 v1）

这一层仅提供数据与健康上下文，不修改产品前端。

- POST /api/v1/health/observations：原有批量接口新增可选 device_scope（32 位小写十六进制随机标识）。由客户端为每台设备保存独立随机 UUID，不上传 MAC。旧客户端继续可用，未标识数据仍可查询原始历史，但不参与设备级汇总。相同内容、相同 client_sample_id 的旧记录可在重传时补充 scope；已有 scope 不可改写。
- GET /api/v1/health/streams：列出当前用户仍拥有真实数据授权的 source、data_origin、device_scope 与 metrics。
- GET /api/v1/health/summary?source=gadgetbridge&data_origin=org.aihealthy.shiyi.embedded&device_scope=<scope>&timezone=Asia/Shanghai&day=2026-11-24 ：按单一设备数据流查询日指标。day 可省略（用户时区今日）。授权撤回后对应指标立即从计算中排除，原始历史仍可由用户审核和删除。
- 步数：完整日内区间去重，重叠冲突返回 null 和 issues；跨日区间不插值。
- 睡眠：昨 18:00 至今 12:00（或当前时间）的完整时段求并集。仅提供部分睡眠时长且存在重叠/跨界歧义时返回 null，不推断睡眠阶段。
- 心率：当天最后一次有效观测及其时间；静息心率单独返回。不将普通心率当作静息心率或实时压力。
- 缺失指标为 null，真实 0 与缺失不同。sample_counts 为查询窗口内已授权记录数，非全天覆盖率。
- 真实采集开关 SHIYI_ENABLE_REAL_HEALTH=1、注册账号、逐来源逐指标授权均为必需条件。未分配设备 scope 的 Health Connect 记录不会被错误聚合为单设备。
- health_summary.summarize(db, ...) 可由后续明确授权的 Harness 上下文工具在同一事务中调用。此阶段不改变原有推荐策略，不把原始生理数据发给模型，也不输出压力诊断。

联调先调用既有授权及上传接口，再查询 streams 和 summary。前端/机器人使用各自经授权的后端调用链，不应共享用户访问令牌。
