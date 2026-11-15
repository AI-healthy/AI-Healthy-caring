# V0.8 Proactive Agent Harness · 主动陪伴（本地模拟）

原有 scheduled_check 仍是客户端手动评估；新增独立的持久化调度器、限时可用声明、邀请收件箱和模拟设备收执。仅合成数据；不在用户不知情时进行推送、实际语音或动作。App 和机器人固件未修改，不依赖云模型。

## 运行机制

1. 用户在 Harness 设置中主动开启 proactive_enabled（默认 false），然后用经过身份验证的 API 明确声明可用时间和投递渠道。
2. 可用声明持续 15–120 分钟（默认30），可用活动时长 1–30 分钟（默认5）；不能自动续期。PUT enabled=false 停止调度并作废待确认邀请。新声明替换旧声明且使旧邀请失效。
3. worker 每30秒扫描已到期计划（一次最多50个；每用户15分钟至多评估一次），直接使用同一 SQLite 数据库。开启和续期后首次检查立即到期。
4. 每用户检查和计划/邀请写入在一个 SQLite 事务中，失败回滚；重复 worker 不创建重复邀请。默认规则决策，不调用网络/LLM。忙碌、已有活动、待确认计划、用户勿扰、频控或无候选等限制继承 Harness；没有可用声明就不检查。暂停后需手动重新声明，过期不会主动补发。
5. 计划与邀请一同入库，有效期最多10分钟且不超过可用声明截止；读取前再校验勿扰、授权开关、租约、活动状态、模拟设备归属。撤销设置或健康授权等原有 invalidation 同样阻止未确认计划；撤销设备使其待确认邀请失效。
6. 用户收件箱查看 run 与候选，选择确认或拒绝使用现有 /harness/runs/{run_id}/confirm 或 /dismiss。确认仅生成 CREATED 会话，开始/完成与设备命令仍走已有 API。
7. 模拟设备仅收到 offer_id、固定 message_code、截止时间和 is_demo，不收到任何原始健康状态、用户令牌、候选详情。设备 ACK 仅表示收执，不证明实际显示、用户接受或活动完成。客户端以 offer_id 去重，收执后设备不再轮询到该邀请。网络失败前可重复拉取，不保证真实展示恰好一次。
8. App 若选 simulator 渠道，仍可主动打开收件箱选择，但不要自动发出 App 提醒；只有选 app 渠道时允许用户端 ACK，不重复投递两个渠道。没有推送服务、WebSocket、TTS 或固件控制。未来由 wu/lan review 后接原生终端。

## API（前缀 /api/v1/proactive）

均需身份验证；设备凭证只用于明确绑定的注册模拟器。
- GET /schedule：当前声明、available_until、next_check_at、last_reason；enabled 是声明开关，过期后可能仍 true，但 next_check_at 为 null，不表示仍可用。
- PUT /schedule：{"enabled":true,"available_minutes":5,"available_for_minutes":30,"channel":"app"}；或 channel=simulator 且 device_id 为本人注册的 sim_ ID。禁用时可只传 {"enabled":false}。
- GET /offers/pending：当前合法邀请或 null（嵌套 run、channel、acknowledged_at）；轮询不代表实际通知。
- POST /offers/{offer_id}/ack：app 渠道收执；同一邀请重试幂等；404 非本人或非该渠道，409 已经不可投递。
- GET /devices/{device_id}/pending：独立模拟设备凭证；最小泛化邀请或 null。
- POST /devices/{device_id}/offers/{offer_id}/ack：设备收执，不能代替用户确认。
- 原有 PUT /harness/settings 为完整替换，修改前 GET 再合并。建议用户离开时 PUT /schedule enabled=false。两层开关需同时开启；关闭 Harness proactive_enabled 后 worker 停止处理，重新开启须显式重新声明。

## 本地运行

终端 A 使用现有启动流程，建议设置绝对路径 SHIYI_DB_PATH 以保证进程共享数据库。
终端 B 同一 venv（且同一 SHIYI_DB_PATH）：
```bash
python -m shiyi_api.harness.scheduler --once
# 或明确启用本地演示 worker（Ctrl+C 停止）
python -m shiyi_api.harness.scheduler --interval 30
```
终端 C 可使用已注册合成模拟器凭证：
```bash
python -m shiyi_api.harness.invitation_simulator
```
该程序只输出固定邀请文案和提交收执，不控制 K151。真实机器人需确认原生协议、语音/表情模式、授权与回执语义，设计真正的离线回退、推送和可撤销执行。现有活动设备命令仍可通过 shiyi_api.simulator 测试。

本版的15分钟、10分钟和可用声明上限是工程初值；没有用户实验支持其最优性。无真实健康数据、自动推送或医学判断。
