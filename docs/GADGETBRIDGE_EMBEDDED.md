# Gadgetbridge 单 APK 实验版

## 目标和实际实现

一个安装包包含时宜原有 Compose 四页界面、时宜原生 Compose 设备管理、Gadgetbridge BLE 认证与同步框架，以及直接从 HuaweiActivitySample 读取真实历史数据的适配器。无需 Health Connect 或另外安装 Gadgetbridge。旧的 Health Connect App 仍保留作快速联调及其他来源兼容。

当前以已核对源码的原官方 GitHub 镜像提交 a0948ee1cbc2a870f91d313f8e37df5f524465f7（0.83.0）作为可复现的实验基线，不宣称这是最新版本。正式发布前需要评估并迁移至 [官方 Codeberg 仓库](https://codeberg.org/Freeyourgadget/Gadgetbridge) 的受支持稳定版。

## 构建

在仓库根目录运行（JDK 17、Android SDK platform 35，配置 ANDROID_HOME；需访问 GitHub、Gradle、Google Maven、JitPack）：

    python3 scripts/build_embedded_gadgetbridge.py --dest ~/health_band_dev/shiyi-embedded --build

目标目录必须不存在，脚本不会覆盖原始仓库或已有工作。也可以不加 --build，仅生成可用 Android Studio 打开的工程。APK 预期在生成工程的 app/build/outputs/apk/mainline/debug/。实验包名 org.aihealthy.shiyi.embedded，避免覆盖时宜原 App；Gadgetbridge 历史版本可能存在固定 provider authority，真机如遇安装冲突，先备份并在专用测试机上停用/卸载冲突版本。不要随意清除有价值的历史数据。

## 真机测试

1. 关闭 Ubuntu 对手环的连接。使用测试手机安装实验 APK，打开时宜「我的」→「搜索附近手环」，授予系统蓝牙权限，选择荣耀手环并点击连接；如手环提示确认，在手环上确认。时宜直接调用内嵌驱动，不启动 Gadgetbridge 页面。
2. 仅授予连接与健康同步所需权限；不启用通知转发、电话、短信等无关功能。
3. 开启连续心率，佩戴一段时间，正常步行；选择 Honor Band 4，再点「同步手环历史数据」。
4. 请求同步为异步操作；在时宜页面确认同步结束，再勾选本地读取授权，点击读取最近七天。
5. 核对原始心率、区间步数、睡眠时段与 Gadgetbridge 图表。未佩戴或无采样时不补零。当前不提供即时流、HRV 或静息心率推断。
6. 可选使用受控 HTTPS 后端，以注册账号授权 gadgetbridge 来源并显式上传。重复同步幂等，禁止提交真实记录、密钥或 token。

## 实现细节

- 保留上游 GBApplication、ControlCenterv2、DeviceService、HuaweiSupportProvider、HuaweiLESupport 和原始 GreenDAO 数据库。
- EmbeddedBandReader 仅选择 HonorBand4Coordinator；使用 DBHelper.findDevice 和 HuaweiActivitySampleDao 限定设备，读取原始开始记录，过滤镜像结束记录。
- 0x0b 步数记录对应 60 秒窗口；心率保留原始时间与 BPM，排除 0/-1/255。0x0d 普通睡眠、0x0a 旧 TruSleep 起止记录不标记为精确睡眠阶段；重叠优先 TruSleep。七天窗口只读完整结束的区间；不对样本补值。
- 样本 ID 为哈希后的设备地址、指标、时间及来源。上传不含明文 MAC。后端使用独立 gadgetbridge 来源授权，与 health_connect 不混用；试验期间不要同时上传两个来源中的同一组手环记录。
- 本地读取和服务器上传均需显式操作，未自动运行 Harness。

## 许可证和分发

Gadgetbridge 为 AGPL-3.0-or-later。保留 upstream LICENSE 和版权声明；如果分发修改 APK，提供完整对应源代码（固定 upstream 源码、时宜覆盖文件、构建脚本及修改内容），并满足适用 AGPL 条款。当前仓库仅提交独立编写的覆盖层和可复现构建脚本，未复制完整上游工程。正式发布前由团队检查完整衍生应用许可和第三方组件许可。当前为实验分支，不发布 APK。

## 验收

CI 编译成功只是工程验证；必须以真实 Honor Band 4 完成配对、同步、非空健康记录、重启后重新连接，才算硬件接入成功。

## 可复现数据库生成器

旧版 JitPack 的定制 greenDAO 工件不可解析时，构建脚本直接获取原项目固定提交 `1998d7cd2d21f662c6044f6ccf3b3a251bbad341` 的生成器 Java 源码和 FreeMarker 模板，并以现有 Gradle 编译，保持数据库 schema 生成行为。对应源码与许可证保留于 `third_party/greendao`，一并归档。

## 原生配对交互

NativeBandConnection 使用 30 秒 BLE 与经典蓝牙发现，按固定上游 DeviceHelper.resolveDeviceType(candidate, false) 识别所有注册真实型号（排除 UNKNOWN、TEST、SCANNABLE、BLE_GATT_CLIENT 等通用/测试入口），离开页面取消扫描。该型号在固定上游的 HuaweiLECoordinator 中明确使用 BONDING_STYLE_NONE：首次连接直接调用 GBApplication.deviceService(device).connect(true)，已记录设备使用 connect(false)。通过上游本地设备状态广播更新 Compose；只有 isInitialized 才显示连接成功。连接超时不伪造成功，不自动删除绑定记录。保留系统权限及手环端确认。真机验收：从时宜入口扫描、连接、同步和读取均不跳转至 Gadgetbridge Activity。

## 多设备接入

扫描匹配采用完整上游协调器注册表，合并广播名称、服务 UUID 和已绑定设备；按地址独立列出设备，可逐个发起连接、切换选择与断开。手动地址未知时必须明确选择实际型号，不能自动套用 Honor 4。通用原生配对处理 NONE/LAZY、BOND、ASK 和 REQUIRE_KEY（显式输入、原生系统配对），已有设备可重连。专用配对 Activity 的新设备标记为需要独立适配，不跳转第三方 UI。识别与连接能力不等于数据适配：目前仅 Honor Band 4 的原始健康记录转换已实现，其他型号允许驱动支持的历史同步但不直接转换或上传未核实数据。多设备同时连接能力由硬件、Android 和驱动决定，需真机验证。

## 首页健康数据与自动同步

在「我的」选择已支持原始记录读取的主设备，点击「授权并设为首页主设备」。该选择保存在应用私有偏好中，健康记录仍由原有本地数据库提供；首页和设备管理共享前台控制器。Activity 处于 RESUMED 时每约 15 分钟请求同步（仅已连接且空闲），使用 ACTION_NEW_DATA 按设备匹配完成事件，超时 120 秒；事件仅表示驱动结束，不保证新增样本。每分钟重新读取本地数据；离开前台停止发起新请求。关闭授权立即清空首页视图，不删除手环或原始数据库记录。服务器上传仍独立、显式授权。

日汇总按手机时区：今日完整步数区间去重并排除重叠，跨日区间不估算；昨晚 18:00 至今日 12:00（或当前时间）的睡眠区间求并集，不推断睡眠阶段；最近有效心率显示其原始测量时间；缺失值不补零。主设备单独汇总，避免跨设备重复计数。压力状态暂为待评估。新增四个聚合单测，CI 通过后再真机验收。
