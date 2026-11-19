# 签到请求参数与原生客户端对齐

> 最新新增 `--native` 配对读取原生 token/远端设备 ID，单次线上验收已签到成功且 verified=true，见
> [原生身份模式](TRAE_CN_CHECKIN_NATIVE_IDENTITY_2026-11-20.md)。旧 `--creds` 命令仍使用独立凭据。

> 后续在用户授权下执行一次 --execute，claim 仍返回 9074。最新剩余差异与原生设备日志
> 对照见 [复核记录](TRAE_CN_CHECKIN_DIFF_2026-11-20.md)。下文“未执行领取”指参数修改与构造验证阶段。

基于本机 Trae CN 3.4.20 的静态源码与 session header 规则实施。
本次修改 `checkin.py`、`client_metadata.py`，新增 `checkin_profile.py`。
未执行线上领取，未修改凭据、Trae 配置或设备注册状态。

## 发送参数

| 参数 | 当前实现 |
|---|---|
| 查询和领取 | POST，保留已确认的两个 `/trae/api/v2/ug/checkin_credits/*` 路径 |
| 请求体 | 明确发送 UTF-8 字节 `{"req_source":1}`，与 JS JSON.stringify 相同 |
| 服务域名 | 读取安装目录 product.json 的 bootConfig.ug.trae.normal；无安装回退 https://api.trae.cn |
| Authorization | 凭据文件对应 token，保留 Cloud-IDE-JWT scheme |
| x-device-id | 保留该凭据的设备 ID，不替换或随机生成 |
| User-Agent | `VSCode <package.json.version> (<product.json.nameShort>)` |
| X-Market-Client-Id | `VSCode <package.json.version>` |
| X-User-Region | CN 产品默认 CN；可用 --user-region 指定实际观察值 |
| x-app-version | 安装产品 appVersion，无法读取安装时回退凭据版本，再回退已审查的 3.4.20 |
| x-device-brand | 当前系统型号优先；保留清洗规则；缺失时回退凭据非自定义名称字段 |
| x-device-type | 当前系统信息，Windows 对应小写 windows，不再沿用旧凭据的 Windows |
| x-os-version | Windows 注册表 ProductName，包含系统版本名称和 edition；本机与 Node os.version() 对照一致 |
| x-rust-request-timeout | 30000 |

安装版本未知时，编辑器 UA 版本回退已审查安装的 1.107.1，客户端名称回退 Trae CN。
`TRAE2API_PRODUCT_JSON` 可以指定另一安装目录中的 product.json，编辑器版本从同目录
package.json 读取。自动解析版本后不再使用 httpx 的默认 Python UA。

## 原生 session 配置

读取 `%APPDATA%/Trae CN/User/settings.json` 的 JSONC 配置：

- `ai_assistant.request.env`、`ai_assistant.request.ppe` 对应环境头；
- `ai_assistant.request.envLane` 对应 x-env-lane；
- telemetry.telemetryLevel / enableTelemetry / enableCrashReporter 控制 marketplace 身份头。

产品 telemetry 未关闭且配置允许 all 时，读取已有的 application storage
`storage.serviceMachineId`，缺失时读取 user-data 目录的 machineid；仅文件回退值要求有效 UUID。
若取得该值，则发送 X-Market-User-Id；VSCode-SessionId 优先复用已有 telemetry.machineId，
缺失时回退同一 serviceMachineId。SQLite 以 mode=ro 打开，只查询两个明确的键。
不会创建新的 native machineid，不解密/替换原生 token。

`TRAE2API_USER_DATA` 可以指定非标准 user-data 目录。缺失原生标识时不伪造它；
原生在这种情况下可能创建标识，这是尚未等价的初始化行为。

## 使用

原命令保持有效，已有旧凭据无需为 UA/OS 修复再次登录：

```powershell
python -m trae2api.checkin --creds .\trae2api\trae2api.json --status-only
python -m trae2api.checkin --creds .\trae2api\trae2api.json --execute
```

有已确认的运行时域名或地区差异时可以覆盖：

```powershell
python -m trae2api.checkin --creds .\trae2api\trae2api.json --status-only --base-url https://api.trae.cn --user-region CN
```

不自动刷新/轮换 token，领取不自动重试，领取被接受后仍查询状态确认。

## 验证与边界

离线测试覆盖已构造 HTTP 请求的最终 UA、两种版本来源、OS/型号、身份保持、
精确 body 字节、环境设置、telemetry 条件、只读标识复用及 CLI 覆盖。
相关回归结果为 **54 passed**；修改模块 compileall 与 git diff --check 通过。
实际凭据的本地构造检查确认：

- UA 为 `VSCode 1.107.1 (Trae CN)`，不存在 Python UA；
- 产品版本 3.4.20，系统字段 windows / Windows 10 Education；
- 本机 OS 字段与 Node os.version() 对照一致；
- 已构建 X-Market-Client-Id、X-User-Region、两个 marketplace 身份头；
- token、设备 ID 保持原值，凭据文件字节未变化；未输出秘密值。

本轮实际执行一次 `--status-only`，返回 `action=status, enable=true,
checked_in=false, credits=100, did_checked_in=false, extra_credits=100`。
这是修改后状态接口的成功响应；没有执行 claim，不能据此认定领取已恢复。

这些检查验证已知应用层参数，不证明领取已成功或 9074 已消失。
以下仍不能宣称与原生完全一致：

- Aha 设备注册、远端 device ID 分配及缓存生命周期；
- Electron session cookie、TLS/HTTP 协议指纹、浏览器自动头、重定向和代理行为；
- 运行时动态 bootConfig、企业策略、命令行 telemetry 禁用及非默认用户 profile；
- reverse-proxy 重定向专用 Trae-Gateway-Target；仅有实际重定向记录才应设置，不能盲加。

当前仍使用 httpx，trust_env=False；参数对齐不代表网络栈等价。地区默认值只针对
当前 CN 产品，迁移账号或不同运行时环境应先观察原生结果，再显式指定。
