# Stack-chan K151 实机测试记录

> 记录：`lan`（Tangshi777） · 2026-11-19
> 原则：区分“K151 现有/官方固件的能力验证”与“本仓库 `firmware/stackchan` 骨架（未上板）”。
> 本文只记录已实际发生的测试；没有串口日志/视频的项标注“成员自测，待补证据”。

## 1. 本次实机验证

| 日期 | 设备 | 固件/环境 | 测试项 | 结果 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 2026-11-19 | StackChan K151（CoreS3） | 设备现有固件 | 头颈动作（yaw/pitch） | **PASS** | 成员现场操作；待补视频 |
| 2026-11-19 | StackChan K151（CoreS3） | 设备现有固件 | 语音唤醒 | **PASS** | 成员现场操作；待补视频 |
| 2026-11-19 | StackChan K151（CoreS3） | 设备现有固件 | 表情响应 | **PASS** | 成员现场操作；待补截图 |

结论：K151 的双舵机、麦克风唤醒链路和屏幕表情能力可用，LAN-01 的 SKU/SDK 选型成立。

## 2. 本次未覆盖

- 三区触摸（front/middle/back）实际映射；
- 12 路 RGB 序号与亮度；
- 提示音音量、TTS/音频流；
- 9 轴 IMU 摇晃/跌倒阈值；
- 断网重连与离线回执；
- 30 分钟稳定性、电量与发热。

以上仍需用本仓库 `stackchan-selftest` 与 `stackchan-k151` 固件补测。

## 3. 与本仓库固件的关系

- 本次验证使用的是设备现有固件，**不代表** `firmware/stackchan/` 已编译或已烧录；
- 本仓库固件尚未执行 `pio run`，也未在 K151 上运行；
- 语音唤醒目前属于设备现有固件能力，本仓库固件没有实现唤醒词/ASR，后续语音链路需单独设计；
- 表情/动作在本仓库固件中的映射仍需上板核对（尤其 Y 轴中位与限位）。

## 4. 复现与补测命令

```bash
cd firmware/stackchan
cp include/secrets.example.h include/secrets.h   # 本地联调时填写
pio run -e stackchan-selftest -t upload
pio device monitor -b 115200
```

自检输出应包含：

```
[selftest] display            PASS
[selftest] servo yaw/pitch    PASS
[selftest] rgb 12-led         PASS
[selftest] speaker            PASS
[selftest] TOUCH FRONT        PASS
[selftest] TOUCH MIDDLE       PASS
[selftest] TOUCH BACK         PASS
[selftest] imu accel          PASS
```

把串口输出与测试日期补进本文件后，再更新 [LAN_STATUS.md](LAN_STATUS.md) 与 GitHub Issue #3。
