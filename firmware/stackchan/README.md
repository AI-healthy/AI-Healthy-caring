# Stack-chan 固件接入

**状态：硬件规格已确认（M5Stack StackChan K151 / CoreS3），固件尚未上板验证。**
本目录暂不包含可烧录固件；设备协议、离线重试与触摸回执已在宿主侧运行时的
`services/api/src/shiyi_api/device_runtime.py` 中验证。

- 设备能力与上板清单：[../../docs/STACKCHAN_DEVICE_PROFILE.md](../../docs/STACKCHAN_DEVICE_PROFILE.md)
- 白名单协议：[../../docs/LAN_DEVICE_PROTOCOL.md](../../docs/LAN_DEVICE_PROTOCOL.md)

设备端只接收六类白名单指令：
`SET_EXPRESSION`, `SPEAK_TEXT`, `PLAY_GUIDE`, `SHOW_TIMER`, `MOVE_HEAD_PRESET`, `CANCEL_TASK`。
不接受任意舵机角度/速度、任意文本或模型生成的底层指令。

首个真机目标：App 提交活动 → API 生成命令 → 机器人表情/字幕/提示音/计时 → 触摸确认或拒绝 →
回执同步。机器人回执不代表用户完成活动。

待实机验证：音频/TTS 方案、舵机中位与限位、三区触摸映射、断网重连、物理动作幂等。
生产需 TLS、配对、短期凭据、限频；不将云模型密钥写入固件，不使用摄像头推断疾病或情绪。

参考：<https://docs.m5stack.com/en/StackChan>
