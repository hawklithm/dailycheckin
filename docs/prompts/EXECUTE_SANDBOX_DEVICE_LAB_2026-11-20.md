# 执行 agent 提示词

复制下方完整提示词到执行 agent。此提示词用于实现设备注册实验工具。

```text
你在 D:\workspace\trae2api 工作。请完整实现：
D:\workspace\trae2api\docs\SANDBOX_DEVICE_LAB_DESIGN_2026-11-20.md

先读方案，再核对 git status、当前提交、AGENTS.md 和实际代码。方案基线为 2bf2b1b；
若代码有新改动，保留并基于当前状态实施，不 reset、不覆盖用户工作。
仓库有 .codegraph 时先用 CodeGraph 理解代码；没有就使用 rg，不自行建立索引。

目标：完成 P1–P4，交付独立的本地/授权环境设备注册与激活实验工具。
P5 所需的远端服务地址、测试 appId、契约和请求额度尚未提供，标记 not_run。


范围必须遵守：




实施顺序：
A. 建立配置、夹具、结果模型及输入/端点校验。
B. 建立仅本地监听的 mock-server，提供 capability/register/activate 协议。
C. 实现 client、runner、请求预算、超时终态、报告原子写入和独立 CLI。
D. 编写必要测试，重点覆盖零网络 dry-run、网络范围拒绝、协议错误、幂等/隔离、超时、重定向和预算耗尽。
E. 做一次真实 loopback HTTP 集成实验，输出 local_mock 来源的报告。
F. 核对生产路径没有行为变更，补充使用文档和示例本地配置。

本地协议、配置 schema、成功判定、文件建议和验收矩阵以方案全文为准。
允许合并小模块，但不要省略网络边界、阶段化结果或失败验证。


测试时不要对 tests 全目录执行自动发现，其中包含线上探针。
显式选择：新增设备实验测试，以及现有 test_independent_login.py、test_native_identity.py、
test_checkin_offline.py、test_checkin_profile.py、test_client_metadata.py、test_gateway_body.py。
历史通过数不等于本轮结果；记录当前实际命令、退出码和结果。
测试依赖缺失时先检查已有可用环境；不修改其他项目的依赖或文件。

Windows 文件操作使用同一 shell 的原生命令。不要递归清理用户目录。
如需移动或递归删除临时目录，先验证绝对路径严格位于本实验输出目录；优先保留可复核报告。
长任务空 write_stdin 轮询使用 yield_time_ms >=180000，优先 300000；functions.wait 同样至少 180000。
functions.exec 外层 yield_time_ms 至少比最长嵌套等待多 30000ms。不要为报告仍在运行而频繁轮询。

完成前检查 git diff --check，并确认没有凭据、私钥、原始网络日志进入待提交文件。
不自动提交或推送，不启动生产注册/激活或签到实验。

最终回复给出：
- 改动文件与原因；
- 本地运行命令；
- 当前测试结果与 loopback 报告路径；
- 生产功能的回归结果；
- P5 缺失的技术参数及 not_run 状态。
不要将本地 mock 成功表述成远端服务或生产服务成功。
```
