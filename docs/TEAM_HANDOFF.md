# V1.0 Alpha 团队交接

2026-11-15 · PR #5 已合并 main，基准提交 432b4cf。最新合并前 CI 74 项测试及完整模拟闭环通过。无真实设备、正式部署或真人健康效果结论。

## 第一次同步

先保存本地未提交修改，再执行：
```bash
git fetch origin
git switch main
git pull --ff-only origin main
```
还没有个人功能分支时，从更新后的 main 创建它（仅执行自己的命令）：
```bash
git switch -c feat/wu-season-ui
# 或 git switch -c feat/lan-stackchan-control
# 或 git switch -c feat/fu-knowledge-cards
```
已有分支请切回该分支并 merge origin/main，解决冲突后提交；不要删除已有工作。

## 启动与联调

参考 [README](../README.md) 与 [LOCAL_WORKBENCH](LOCAL_WORKBENCH.md)。Ubuntu 使用 run_local.sh；Windows 可尝试 run_local.ps1（尚未实机验收）。工作台仅 loopback，不是手机/机器人网络服务，不要暴露公网或输入真实健康数据。手机联调需单独设计受控测试网络及授权。

## 四人交接

| 成员 | 当前可使用的成果 | 下一步验收 |
| --- | --- | --- |
| xu | 账号、活动、授权合成观测、设备模拟、Harness、Benchmark、工作台 | OpenAPI 契约联合评审、跨端调试、安全部署与真机集成 |
| wu | 用户登录、授权、候选、活动、记忆、主动邀请 API | Android 编译通过；接通登录→推荐→选择→完成→反馈，真实穿戴权限单独验收 |
| lan | 模拟设备注册、命令队列、独立 ACK、MCP 只读工具、模拟邀请 | K151 能力测试；真实语音工具和安全设备命令逐项对接，不把模拟协议当原生协议 |
| fu | RuleRanker 与 LocalModelRanker 接口、合成评估框架 | 内容卡与 RAG 来源审核、候选排序对照实验；与 xu 评审契约，不擅自发送健康数据 |

## 技术入口

- [用户与健康数据](USER_HEALTH_API.md)
- [活动 API](ACTIVITY_API.md)
- [Agent Harness](HARNESS.md)、[模型适配](MODEL_ADAPTER.md)、[记忆](MEMORY_HARNESS.md)、[主动陪伴](PROACTIVE_HARNESS.md)
- [设备与 MCP](INTEGRATION.md)
- [合成 Benchmark](HARNESS_BENCHMARK.md)
- [团队任务](TEAM_TASKS.md)

CI 通过不等于实机联调完成。接口变更需调用方同意并新建 PR，推荐至少一名非作者 review，禁止强推 main。不得提交隐私数据、配对令牌或模型密钥。Issue #1 保持开放，真实联调与部署不关闭。
