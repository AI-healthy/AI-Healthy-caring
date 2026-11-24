# Health State Engine v1

## 职责

数据服务提供授权后的设备级观测；状态引擎从同一设备的时间序列计算可解释的日特征、稳健个人基线、趋势和持续变化事件。Harness 后续消费结构化状态，而非任意原始传感器值。此版本不触发通知、不改动 Harness 推荐、不调用 LLM，不修改前端。

## API

GET /api/v1/health/state?source=gadgetbridge&data_origin=org.aihealthy.shiyi.embedded&device_scope=<32位标识>&timezone=Asia/Shanghai

与 streams/summary 使用相同账户、设备范围与实时授权。需要真实健康开关及注册用户。最多读取 100000 条观测；只计算最近 17 个完整本地日，前 14 日为基线、最近 3 日为检测窗口，另读取前一晚睡眠边界。请求时重新计算；撤回授权后不继续使用该指标。无跨设备拼接，无状态持久化。当前日排除，避免拿未结束的日指标比较。

## 特征与规则

- recorded_sleep_minutes: 昨日 18:00 至当日 12:00 的记录睡眠区间并集；记录不证明完整佩戴，事件仅称记录睡眠减少，证据 limited。
- recorded_steps: 完整日内区间和，冲突/跨界或记录覆盖不足 12 小时的日不参与基线与事件。覆盖表示记录区间，不等于实际佩戴或全天采样。
- resting_hr_bpm: 设备明确提供静息心率的日中位数，不从普通 HR 直接推断。
- low_step_hr_bpm: 本地 06:00–10:00 内，前 10 分钟被连续零步数区间覆盖且无冲突正步数记录的 HR 中位数；至少 5 个不同时间点。仅低步数背景代理，不等同静息心率、HRV 或心理压力。
- 每项特征独立要求 >=7 个合格历史日与连续 3 个合格近期日。中心为 median，尺度 max(1.4826*MAD, floor)，floor 分别为 30 min、500 步、3 bpm、3 bpm。近期 z 为三个日偏离的中位数。连续 3 日都低于 -2 或高于 +2（按特征方向）才产生对应事件。趋势为合格近期日两两斜率的中位数。缺失不填零；无足够证据不产生事件。
- adequate_for_rule 仅表示满足当前工程规则的数据条件，不代表临床可信度或校准概率。阈值均为待真实数据和对照标注验证的 v1 工程参数。
- 压力固定返回 insufficient_evidence；目前无 RR/HRV 和与时序对齐的自评标签，禁止输出虚假的心理压力分值。未来增加独立授权自评、按人划分验证集、基线/活动控制消融、置信度校准，之后才接入 Harness 决策。

## 验收

纯函数测试覆盖冷启动、历史极端值、持续变化、基线隔离、设备隔离、缺日、活动覆盖、低步数心率和运动混淆。HTTP 测试覆盖权限、设备归属、撤回授权和功能开关。合成测试仅验证算法机制，不证明对真实压力的预测能力。


## V2 多域状态融合与压力标签

state API 新增 fusion：睡眠、活动、心率三个独立域。显式静息心率可评估时优先于低步数心率代理；两个心率事件不算两个独立域。输出 insufficient/no_sustained_pattern/single_domain_change/multi_domain_change、支持事件与已评估域。多域共同变化是描述性证据，不等同压力概率。

压力研究接口（用户自己的数据，独立授权）：
- GET/PUT /api/v1/health/pressure/consent，policy_version=pressure-checkin-v1。
- POST /api/v1/health/pressure/checkins：client_checkin_id、source、data_origin、device_scope、perceived_stress（用户自评 0–10，非临床量表）、context（resting/studying/working/exercise/other/unknown）、observed_at（过去24小时内）。重复请求幂等，不允许更改同 ID。
- GET /api/v1/health/pressure/checkins：用户审核自身历史；DELETE /api/v1/health/pressure/checkins/{id} 删除。
- GET /api/v1/health/pressure/checkins/{id}/features：按当前授权、同设备、标签时间前30分钟匹配有效心率、低步数背景心率、步数及覆盖度。低步数判断额外读取前10分钟。只做事件时间的回顾性配对，允许手环历史补传，不宣称实时推理时可用。至少5个有效心率和5个低步数心率点、25分钟步数区间覆盖、可比情境、无区间冲突才标记 eligible_for_research。标签撤权阻止新标签及派生配对，历史可审计删除；传感器撤权即时排除对应特征。无自动上传、无跨用户训练、无模型调用。
- 自评不是设备测得的压力真值。当前仅形成研究数据对；后续按时间/用户划分验证、校准与独立研究授权后才允许训练模型，不将特征可用性当作准确率。


## V3 个性化压力预测研究评估

独立授权：GET/PUT /api/v1/health/pressure/research/consent（policy_version=pressure-research-v1），仅注册用户且自评授权开启时可授予；撤回自评同时撤回研究授权。POST /api/v1/health/pressure/research/evaluate 接收 source、data_origin、device_scope，对该用户单一设备最近60天标签进行回顾性评估（最多180个标签，最多20万条窗口观测），不持久化模型、不共享原始数据、不跨用户训练。撤回授权或删除样本后的请求重新计算。

- 过滤不合格配对；按时间保留至少40分钟间隔的样本，避免共享生理输入窗口。
- 按 UTC 日排序，前约70%有数据日期训练、后约30%测试，训练与测试保持40分钟隔离。至少14训练样本/7训练日、6测试样本/3测试日，训练标签至少3个不同值，测试情境在训练中出现。门槛为工程起点，不是统计功效保证。
- 模型：固定 L2 系数1的岭回归，训练期稳健中位数/MAD归一化低步数心率、整体心率与低步数心率差、log(1+步数)，情境独热编码。截距不惩罚，预测限制在自评0–10。测试样本不参与基线或拟合。对照：训练标签中位数、仅情境岭回归。
- 输出独立样本数量、训练/测试日、MAE、RMSE、平均误差、相比仅情境模型的MAE改善；无足够数据直接返回 insufficient_data。正改善不代表临床可靠性，deployable 固定 false。不输出实时压力评分，不改动 Harness。回顾性对齐允许历史补传，不能证明在线可用性；下一阶段需前瞻性、按时间可用性验证，独立真实数据校准与泛化评估。
- 合成单测验证已知信号可被拟合、窗口去重和训练数据隔离，不等于真实用户实验结果。
