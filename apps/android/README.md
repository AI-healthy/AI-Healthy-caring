# Android · Jetpack Compose 起点

Android Studio 打开 `apps/android`。首页活动与 Stack-chan 仍为静态演示；「我的」新增 Health Connect 读取及受控 HTTPS 上传面板。

起点：AGP 8.13.2、Kotlin 2.2.21、Compose BOM 2026.09.00。需要在团队 Android Studio/SDK 环境下确认可编译，并生成 Gradle Wrapper；本次不宣称已通过 Android 构建。

推荐包划分：`feature/today`、`feature/seasons`、`feature/explore`、`feature/profile`，以及 `core/network`、`integration/healthconnect`、`integration/device`。

## 穿戴接入

参见 [WEARABLE_INTEGRATION.md](../../docs/WEARABLE_INTEGRATION.md)。先通过 Gadgetbridge 配对并导出至 Health Connect；本阶段不内嵌蓝牙驱动。Android 9+ 需可用 Health Connect（Android 14+ 通常内置）。首次授权后手动读取最近七天；无数据时不显示伪造数值。上传需受控 HTTPS 后端及注册账号 token。
