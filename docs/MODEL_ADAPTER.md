# Harness V0.6 · 模型与工具接口

默认规则，不依赖模型。只允许本机 OpenAI-compatible chat-completions HTTP 端点；
仅用于合成数据。没有云 API、API key、自动下载模型或调用真实个人健康数据的选项。
如果本机运行兼容服务，手动确认其已安装模型、没有云转发或请求日志外发，再启动后端：

```bash
cd services/api
source .venv/bin/activate
python -m pip install -e '.[dev,mcp]'
export SHIYI_RANKER=local_llm
export SHIYI_LOCAL_MODEL_URL=http://127.0.0.1:11434/v1/chat/completions
export SHIYI_LOCAL_MODEL_NAME='YOUR_INSTALLED_MODEL'
uvicorn shiyi_api.main:app --host 127.0.0.1 --port 8000
```

YOUR_INSTALLED_MODEL 是占位符，请换成本机实际模型名。兼容 Ollama 等提供相同 API 的本机服务，
但需确认支持 response_format=json_object；此版本没有测试真实模型推理，CI 使用可控模拟 HTTP 服务。
若模型不支持接口、响应异常、超时或未配置，会回到规则。服务端环境变量和用户
PUT /api/v1/harness/settings 的 use_local_model=true 必须同时开启。关闭后不请求模型。
PUT 是完整替换，保留原有设置时请先 GET、修改需要的字段，再 PUT。

## Context engineering

只给模型候选 ID、时长、固定标签、可用时间、用户选择的偏好标签、粗粒度自评状态、
且仅限分别授权的反馈/行为记忆检索后候选活动聚合决策分数。没有账号、token、原始穿戴数据、对话内容、
具体时间、反馈文本、数据库 ID 或任意客户端自由文本。上限 4096 字节。
固定系统提示加结构化 JSON；不把临床诊断或处方开放为工具。

## Tool routing

模型必须只返回 JSON：{"tool":"rank_activities","activity_ids":["culture","stretch"]}。
仅该工具名通过严格校验；1–3 个互不重复 ID，必须来自服务端候选目录；
不接受其它字段或额外动作。模型无能力发出机器人指令或创建任务。
用户仍需通过 /runs/{run_id}/confirm 明确选择，原子创建 CREATED 活动。
MCP 仍是旧的匿名只读合成演示接口，不共享个人上下文。RAG 与通用多工具代理未实现。

## Runtime & fail-safe

短事务采集快照 → 事务外单次推理 → 短事务重新读取快照并校验写入。
设置变动、撤回授权及删除观测增加上下文 revision，即使推理期间又恢复也不会保留旧提议。
反馈和可用性门控重新查询；不同快照则按最新上下文重新执行本地规则，禁止二次网络推理。
同用户同请求 ID 保证最终只有一条 run；同一请求竞争时，可能有重复模型请求，但不重复创建计划。
该机制不能撤回已经发给本机服务的请求，所以仅限合成数据和用户知情开启。
不等待并发容量（最多2个本机推理），HTTPX 连接/读写各阶段超时5秒、
响应读取时检查总时间；慢分段网络的最坏墙钟时间可能超过5秒，非硬实时取消。
不重试、不跟随重定向、不使用 HTTP 代理，固定 loopback IP，响应上限24576字节。
本机服务自身仍是受信边界，不允许将 loopback 当作生产隔离或安全保证。
日志 trace 只保存阶段结果和算法，非模型思维链。模型原文、错误详情不入库。
algorithm=local_llm_v1 表示模型合法排序；rules_v1_fallback 表示非法/不可用返回规则；
rules_v1 表示默认规则或上下文变更后重算。未开启时 trace 含 opt_in_disabled。
本地接口仍需登录鉴权，真实用户/穿戴/设备、云服务、隐私合规不在本版本验收范围。

## Tests

使用本机模拟 HTTP server 验证真正的 JSON 请求、工具读取、用户 opt-in、
非法 tool/候选、超时与 fallback；通过在 ranker 内执行独立 SQLite 写事务验证没有锁被持有，
并用撤销授权和并发主动检查验证提交前重校验。模拟服务不代表真实 LLM 能力。
