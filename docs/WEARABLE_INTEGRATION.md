# 穿戴设备接入 V0.1 · WU-03 / XU-03

## 当前实现

Gadgetbridge → Health Connect → 时宜 Android → 授权 HTTPS API。先用成熟驱动验证荣耀手环 4 的真实记录；最终单 APK 方案保留 WearableReader 抽象，后续由 Gadgetbridge 二次开发实现直接 BLE。当前没有内嵌 Gadgetbridge，也不需要修改手环固件。

- 官方驱动：[Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge)，[Honor Band 4](https://gadgetbridge.org/gadgets/wearables/huawei-honor/)，[Health Connect 导出](https://gadgetbridge.org/basics/integrations/health-connect/)。
- 官方 Android [接入说明](https://developer.android.com/health-and-fitness/health-connect/get-started)。
- 首次实测通过后记录设备型号、固件版本、Gadgetbridge 版本、记录数量、时间范围和采样间隔，不提交真实个人数据。

## 真机测试

1. Android 9+ 安装支持 Health Connect 导出的 Gadgetbridge 版本，并保证 Health Connect 服务可用。
2. 关闭 Ubuntu 与手环的连接；通过 Gadgetbridge 配对 Honor Band 4，开启连续心率，步行几分钟后执行活动数据同步。需要睡眠记录时跨夜佩戴。
3. 根据 Gadgetbridge 官方文档开启 Health Connect 导出并授权写入所需指标；检查系统 Health Connect 中是否出现记录。
4. Android Studio 打开 apps/android，以 JDK 17 配置 SDK 36。同步 Gradle，安装时宜 App。当前仓库没有 Wrapper，可通过 Android Studio 或本机兼容 Gradle 生成。
5. 时宜「我的」→「授权读取健康数据」→「读取最近七天」。默认来源包名 nodomain.freeyourgadget.gadgetbridge，若实际构建包名不同，按 Health Connect 中来源修改。
6. 比较记录时间、数量及心率/步数与 Gadgetbridge，缺失保持暂无。休息、正常步行和睡眠分别验证，不能将历史 BPM 当 HRV。

## 指标映射

| Health Connect | 后端 metric | 语义 |
|---|---|---|
| HeartRateRecord.samples | heart_rate_bpm | 每个样本的 BPM 与时间 |
| RestingHeartRateRecord | resting_heart_rate_bpm | 来源明确标记的静息心率 |
| StepsRecord | steps | 原始区间步数，不重复聚合日累计 |
| SleepSessionRecord | sleep_minutes | 会话经过的整分钟；不是精确生理睡眠 |

记录最多七天、分页读取、仅选定来源。ID 使用来源包名、指标、记录 ID、样本时间的 SHA-256；重传幂等。若源记录修订且相同 ID 内容改变，当前服务器返回 409，需后续实现版本化更新，不能自动覆盖。不同时间区间可能重叠，不能直接相加。尚无 HRV、实时心率流、原始 PPG、压力测量或可靠深睡阶段保证。

## 后端受控上传

默认 SHIYI_ENABLE_REAL_HEALTH=0，不接收真实数据。启用前需受试者明确同意、可信 TLS、访问控制和受保护存储/备份，不公开部署。仅在团队控制环境将环境变量设为 1。真实数据要求注册账号（非开发 token），health_connect 来源、真实策略 local-wearable-v1 和来源包名 data_origin。来源由客户端报告，不是服务端验证的硬件身份证明。

App 中输入受控 HTTPS 服务 origin 和注册账号的 access token（不持久化），点击「授权服务器采集预览指标」后再点击「上传预览记录」。每批最多 100 条；失败可重试，先前成功批次保留。可撤回本地和服务器权限，历史通过现有 DELETE 接口清除。后端未启用时会拒绝上传。本地 HTTP 不发送真实健康数据。Harness 暂不自动消费真实记录。

测试：services/api 下执行 python -m pytest -q 和 python -m ruff check src tests；Android 构建及真实设备数据需要团队真机验证。

## 单 APK 后续迁移

Gadgetbridge 是完整 AGPL-3.0 Android 应用，不是 Maven SDK。以官方稳定源码为基座，保留 HuaweiLESupport、HuaweiSupportProvider、HuaweiSyncState、HuaweiCrypto、HuaweiPacket、HuaweiTLV、FitnessData、HuaweiSampleProvider、设备与数据库服务。先跑通原版，再将时宜 Compose 页面和 WearableReader 适配器移入同一应用工程；以同步完成事件查询 HuaweiActivitySample 并转换为观测。保留许可与作者声明、开放衍生应用对应源码；核对 AGPL 义务后再分发。无需继续自研 Python 认证协议。
