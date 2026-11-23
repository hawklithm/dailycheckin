# 本地合成设备验证工具

实现入口：`python -m trae2api.sandbox_lab`。

当前范围：固定合成设备持久化、实验用持久化 P-256 安装密钥、loopback mock 注册/激活、
本地合成账号绑定、签名请求和设备/账号日限测试流水；支持串行预算、默认离线执行与分阶段报告。
真实账号授权/OAuth、线上签到和远端服务适配均未实现/未执行。
完整绑定协议、密钥迁移与本轮验收见 [本地绑定及日限验证](LOCAL_BINDING_QUOTA_2026-11-20.md)。

## 快速运行

在仓库根目录使用已有依赖环境。本机已验证的解释器为
`D:\Users\marcus\anaconda3\python.exe`；仓库自身 `.venv` 当前缺少运行依赖。

```powershell
# 生成并保存固定夹具和 I1/I2 的 P-256 密钥；不联网
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab fixtures

# 默认 dry-run：校验输入、复用持久化档案并写报告，不创建 HTTP 客户端
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab run --config docs/examples/sandbox-device-lab.local.json

# 一次完整本地 HTTP 闭环：临时监听随机 loopback 端口，完成后自动关闭
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab demo

# 本地签名绑定/账号切换/重建安装身份/设备日限完整闭环；服务结束后自动关闭
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab binding-demo

# 仅离线准备 P-256 身份及实验计划；不联网、不重建已有安装身份
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab binding-run --config docs/examples/sandbox-device-lab.binding-local.json
```

也可分别运行服务和客户端：

```powershell
# 终端一；Ctrl+C 关闭
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab mock-server --port 8765

# 终端二；只有 --execute 才发请求
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab run --config docs/examples/sandbox-device-lab.local.json --execute
```

退出码：0=离线准备或本地实验通过，1=协议/网络/业务观察失败，2=配置或存储输入错误，3=预算耗尽。
`demo`、`binding-demo` 是显式本地执行命令，始终连接自己启动的 mock；
普通 `run`、`binding-run` 默认离线，只有 `--execute` 才连接已配置的 loopback mock。

## 持久化模型

所有输出严格位于仓库 `logs/sandbox-device-lab/` 内，已被 Git 忽略。
不允许通过绝对路径、父目录跳转、符号链接或 junction 将输出重定向到目录之外。

- `profiles/*.fixture.json`：固定夹具、schema、synthetic 标记和内容摘要。
- `profiles/*.installation.json`：schema v2 安装公共信息、machine ID、公钥及公钥指纹。
- `profiles/*.p256.secret`：按公钥指纹命名的不可变实验私钥版本；未加密 PKCS#8，禁止分享。
- `profiles/history/*.json`：旧标签迁移或身份重建时保留的公共信息快照。
- `reports/lab-experiment-*.json`：每次实验独立的原子写入报告。

固定夹具：

| 夹具 | 含义 | 默认 run |
|---|---|---|
| fixture-a | H1 基准合成设备 | 包含 |
| fixture-a-display | H1 的展示描述变化；同一 mock 物理分组 | 可替换另一个有效夹具 |
| fixture-b | H2 独立合成设备 | 包含 |
| fixture-invalid | model 字段类型错误的负例 | 包含；本地拒绝，不发送 |

这些描述使用 `lab-physical-*` 标记，不读取或生成可直接发送到生产注册接口的完整硬件指纹。
I1/I2 现在使用真实 P-256 密钥，只用于带有 `local-device-lab-proof-v1` 前缀的本地协议签名。
旧 schema v1 标签会保留 machine/key 标签并迁移到 v2；损坏私钥不会静默重建。
基本注册协议不提交 I1/I2 密钥；新增本地绑定协议才登记公钥，不能把密钥不同当成不同物理设备。

同一目录重复运行会复用夹具及安装密钥；文件损坏或与固定定义不符时停止，不静默覆盖。
`binding-demo` 明确包含一次 H1/I2 重建用例，因此会生成新 machine ID 和密钥，旧版本保留。
不同实验使用不同 experiment_id。mock 注册状态仅在服务进程内存保存，退出后失效；
旧报告不能作为新进程激活身份的恢复缓存。

## 网络及协议范围

本轮按照用户要求只实现本地能力，比最初设计中的私网沙箱范围更窄：

