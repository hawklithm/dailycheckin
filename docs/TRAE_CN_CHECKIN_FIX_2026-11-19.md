# Trae CN 签到客户端差异修复记录

> 2026-11-20 已继续补齐 UA、OS 及 session header，最新实现与边界见
> [对齐记录](TRAE_CN_CHECKIN_ALIGNMENT_2026-11-20.md)。本文件保留上一轮修复快照。

基于 `TRAE_CN_CHECKIN_CALL_CHAIN_2026-11-19.md` 的本地 3.4.20 静态证据实施。
该逆向报告的差异表记录修复前基线；本文件记录修复后的实现。

## 已完成

- 新增 `client_metadata.py`：从安装目录 product.json 读取 **appVersion**，不使用编辑器 version。
  支持 `TRAE2API_PRODUCT_JSON` 指定非标准安装路径；无可读安装时使用调用方的版本回退值。
- Windows 系统型号读取 BIOS 注册表的 SystemProductName，按原生 HF 过滤控制字符。
  这是本机实际型号来源，但尚无动态证据证明它在所有设备上与 Aha 的 deviceModel 完全相同。
- 登录 URL、ExchangeToken、GetUserInfo 和 DeviceInfo 使用同一个解析后的客户端版本。
  新登录把用户自定义设备名称保留在 DeviceName，型号/brand 使用系统型号。
- TraeAuth 保存并加载 device.clientVersion，解决版本字段丢失。
- 签到读取旧凭据时在内存补齐版本和缺失的系统信息；旧 login 把设备名称同时存为型号时，
  改为读取当前系统型号。凭据文件不会被重写，token、设备 ID 和私钥不会被替换。
- 签到请求增加 `x-rust-request-timeout: 30000`；已有的版本、型号、OS 请求头补齐。
- status-only 保留可选 did_checked_in、extra_credits。did_checked_in=true 时不再领取。
  可选 did_checked_in 出现但类型错误时保守停止，避免误领取。
- 领取被接受后再查询一次签到状态；确认 checked_in 或 did_checked_in 为 true 时输出
  `action=checked_in, verified=true`。
- 领取被接受但确认未完成时输出 `action=claim_accepted, verified=false`；若确认失败，
  携带 verification_error。领取请求不会因为确认失败、超时或未立即反映状态而重发。
  verified 仅确认签到状态，不证明积分余额实际增加；credits 字段沿用签到状态的配置值。
- 领取业务错误仍如实返回，不把 9074 视为成功，不自动重试。

## 验证

运行：

```powershell
python -m pytest tests/test_checkin_offline.py tests/test_client_metadata.py tests/test_gateway_body.py -q
```

结果：**36 passed**。执行时复用本机已有测试依赖路径，没有修改另一项目。
验证包含请求序列/请求体/超时 header、did_checked_in gate、领取拒绝阶段、领取后确认、
确认网络超时不重发、旧凭据读取不改文件、产品版本解析、凭据版本往返、登录各处版本一致，
以及既有聊天请求 body 的 6 项回归。

对现有账号文件的本地只读检查确认：版本解析为 3.4.20，系统型号非空，8 个预期请求头均已构建。
未输出 token、设备 ID 或私钥。

尝试真实 `--status-only` 时当前执行环境返回 ConnectError，未成功取得服务端响应，
因此没有执行后续领取，也没有真实签到成功或 9074 消失的证据。

## 运行

已有有效凭据可直接重试，无需为元数据修复再次登录：

```powershell
python -m trae2api.checkin --creds .\trae2api\trae2api.json --execute
```

只查询：

```powershell
python -m trae2api.checkin --creds .\trae2api\trae2api.json --status-only
```

## 尚未闭合

- 凭据里的设备 ID 仍然使用对应登录时的原值。Aha 原生设备注册尚未完整实现；
  当前独立登录生成设备 ID 的流程不等同于 Aha 注册。本补丁没有更换身份或声称注册成功。
- httpx 与 Electron net.fetch 的原生 session、User-Agent、代理、TLS 及内部网络处理差异仍存在。
  本补丁对齐已证实的 JS 请求字段，不声称网络报文已完全等价。
- 未发现 9074 服务端触发条件的可靠证据，仍需同账号原生客户端的动态对照。
