# Android · Jetpack Compose 起点

Android Studio 打开 `apps/android`。当前为 **静态页面**，未接服务端、穿戴设备或 Stack-chan。

起点：AGP 8.13.2、Kotlin 2.2.21、Compose BOM 2026.09.00。需要在团队 Android Studio/SDK 环境下确认可编译，并生成 Gradle Wrapper；本次不宣称已通过 Android 构建。

推荐包划分：`feature/today`、`feature/seasons`、`feature/explore`、`feature/profile`，以及 `core/network`、`integration/healthconnect`、`integration/device`。
