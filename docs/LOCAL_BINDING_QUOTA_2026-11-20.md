# 本地 P-256 账号绑定与设备日限验证

日期：2026-11-20。来源：`local_mock`。本轮只连接 `127.0.0.1`，未使用真实账号或线上服务。

## 运行

```powershell
# 一次完整本地闭环；随机本机端口，完成后关闭服务
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab binding-demo --output-directory logs/sandbox-device-lab/binding-acceptance-20261120

# 仅生成/复用密钥并写离线实验计划：零请求，不旋转已有密钥
& 'D:\Users\marcus\anaconda3\python.exe' -m trae2api.sandbox_lab binding-run --config docs/examples/sandbox-device-lab.binding-local.json
```

长期手动运行时可使用现有 `mock-server --port 8765`，再执行同一 `binding-run` 命令并加 `--execute`。
默认不联网。配置 `scenario=binding_quota` 才允许扩展协议与最多 32 次请求；原注册场景仍限制为 8 次。
全部请求仍受固定 loopback URL、显式 CIDR、禁止代理继承与禁止重定向的边界约束。

## 密钥持久化与重建

安装公共档案升级为 schema v2，记录独立 machine ID、P-256 公钥和 SPKI SHA-256 指纹。
私钥为未加密 PKCS#8，存于实验根目录内按指纹命名的 `.p256.secret` 文件，不进入报告或 Git。
文件通过私密临时文件写入；先发布不可变密钥版本，再原子替换公共档案。

- 重新加载同一安装身份时复用密钥；验证曲线必须是 P-256、公私钥匹配、指纹一致。
- 缺失、损坏或错误曲线的私钥会使加载失败，不重新生成来掩盖损坏。
- 旧 v1 标签迁移时保留 machine/key 标签，旧公共档案存入 history，另生成真实 P-256 密钥。
- 显式重建会生成新 machine ID 和密钥，物理夹具保持不变；旧档案及旧私钥版本保留。
- 公共档案切换失败时，旧公共档案仍指向旧有效私钥；可能遗留未引用的新版本，但不删除用户文件。

这些是本地实验身份，不是硬件背书或真实服务认可的设备凭据。

## 本地账号绑定协议

mock 只认识 `lab-account-a`、`lab-account-b` 两个合成别名，无密码、真实 token 或浏览器 OAuth。
账号别名是测试输入；设备密钥证明不等于证明现实中的账号所有权。

1. 注册并激活固定夹具，获得实验内 device/install ID。
2. `/lab/binding-challenge` 登记合成账号、注册身份、machine ID、公钥与指纹。
3. 服务端检查激活与实验归属，生成绑定上下文的挑战，60 秒有效、只可使用一次。
4. 客户端用持久化私钥签名；`/lab/bind` 使用挑战中存储的公钥验签，签发仅内存保存的 mock session。
5. 已登记的同一 device ID/machine ID 不能被另一公钥覆盖；绑定提交时再次检查，覆盖并发登记竞态。

签名带有专用域前缀、请求方法、路径及规范 JSON 内容，不能当作生产 DeviceProof 使用。
session 绑定实验、app、账号、注册设备与安装公钥，600 秒过期。

后续状态、领取和测试流水查询均签名，包含 session、账号、设备、时间戳与唯一 nonce。
服务端从已登记 session 选取公钥；拒绝错配账号/设备、错误私钥、签名篡改、跨路径签名、
时间偏差超过 60 秒、过期 session 和已使用 nonce。

## 日限与账本

服务端根据注册记录取得 mock 物理分组，不以受保护请求中自行声明的新字段替换它：

- fixture-a 与 fixture-a-display：同属 H1，但注册 ID 不同。
- fixture-b：独立的 H2。

约束键分别为：

```text
设备日限：(experiment_id, app_id, mock_physical_id, 北京业务日期)
账号日限：(experiment_id, app_id, synthetic_account_id, 北京业务日期)
```

检查两个限额键、登记两个唯一键、追加测试流水在同一服务端锁内完成。
同一账号或设备达到日限时返回拒绝，客户端仍实际提交该测试领取以检验服务端 gate。
测试单位仅为 `test_units=1` 的内存记录，capability 始终声明 `rewards_enabled=false`。

实验之间故意隔离；新 experiment_id 或 mock 服务重启会获得新的实验状态。
这不是“跨实验重置真实设备日限”的证据，也不能证明真实服务能识别合成物理设备。
物理分组是本地参考模型中预设的夹具关系。

## 本轮 CLI 验收结果

2026-11-20 12:29（UTC+8）运行上述 `binding-demo` 命令，exit code 0。
总计 **31 次 HTTP 请求、6 次测试领取尝试**，未超过 32/6 的本地上限。

| 用例 | 控制条件 | 结果 |
|---|---|---|
| A 在 H1/I1 首次领取 | 初始基线 | 接受，H1 流水 1 笔 |
| 同一安装切换为 B | device ID、machine ID、密钥均不变 | device_daily_limit，无新增流水 |
| B 使用重建的 I2 | 保持 H1 和原 device ID；新 machine ID、新 P-256 密钥 | device_daily_limit，无新增流水 |
| B 换用 H1 的另一注册记录 | 账号及重建后的安装密钥不变；注册 ID 改变 | device_daily_limit，无新增流水 |
| A 再次领取 | 新 nonce，仍为同账号/同设备 | account_daily_limit，无新增流水 |
| B 在 H2 首次领取 | 独立物理分组对照；B 此前从未成功领取 | 接受，H2 流水 1 笔 |

最终从签名审计接口确认 **总流水 2 笔，H1/H2 各 1 笔**，账号和设备日限符合预设参考策略。

报告：
`logs/sandbox-device-lab/binding-acceptance-20261120/reports/lab-experiment-007892350aa34c75b84650e0f4bca2c7.json`。

另运行 `binding-run` 默认离线入口，确认 requests_sent=0、claim_attempts=0，各本地网络阶段为 not_run。
实际执行 fixtures 命令，对首版本本地标签档案完成迁移；没有读取原生账号凭据。

## 测试

```powershell
& 'D:\Users\marcus\anaconda3\python.exe' -m pytest tests/test_sandbox_lab_config.py tests/test_sandbox_lab_client.py tests/test_sandbox_lab_runner.py tests/test_sandbox_lab_binding.py tests/test_independent_login.py tests/test_native_identity.py tests/test_checkin_offline.py tests/test_checkin_profile.py tests/test_client_metadata.py tests/test_gateway_body.py tests/test_device_identity_offline.py -q
```

本轮结果：**221 passed in 11.18s，exit code 0**。

覆盖跨进程密钥复用、旧档案迁移、原子切换失败、私钥损坏/不匹配、P-256 曲线校验、
挑战一次性/过期、会话过期、请求重放/篡改/错配、登记公钥竞争、服务端原子日限、北京时间跨日、
各请求阶段重定向拒绝、领取已提交后的网络超时不重试、预算耗尽、报告脱敏、真实 loopback HTTP，
以及既有登录/签到/网关离线回归。

本轮未修改生产认证、设备注册、硬件读取或签到模块；未提交、推送。
报告明确记录 `real_account_binding=not_run`、`online_checkin=not_run`、`provider_test=not_run`。
