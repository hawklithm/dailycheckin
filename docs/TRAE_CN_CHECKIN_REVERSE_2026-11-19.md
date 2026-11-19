# Trae CN 签到逆向与离线实现

## 证据范围

静态分析本机 `D:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app`：

- `product.json` SHA-256 `c1cb3a485464a0dcf2fb5e0361d49504ab2d6a70a3522b8b531e7f9db3408ccf`；`bootConfig.ug.trae.normal` 为 `https://api.trae.cn`。
- `out/main.js` SHA-256 `433e32bd7821ab4b05e46be1fc1b74043315884ba3ec58c45c99d94f58fd6816`；字符偏移基于 UTF-8 解码字符串。`package.json` 的 `version` 为 VS Code 基础版本 `1.107.1`，不能直接当作 Trae 产品版本。
- 分析没有操作账号、没有发送网络请求。客户端更新后必须重新核对这些结论。

## 签到调用链与请求

`main.js` 偏移约 1985760 处，主进程注册状态和领取的 IPC；约 1991012 处 `mb` 负责调用，1992603 和 1992999 分别为 `fetchCheckinCreditsStatus` 与 `claimCheckinCredits`。通过 `ugApi` 选择主机：

| 用途 | 方法与路径 | JSON 请求体 |
|---|---|---|
| 查询 | `POST /trae/api/v2/ug/checkin_credits/status` | `{"req_source":1}` |
| 领取 | `POST /trae/api/v2/ug/checkin_credits/claim` | `{"req_source":1}` |

这里 1 对应 IDE，客户端对于另一产品分支使用 2。认证由 `mixAuthorization`（约 1987981）设置为 `Authorization: Cloud-IDE-JWT <当前登录 token>`。还设置 `Content-Type: application/json` 和 `x-device-id`，可选 `x-device-brand`、`x-device-type`、`x-os-version`、`x-app-version`（约 1994005）。底层网络栈可能附加其他头，当前证据不能确定其全部 wire 形式及服务端必要性。

状态响应客户端检查 `enable`、`checked_in` 为布尔值；若存在 `code` 则其须为数字且为 0。领取成功判定为 HTTP 200、JSON 对象且若存在 `code` 则为数字 0；这仅是客户端接受结果，不证明积分已到账。客户端同账号、同北京日的并发领取复用同一 promise；并发完成之后不保证幂等。客户端领取后可能附带独立的活动抽奖，当前实现不触发抽奖。

本地 `D:\workspace\qoder-trae-workbuddy-switch\crates\buddy-switch-core\src\modules\trae\checkin.rs` 及 `credits.rs` 也实现类似接口，但发 `{}`，与当前 Trae 客户端的 `req_source` 有差异；其头及账号设备分配属于参考实现，不作为 Trae 真实行为或线上有效性的证明。

## 设备识别的证据和未知项

`main.js` 约 1294797–1297000：`guaranteedDeviceId` 优先使用设备注册服务中的 ID，否则使用 `localDeviceId`；该服务从 Electron 的 `ahaDeviceService.deviceId` 取得初值，再调用 `ahaDeviceService.getDeviceId(...)` 异步获取 ID，并处理旧存储项迁移。签到路径把此 ID 放入 `x-device-id`。这说明它是签到请求携带的设备标识，**不证明**服务端仅凭它判定设备，也不能证明任意自造 ID 已注册或者能通过风控。

所检索的客户端 JS 中没有 `geelab` 字面量；这不排除 Electron 原生组件、其他名称的 SDK、远程配置或服务端有更多设备指纹。注册算法、持久化与网络交互未闭合，无法确认是不是 GeeLab 或其等价物。`machineId`、登录设备公私钥及 `DeviceProof` 存在于项目的 OAuth 逆向材料，但不能据此断言它们参与本签到接口。

当前实现要求凭据文件提供该账号对应的 `device.deviceId`，不生成或轮换设备标识，不声称可模拟完整设备。凭据文件中的 `deviceId` 应与对应登录流程一致；项目历史登录代码生成的 ID 未证明等价于 Aha 注册 ID。每账号可传入自己的凭据文件，但不能证明每账号单独 ID 会改变服务端限制。

## 使用与边界

代码 `trae2api/checkin.py` 是独立入口，默认空运行，不读取凭据、不联网：

```powershell
python -m trae2api.checkin --creds C:\path\account.json
```

后续用户自行决定进行线上验证时，显式加 `--execute`：

```powershell
python -m trae2api.checkin --creds C:\path\account.json --execute
```

接受项目的 `auth.token`（缺失时 `auth.jwt`）和 `device.deviceId`，可选设备字段复用现有文件格式；不会主动刷新 token 或轮换 refresh token。每账号执行一次命令即可。先查询状态；已签到或未启用则不提交；状态不明确、鉴权或网络异常直接停止。领取没有自动重试：超时可能已经被服务器处理，后续操作应先查状态。输出的 `claim_accepted` 是客户端协议层接受，奖励到账仍需后续实测确认。此实现尚未用真实账号或真实上游验证。

离线测试：`python -m pytest tests/test_checkin_offline.py -q`。mock 传输仅验证本地行为，不能证明远端接受所生成的请求。
