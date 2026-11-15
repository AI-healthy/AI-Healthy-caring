# 时宜 ShiYi

> AI + 智能穿戴 + 四时生活文化 + Stack-chan 实体陪伴
>
> 第二十届全国大学生软件创新大赛 · AI + 健康赛道

**状态：本地后端 MVP，非可交付产品。** 本地 Agent Harness、账号与合成健康数据授权、活动与反馈 SQLite 持久化、设备模拟 REST、MCP 只读工具；Android、Stack-chan 原生固件与真实穿戴数据尚未经代码联调。

## 组成

- `apps/android/`：Kotlin + Jetpack Compose，今日／四时／探索／我的
- `services/api/`：FastAPI、规则推荐、演示节气内容、持久化活动与反馈、设备模拟接口
- `firmware/stackchan/`：固件接入边界，待确定硬件版本
- `packages/contracts/`：跨端设备消息示例
- `simulators/`：离线 Stack-chan 指令模拟器
- `docs/`：系统架构、决策记录、协作规范
- `.github/workflows/`：后端持续集成

## 本地运行后端

```bash
cd services/api
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn shiyi_api.main:app --reload --port 8000
```

访问 http://127.0.0.1:8000/docs；测试：`python -m pytest -q`。

## 核心闭环

经授权的穿戴记录／主动反馈 → 活动候选 → 用户选择 → Stack-chan 陪伴（模拟协议，真机待接入）→ 反馈 → 推荐调整。

**重要**：本仓库不是医疗诊断、治疗、开方或心理疾病识别系统。演示数据标记 `is_demo`，不得误当真实健康记录。严禁上传个人健康原始数据、音频或云服务密钥。

详见 [架构设计](docs/ARCHITECTURE.md)、[团队规范](docs/CONTRIBUTING.md)、[工作清单](docs/BACKLOG.md)。


## 联调

运行 `bash scripts/demo_backend.sh`（仓库根目录，Python 3.11+）验证本地模拟闭环。
活动 API：[ACTIVITY_API.md](docs/ACTIVITY_API.md)；
设备模拟与小智 MCP：[INTEGRATION.md](docs/INTEGRATION.md)。

用户与健康数据接口：[USER_HEALTH_API.md](docs/USER_HEALTH_API.md)（仅合成数据）。

智能体运行框架：[HARNESS.md](docs/HARNESS.md)（本地规则基线与用户确认；无外部模型或自主推送）。

可选本机模型排序：[MODEL_ADAPTER.md](docs/MODEL_ADAPTER.md)（默认关闭，规则回退，不接收真实健康数据）。

记忆检索与隐私控制：[MEMORY_HARNESS.md](docs/MEMORY_HARNESS.md)（V0.7 合成数据）。

主动陪伴调度与模拟邀请：[PROACTIVE_HARNESS.md](docs/PROACTIVE_HARNESS.md)（需要独立启动本地 worker；不实际推送）。

Harness 合成评估：[HARNESS_BENCHMARK.md](docs/HARNESS_BENCHMARK.md)（V0.9，不代表真人健康效果）。

V1.0 本地联调工作台：`bash scripts/run_local.sh`（临时合成数据库、可控调度器、仅 loopback）；详见 [LOCAL_WORKBENCH.md](docs/LOCAL_WORKBENCH.md)。不是生产部署或 Android/机器人实机验收。
