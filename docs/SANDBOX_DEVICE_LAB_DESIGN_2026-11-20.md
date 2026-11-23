# 沙箱设备注册与激活实验改造方案

日期：2026-11-20

状态：设计稿，尚未实现。基线提交：`2bf2b1b`。

> 后续实现状态（2026-11-20）：本地 P1–P4 已实现并通过 loopback 验证；
> 网络范围按本轮指令收窄为固定 127.0.0.1 mock，不支持远端私网 adapter。
> P5、真实账号绑定和线上签到仍为 not_run。下文保留原始设计，当前行为见
> [本地工具使用说明](SANDBOX_DEVICE_LAB_USAGE.md)。

## 1. 目标与实验范围

实现一个独立、可重复的设备注册兼容性实验工具，在本地模拟服务或服务方提供的测试端点中，
验证合成设备夹具的输入校验、注册响应、激活确认、重复提交及配置隔离行为。

本方案不包含生产环境设备身份伪造、真实账号 OAuth、签到接口、奖励领取或设备日限规避。
结果只能说明特定测试服务对测试输入的处理，不能推出生产签到资格。

交付两种能力：

1. **本地完整闭环**：自建模拟服务、固定合成夹具、注册/激活客户端、实验报告和自动化测试。
2. **真实沙箱适配接口**：显式配置的服务方测试端点、测试 appId、请求上限和字段映射。
   当前尚未取得这些参数，不能替代为项目已有的生产常量。

## 2. 现状与可复用内容

| 文件 | 当前职责 | 本轮处理 |
|---|---|---|
| `trae2api/aha_registration.py` | 真实硬件注册/激活，内含生产地址 | 保持原样；实验网络客户端不得调用其 register/activate |
| `trae2api/device_hardware.py` | 读取真实 UUID、磁盘、MAC 等 | 实验路径不导入、不调用 |
| `trae2api/login_identity.py` | 独立登录设备 ID、密钥及缓存 | 不复用其存储目录、配置格式或迁移逻辑 |
| `trae2api/login.py` | 独立设备准备与真实 OAuth | 保持原样；不作为实验入口 |
| `trae2api/native_identity.py` | 读取原生登录及设备证据 | 不导入、不调用 |
| `trae2api/checkin.py` | 真实签到 | 不接入实验工具 |
| `trae2api/device_identity.py` | 离线虚拟 UUID 候选生成 | 保持离线性质；不升级为生产注册器 |
| `tests/test_independent_login.py` | 现有注册/OAuth mock 回归 | 保留，作为回归项 |

已有事实见 `docs/INDEPENDENT_LOGIN_2026-11-20.md`：真实硬件的独立注册和激活成功；
新版独立 OAuth/签到仍未做真实完整验收。此前 129 项测试和 12 项子测试是历史基线，
执行 agent 必须检查当前结果，不能直接将历史数字写成新验证结果。

## 3. 架构与目录

新增隔离包 `trae2api/sandbox_lab/`，不修改现有生产命令的行为。

```text
trae2api/sandbox_lab/
  __init__.py
  __main__.py          # 独立 CLI
  config.py            # 实验配置与端点校验
  fixtures.py          # 有限、固定的合成输入，不读取真机信息
  client.py            # 仅沙箱注册/激活客户端
  runner.py            # 请求预算、执行顺序、停止条件
  report.py            # 分阶段结果、错误分类与报告写入
  mock_server.py       # 仅本地监听的参考服务
tests/
  test_sandbox_lab_config.py
  test_sandbox_lab_client.py
  test_sandbox_lab_runner.py
docs/
  SANDBOX_DEVICE_LAB_USAGE.md
```

可以按复杂度合并小文件，但端点校验、网络调用和结果判定应有清晰边界。
不为本功能引入数据库、后台守护进程、任务调度或前端。

## 4. 数据模型

### ExperimentConfig

必需字段：schema_version、environment=sandbox、app_id、base_url、allowed_cidrs、
max_requests、timeout_seconds、fixture_ids、output_directory。

固定路径：`/lab/capabilities`、`/lab/register`、`/lab/activate`。
v1 不接受任意完整 URL、任意路径、代理配置或生产凭据路径。

示例仅用于本地模拟服务：

