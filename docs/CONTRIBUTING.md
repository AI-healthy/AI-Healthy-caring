# 团队协作

- `main`：稳定分支（建议 GitHub Ruleset 禁止强推、PR + CI 通过后合并）。
- 开发分支：`feat/<area>-<topic>`、`fix/<area>-<topic>`、`docs/<topic>`。
- PR 必须有问题背景、接口影响、测试方式、截图或日志；建议一人 Review。
- 后端修改同步更新 OpenAPI、跨端契约和测试。
- 不提交云服务密钥、私密录音、真实健康数据和个人信息。
- 明确标注模拟数据，区分已完成与待接入模块。

建议 Labels：android、backend、firmware、ai、content、design、infra、bug、P0、P1、needs-decision。
