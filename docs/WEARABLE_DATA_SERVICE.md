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

## Android 适配器

EmbeddedBandReader 是统一 WearableReader 入口，保留已真机验证的 Honor Band 4 原始 HuaweiActivitySample 适配；新增小米手环 4/5/6 的 HuamiBandReader，依据固定上游 FetchActivityOperation 每分钟写入 MiBandActivitySample 的行为读取原始 DAO，不使用图表补点。心率过滤无效值，步数为分钟区间，睡眠只使用显式深/浅睡眠分类；不推断缺失或延续睡眠状态。后者尚需逐型号真机验证。未实现的设备仍仅发现/连接，不转换健康记录。

每个嵌入式设备在本地设备偏好中持久化随机 device_scope；同一条历史样本保留既有 id，升级后可通过重传补齐标识。不同安装生成不同 stream，不跨安装合并。旧 Health Connect 适配器仍无可信的硬件级标识，不进入 scoped 汇总。