```json
{
  "schema_version": 1,
  "environment": "sandbox",
  "app_id": "local-device-lab",
  "base_url": "http://127.0.0.1:8765",
  "allowed_cidrs": ["127.0.0.0/8"],
  "max_requests": 8,
  "timeout_seconds": 10,
  "fixture_ids": ["fixture-a", "fixture-b"],
  "output_directory": "logs/sandbox-device-lab"
}
```

服务方沙箱 appId 必须由服务方提供，不使用生产 appId 作为缺省值。
如测试端点只支持另一套路径或协议，新增有测试覆盖的沙箱 adapter；不得猜路径。

### DeviceFixture

包含 fixture_id、schema_version、case_description、attributes 和 fixture_digest。
attributes 是本地协议中的合成设备描述；夹具固定、有限、显式标记 synthetic=true。
v1 不生成可投递生产的硬件指纹，不替换 OS 或原生客户端的设备信息。

提供三类夹具：基准有效夹具、不同描述的有效夹具、类型错误夹具。
相同夹具重复读取必须一致；禁止依赖当前真机硬件、原生账号或真实设备缓存。
无须生成私钥，也不需要真实账号到设备的映射。

### ExperimentReport

顶层字段：experiment_id、started_at、finished_at、source_kind、config_digest、
request_budget、requests_sent、fixture_results、completion_status。

每个结果记录 validation、registration、activation 三个阶段；每阶段使用
not_run / accepted / rejected / protocol_error / network_error / budget_exhausted。

记录 HTTP 状态、耗时、字段类型校验、固定错误标签；不保存原始响应体、认证头或 token。
沙箱返回的 ID 仅保留在实验运行上下文及受隔离的实验记录中，不能写入生产凭据文件。
不把 mock 服务的成功标记为真实沙箱成功。

## 5. 本地协议与参考服务

本地协议与生产 Aha 协议解耦，避免把测试工具变成生产注册入口。

- GET `/lab/capabilities` 返回 service=device-registration-lab、protocol_version=1、
  environment=sandbox、rewards_enabled=false、supported_fixture_schema=1。
- POST `/lab/register` 接收 experiment_id、fixture_id、app_id 和合成 attributes；
  返回 accepted、sandbox_device_id、sandbox_install_id。ID 必须有 `lab-` 前缀。
- POST `/lab/activate` 接收当前实验已获得的沙箱 ID，返回 accepted、activated。
- 使用进程内存保存实验状态；退出即失效。不得读取注册机、硬件、Trae 存储或浏览器数据。

注册成功要求 HTTP 200、响应对象类型正确、accepted 严格为 true、两个 ID 为非空 lab- 字符串。
激活成功要求 HTTP 200、accepted=true、activated=true，且 ID 属于本次实验。
错误类型不得用 truthiness 将字符串 "true"、数字或空对象误判为成功。

同一 experiment_id/fixture_digest 重复注册在 mock 服务中应返回相同 ID；不同有效夹具
返回不同 mock ID。这只是参考服务的幂等契约，不代表生产服务的去重规则。

远程沙箱 adapter 只有获得服务方契约后才能定义相应判断，不能沿用 mock 的预期代替观察。

## 6. 端点与网络边界

1. 默认 dry-run，不创建网络客户端；只有显式 `--execute` 才发送请求。
2. v1 仅接受 IP 字面量端点：本机 loopback，或配置允许的 RFC1918 私网/IPv6 ULA 地址。
   不使用 DNS，避免通过域名解析或重绑定绕过实验网络范围。
3. 请求目标 IP 必须落入显式 allowed_cidrs；拒绝公共地址、链路本地、元数据地址、
   多播、未指定地址和任意范围 CIDR；私网使用 HTTPS，loopback 可用 HTTP。
4. 拒绝 URL 用户名/密码、query、fragment、非根路径和非法端口。
5. 不接受生产 host 或生产注册路径；不存在“未配置时使用现有生产常量”的分支。
6. `httpx.Client(trust_env=False, follow_redirects=False)`，TLS 正常校验，不提供关闭校验开关。
7. capability 握手符合第 5 节契约后才允许 POST；配置字符串 sandbox=true 本身不构成握手成功。
8. 远程测试认证如有需要，从指定环境变量读取测试 token；缺失时停止，不读取现有登录凭据。
   不将 token 写入配置、日志或报告；不允许调用方任意覆盖 Host/Authorization 等保留头。

