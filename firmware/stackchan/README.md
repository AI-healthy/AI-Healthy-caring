# Stack-chan 固件接入

**状态：待确定具体设备 SKU；目前没有刷机固件。**

优先使用官方 Stack-chan K151 BSP / SDK，设备端只接收安全白名单指令：
`SET_EXPRESSION`, `SPEAK_TEXT`, `PLAY_GUIDE`, `SHOW_TIMER`, `MOVE_HEAD_PRESET`, `CANCEL_TASK`。

首个真实演示目标：App 提交活动 -> API 生成命令 -> 机器人显示表情／语音提示 -> 触摸确认 -> 回执同步。

认证与传输待实机和网络环境验证：生产需 TLS、配对、短期凭据、限频与舵机角度/速度限制。不将云模型密钥写入固件；不使用摄像头推断疾病或情绪。

参考：https://docs.m5stack.com/en/StackChan
