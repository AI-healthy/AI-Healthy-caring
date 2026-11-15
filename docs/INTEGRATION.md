# XU-02 联调指南 · 本地模拟与 XiaoZhi MCP

## 状态与边界

活动 API、模拟设备 REST 通道、有条件的命令回执、MCP 只读工具已提供。
设备协议是 ShiYi 草案，不是 M5Stack 原生协议；真实设备、Android、穿戴和公网部署均须另行验证。
所有测试使用合成数据。阶段内不引入 Go 后端、外部健康记录或真实个人身份。
MCP 工具不创建任务、不读取个人记录，不含用户或设备令牌。语音输入仍由小智平台处理；
测试请勿说出真实姓名、健康数据或其他个人隐私。

## Ubuntu 本地一键模拟

从仓库根目录执行 `bash scripts/demo_backend.sh`（Linux/macOS，Python 3.11+）。
首次安装依赖需联网；脚本启动本地 API，创建合成活动，获取命令，
由模拟客户端提交 ACK/完成，然后用户端确认完成及反馈。进程退出会停止 API。
端口 8000 应空闲。脚本通过临时目录保存演示数据库并清理。

## API 与设备状态

- 用户端：POST /api/v1/devices/commands（session_id, device_id, preset, client_request_id）
  → GET /api/v1/devices/commands/{command_id}
- 设备端：GET /api/v1/devices/{device_id}/pending（无待处理请求时为 null）
  → POST /api/v1/devices/{device_id}/events（独立设备 Bearer token）
- QUEUED → ACKNOWLEDGED → COMPLETED / FAILED。
  活动结束或命令过期时，未终结命令在访问时标记 CANCELLED / EXPIRED。
- 命令重复投递可能发生；同一事件 ID 必须重发完全相同的消息；模拟器重启后先查询状态，已 ACK 则直接发送模拟终态。当前仅无副作用的模拟表情，
  真机应持久化已执行 command_id，设计物理命令幂等和执行取消。REST 不等于 WebSocket；
  后续适配器可更换传输层，但不应把命令完成理解为用户活动完成。
- 设备白名单来自 SHIYI_DEV_DEVICES，身份必须绑定已存在的开发用户。
  访问时检查当前配置，无真实设备配对或线上认证功能。

## XiaoZhi MCP 第一次实机测试

从仓库根目录，在独立终端分别运行：

```bash
cd services/api
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,mcp]'
uvicorn shiyi_api.main:app --host 127.0.0.1 --port 8000
```

MCP 只读工具不需要开发用户令牌。第二个终端（仓库根目录）：

```bash
source services/api/.venv/bin/activate
python -m pip install mcp2xiaozhi
read -r -s -p "Paste XiaoZhi MCP endpoint: " MCP_ENDPOINT
export MCP_ENDPOINT
echo
mcp2xiaozhi --config integrations/xiaozhi/mcp_config.json run shiyi
```

从官方 StackChan World 当前设备的 MCP 页面获取接入 URL，不要截图公开、提交 Git 或把 token 发给他人。
桥接器与 FastAPI 必须在线；FastAPI 仅监听 loopback。第三方桥接器可见语音工具参数及结果；
不允许真实健康记录，接入前核查其依赖和平台隐私条款。命令行依据 MCP2Xiaozhi 官方说明：
https://stanleychanh.github.io/MCP2Xiaozhi/quick-start/ 及 /configuration/。

模型角色设置建议：当用户问时宜示例节气卡时调用 get_shiyi_season_card；
当问五分钟微活动时调用 recommend_shiyi_activity；一律说明样例数据、不代表真实日期或医疗建议。
工具失败时不要编造。问机器人“请调用时宜工具读取演示节气卡”，预期返回固定立冬样例，
再问“调用时宜工具推荐五分钟活动”。检查本地 API 访问日志、MCP 页面工具列表和语音回复。
当前 PR 的自动化验证不包含实际小智云服务或 K151；接入点和真实语音必须现场验证。
