# Android · Jetpack Compose 起点

Android Studio 打开 `apps/android`。首页活动与 Stack-chan 仍为静态演示；「我的」新增 Health Connect 读取及受控 HTTPS 上传面板。

起点：AGP 8.13.2、Kotlin 2.2.21、Compose BOM 2026.09.00。需要在团队 Android Studio/SDK 环境下确认可编译，并生成 Gradle Wrapper；本次不宣称已通过 Android 构建。

推荐包划分：`feature/today`、`feature/seasons`、`feature/explore`、`feature/profile`，以及 `core/network`、`integration/healthconnect`、`integration/device`。

## 穿戴接入

参见 [WEARABLE_INTEGRATION.md](../../docs/WEARABLE_INTEGRATION.md)。先通过 Gadgetbridge 配对并导出至 Health Connect；本阶段不内嵌蓝牙驱动。Android 9+ 需可用 Health Connect（Android 14+ 通常内置）。首次授权后手动读取最近七天；无数据时不显示伪造数值。上传需受控 HTTPS 后端及注册账号 token。

## StackChan 陪伴

在底部「陪伴」页轻点角色可以打开文字聊天，长按摸头，或点「一起慢呼吸」
进行三轮吸气／呼气。触觉反馈遵循 Android 系统设置。
角色根据 Stack-chan 的屏幕、三键和桌面底座绘制。形象参考
[Stack-chan 官方项目](https://github.com/stack-chan/stack-chan)。

在运行时宜 API 的机器上启动 Ollama，在 API 的启动环境中设置
`SHIYI_COMPANION_MODEL` 为 `ollama list` 中的模型名，例如 `qwen3.6:35b-a3b`。
默认连接同机的 `http://127.0.0.1:11434/v1/chat/completions`。
手机的「对话设置」填可达的时宜 API HTTPS 地址和已有的时宜登录令牌，
与穿戴接口使用同一身份验证。开发联调也可使用 `SHIYI_DEV_USERS` 配置的测试令牌。

`POST /api/v1/companion/chat` 请求格式为
`{"messages":[{"role":"user","content":"今天有点累，陪我聊聊吧"}]}`。
多轮时按 user、assistant 的顺序传入最近四组完整问答，附本轮 user 消息。
响应形如 `{"reply":"当然，我在。","reaction":"calm"}`，表情支持
`nod`、`cheer`、`calm`。聊天和连接信息在 App 运行期间保留在界面内存中，
普通聊天无需穿戴或日程权限，模型仅收到聊天文字。
