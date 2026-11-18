# Stack-chan 模拟器

## 离线单命令校验

```bash
python simulators/stackchan_sim.py packages/contracts/stackchan-command.example.json
```

只验证一条表情命令的字段、过期与回执，不接入真实机器人。

## 有状态设备运行时（LAN-02/LAN-03）

`services/api/src/shiyi_api/device_runtime.py` 在本地 REST 协议上模拟真实设备的完整行为：

- 轮询命令 → ACK → 执行白名单动作 → 完成/失败回执；
- 触摸 `confirm` / `decline` → `COMPLETED(touch_confirmed)` / `FAILED(user_declined)`；
- 断网时终态事件写入 spool，下次启动先回放（同一 event_id，服务端去重）；
- 收到 `ACKNOWLEDGED` 后重启不重复执行，直接补发终态；
- `--speed` 把 5 分钟活动缩短到秒级，便于演示。

```bash
export SHIYI_API_URL=http://127.0.0.1:8000
export SHIYI_SIM_DEVICE_ID=sim
export SHIYI_SIM_DEVICE_TOKEN=...
python -m shiyi_api.device_runtime --once --touch confirm --speed 0
python -m shiyi_api.device_runtime --drain --speed 0
```

完整演示：`bash scripts/demo_lan.sh`；测试见
`services/api/tests/test_lan_protocol.py`。仍为**模拟器**，不是 K151 实机。
