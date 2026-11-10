# 时宜 ShiYi

> AI + 智能穿戴 + 四时生活文化 + Stack-chan 实体陪伴
>
> 第二十届全国大学生软件创新大赛 · AI + 健康赛道

**状态：工程启动骨架，非可交付产品。** 后端演示接口可运行；Android 尚未实机编译；Stack-chan 固件与健康穿戴数据未接入。

## 组成

- `apps/android/`：Kotlin + Jetpack Compose，今日／四时／探索／我的
- `services/api/`：FastAPI、规则推荐、演示节气内容、反馈接口
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

经授权的穿戴记录／主动反馈 → 活动候选 → 用户选择 → Stack-chan 陪伴（未来接入）→ 反馈 → 推荐调整。

**重要**：本仓库不是医疗诊断、治疗、开方或心理疾病识别系统。演示数据标记 `is_demo`，不得误当真实健康记录。严禁上传个人健康原始数据、音频或云服务密钥。

详见 [架构设计](docs/ARCHITECTURE.md)、[团队规范](docs/CONTRIBUTING.md)、[工作清单](docs/BACKLOG.md)。