若服务方仅提供公共域名沙箱，当前 v1 不自动放宽网络限制。应另行取得明确的沙箱契约，
设计专用 adapter 和固定目标校验；这不是执行 agent 本轮需要临时扩展的功能。

## 7. 执行、预算与恢复

默认最多两个有效夹具，总 HTTP 请求硬上限 8；硬上限包含 capability GET、失败和超时的尝试。
不使用并发，不自动重试。一个注册结果不明时，不继续为该夹具激活。

默认本地场景：capability 一次，A 注册/激活，A 重放注册一次，B 注册/激活；
类型错误夹具在本地校验阶段拒绝，不发送。共最多 6 次 HTTP 请求。

状态机：draft → validated → registration_accepted → activation_confirmed。
失败进入对应终态；预算耗尽后不再创建请求。超时记为结果未知，不补发注册。

报告先写临时文件再原子替换。实验输出路径限定在明确的实验根目录，禁止路径穿越。
不写 `trae2api.json`、`.device.secret`、原生 user-data 或现有生产注册缓存。
v1 不跨进程恢复远端注册；重新执行使用新 experiment_id，报告必须保留各次来源和请求数。

## 8. CLI 草案

```powershell
# 本地参考服务，默认仅监听 loopback
python -m trae2api.sandbox_lab mock-server --port 8765

# 离线配置与夹具检查；不联网
python -m trae2api.sandbox_lab run --config .\lab-config.json

# 显式执行本地实验
python -m trae2api.sandbox_lab run --config .\lab-config.json --execute
```

dry-run 输出计划步骤和预算，不输出 token，不产生注册成功记录。
退出码建议：0=本次目标通过，1=实验观察失败，2=配置/输入错误，3=预算终止。
远程参数缺失时仍完成本地功能与测试，远程验收标记 not_run，并列出缺失技术参数。

## 9. 实施阶段

| 阶段 | 交付物 | 验收 |
|---|---|---|
| P1 配置/模型 | config、fixture、report 定义 | malformed 输入与目标 IP 校验测试通过 |
| P2 本地参考服务 | capability/register/activate | 有效、无效、幂等、隔离行为有集成测试 |
| P3 客户端与执行器 | 串行预算、状态机、dry-run、CLI | 超时、重定向、预算耗尽不再发送 |
| P4 本地闭环 | 真实 loopback HTTP 实验与报告 | 两个夹具和重放测试完成，报告来源为 local_mock |
| P5 外部沙箱适配 | 服务方端点、appId、契约、请求额度 | 当前缺失，必须 not_run；不得用生产服务替代 |

P1–P4 可立即由执行 agent 完成。P5 的缺失不妨碍交付完整的本地实验工具，
但最终报告必须明确外部沙箱尚未验收。

## 10. 必需测试

- 默认 dry-run 的网络调用次数严格为零。
- 公网、链路本地、非法 URL、宽泛 CIDR、重定向、握手不符均在 POST 前停止。
- 两个固定夹具独立，同一夹具重放稳定；无效夹具不发送。
- HTTP 200 但业务拒绝、缺少 ID、错误字段类型均不误判成功。
- 注册超时不重试、不激活；激活超时不重发注册；预算耗尽没有后续请求。
- 报告不含测试 token，不与生产身份或文件格式混用。
- 真实 loopback 集成测试走完协议，不只使用 MockTransport。
- 保持现有 independent login / native identity / checkin / gateway body 回归通过。

不要运行整个 tests 目录的自动发现：其中包含线上探针和真实工具执行脚本。
显式选择离线测试文件。优先使用当前已有依赖，不修改其他项目环境。

## 11. 完成标准与交付

执行 agent 交付：源码、必要测试、示例本地配置、使用说明、一次本地闭环报告、
回归命令及结果、生产路径无改动的 diff 检查。

最终结论分开写：本地实现完成、本地实验结果、外部沙箱是否执行、尚未验证的事项。
不得写“已突破设备限制”“已证明多账号签到可行”或用 mock 成功替代生产/真实沙箱证据。
没有新的明确指令时，不提交、不推送，也不开展生产测试。