- 仅接受 `http://127.0.0.1:<显式端口>`；不支持 DNS、其他 loopback 写法、私网或公网。
- appId 固定为 `local-device-lab`，CIDR 必须包含目标且完全落入 127.0.0.0/8。
- 不接受凭据、token、代理、自定义请求头或任意路径配置。
- `trust_env=False`，不跟随重定向，无自动重试。
- capability 明确声明无奖励、sandbox 与版本兼容后，才允许注册/激活。
- 基本协议路径为 `/lab/capabilities`、`/lab/register`、`/lab/activate`。
- 绑定场景另提供 `/lab/binding-challenge`、`/lab/bind` 和
  `/lab/checkin/status`、`/lab/checkin/claim`、`/lab/checkin/ledger`，仅合成账号与内存测试流水。
  不提供真实 OAuth 或生产签到路由；扩展 capability 需额外声明本地绑定和测试流水能力。

同一 experiment/app/fixture_digest 重放返回相同 mock device/install ID；不同有效夹具返回不同注册 ID。
mock 另返回 `sandbox_physical_id`：fixture-a 与 fixture-a-display 共享一个分组，fixture-b 使用另一分组。
它是本地参考模型的预设契约，不能推断真实服务的去重算法。

默认执行顺序：capability → A 注册 → A 激活 → A 注册重放 → B 注册 → B 激活，共 6 次。
基本注册场景最大预算为 8 次；绑定场景最大 32 次、正常完整运行 31 次，另有 6 次测试领取上限。
失败和超时也计入；非预期失败即停止后续网络操作，预期的账号/设备日限拒绝作为测试结果记录。
超时记录 outcome_unknown，不重试、不激活结果未知的注册。
业务拒绝、错误字段类型、缺少或非法 lab-ID 均不判成功。

## 报告含义

dry-run 来源为 `offline_fixture`，请求数为 0，注册与激活均为 `not_run`。
本地 HTTP 来源为 `local_mock`；即使全部通过，也只能说明本地协议与实验工具工作正常。

基本注册报告保留 `account_binding=not_run`；绑定场景报告区分本地与真实账号：

```json
{
  "local_account_binding": "passed",
  "local_device_quota": "passed",
  "real_account_binding": "not_run",
  "online_checkin": "not_run",
  "provider_test": "not_run"
}
```

报告只记录固定错误标签、状态码、耗时及布尔关系，不保存原始响应体、HTTP 认证头或任何 token。
绑定报告也不输出私钥、公钥全文、签名、挑战或 mock session token。
远端服务方契约、测试账号、奖励隔离和后端审计途径仍未提供；本实现没有远端 adapter。

## 第一版本验收（历史）

2026-11-20 执行以下显式选择的离线测试；没有对整个 tests 目录自动发现：

```powershell
& 'D:\Users\marcus\anaconda3\python.exe' -m pytest tests/test_sandbox_lab_config.py tests/test_sandbox_lab_client.py tests/test_sandbox_lab_runner.py tests/test_independent_login.py tests/test_native_identity.py tests/test_checkin_offline.py tests/test_checkin_profile.py tests/test_client_metadata.py tests/test_gateway_body.py tests/test_device_identity_offline.py -q
```

结果：**181 passed in 6.46s，exit code 0**。其中新增实验工具 95 项，既有离线回归 86 项。
覆盖网络范围、配置类型、文件逃逸、档案损坏、原子写入失败、重定向、协议错误、
幂等/隔离、超时、预算耗尽、零网络 dry-run、生产模块导入隔离及真实 loopback HTTP。

独立 CLI loopback 验收：

```powershell
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab demo --output-directory logs/sandbox-device-lab/acceptance-20261120
```

结果：exit code 0，source_kind=local_mock，completion_status=passed，6 次 HTTP 请求。
两个有效夹具均注册/激活成功，A 重放稳定，负例未发送。

报告：`logs/sandbox-device-lab/acceptance-20261120/reports/lab-experiment-bd066a03d5c149f5b7b142757e6a7d13.json`。

本轮没有修改生产登录、硬件读取、凭据、注册或签到模块；工作区中此前已有的签到修正保留。
未提交、推送，也未开展真实账号绑定、线上签到或服务方沙箱验证。

## P-256 与本地绑定扩展验收

最新结果为 **221 passed in 11.18s，exit code 0**，包含新增绑定/密钥测试、已有本地实验测试及生产离线回归。
本地 CLI 绑定验收为 **31 次请求、6 次测试领取尝试，H1/H2 各一笔内存流水**。
详细命令、用例结果和报告路径见 [扩展验收记录](LOCAL_BINDING_QUOTA_2026-11-20.md)。
