# Windows Trae CN 3.4.20 签到调用链复核

> 2026-11-20 已从原生界面 tooltip 确认 `checked_in` 的账号语义及
> `did_checked_in=true, checked_in=false` 的设备限制语义，见
> [字段复核与修正](TRAE_CN_CHECKIN_FIELD_SEMANTICS_2026-11-20.md)。

> 2026-11-20 已实施后续 UA、OS 和 session 请求头参数对齐，见
> [对齐记录](TRAE_CN_CHECKIN_ALIGNMENT_2026-11-20.md)。下方差异表保留 11 月 19 日分析基线；
> 不应用其中“缺少 UA/地区头”等描述判断最新代码。设备注册和网络层验收仍未完成。

## 取证范围

2026-11-19 直接读取当前安装目录：
`D:\Users\marcus\AppData\Local\Programs\Trae CN\resources\app`。
`product.json.appVersion=3.4.20`；`package.json.version=1.107.1` 是编辑器基础版本。
本报告是静态代码取证，不是网络抓包，也未执行签到或修改 Trae 安装、账号凭据。

| 文件 | SHA-256 |
|---|---|
| product.json | c1cb3a485464a0dcf2fb5e0361d49504ab2d6a70a3522b8b531e7f9db3408ccf |
| out/main.js | 433e32bd7821ab4b05e46be1fc1b74043315884ba3ec58c45c99d94f58fd6816 |
| out/vs/workbench/workbench.desktop.main.js | ef45a1c374921209589a69ce36bcda89855f569a2ac15e04f92996d8c1101edc |

原始片段、精确位置见同目录 `TRAE_CN_CHECKIN_STATIC_EVIDENCE_2026-11-19.json`。
位置均为 UTF-8 解码后 Python 字符串的零起始字符索引，不是文件字节偏移。

同日补充复核：重新计算上述三个文件的 SHA-256，均与本报告一致；原有 13 个
取证片段逐一与安装原件核对通过。新增 17 个片段保存在
`TRAE_CN_CHECKIN_ADDITIONAL_STATIC_EVIDENCE_2026-11-19.json`，覆盖系统信息来源、
session 请求拦截器及网络发送边界。下方差异表已按当前工作区代码更新。

## 1. 从界面到主进程

1. 命令 `workbench.action.icubeClaimCheckinCredits` 调用 entitlement service 的
   `claimIdeCheckinCredits(source)`。
2. 界面要求环境可用、状态已加载、`enable === true`、`checkedIn === false`、
   `didCheckedIn !== true`、没有缓存的 `businessFailure`；已有领取请求时复用 promise。
3. `claimCheckinCredits(source)` 通过 Electron IPC 调用
   `vscode:sandbox::main-invoke-claimCheckinCredits`。
4. 主进程 handler 接收 source。只有有效窗口且来源属于
   `account_menu`、`banner_popup`、`sidebar_banner` 时，构建抽奖上下文。
   其他来源仍会调用领取；来源不是领取 HTTP 请求的参数或签名。
5. 主进程 `claimCheckinCredits(context, owner)` 按当前账号、generation、北京时间日期
   合并进行中的领取请求，调用共享请求函数 `mb(...)`。

证据：workbench `13628366`、`13633559` 附近；main `1985801`、`1992999` 附近。
精确索引以 evidence JSON 的动态 anchor 结果为准。

## 2. 真实 HTTP 契约

| 用途 | 方法 | 路径 | 请求体 |
|---|---|---|---|
| 查签到状态 | POST | /trae/api/v2/ug/checkin_credits/status | `{"req_source":1}` |
| 领取签到积分 | POST | /trae/api/v2/ug/checkin_credits/claim | `{"req_source":1}` |

域名通过 bootConfig service 的 `getApi(ugApi, path)` 解析，当前安装的产品配置
`bootConfig.ug.trae.normal` 是 `https://api.trae.cn`。运行时配置可能更新域名，
此处未把默认产品配置等同于动态抓包证据。

普通 IDE 的 `req_source=1`，另一产品形态的分支使用 2；不是随机参数。
此 JS 调用层没有加入 token 刷新参数、DeviceProof、ECDSA 签名、machine_id、
activity_id、windowId、source、nonce、时间戳、积分数量。
这不排除 Electron 原生网络层另有行为。

共享函数先取 `getAuthUserInfo()` 的当前 `token`，检查 CN provider 和 MARSCODE account scope，
并检查异步过程中账号是否切换；使用的是登录 token，不是 cookie 登录接口。

## 3. 请求头逐项来源

| 请求头 | 原生客户端来源 | 条件 |
|---|---|---|
| Content-Type | 固定 application/json | 总是 |
| Authorization | `Cloud-IDE-JWT ${currentUser.token}` | 总是 |
| x-device-id | device service 的 `guaranteedDeviceId` | 总是赋值 |
| x-device-brand | `HF(commonParams.device_model)` | 清洗后非空才加 |
| x-device-type | `commonParams.os_name` | 非空才加 |
| x-os-version | `commonParams.os_version` | 非空才加 |
| x-app-version | `commonParams.app_version` | 非空才加 |
| x-rust-request-timeout | TTNet JS wrapper，默认 30000 | 实际发送封装追加 |
| x-tt-env / x-use-ppe / x-use-boe / x-env-lane | 本地请求环境配置 | 仅相应配置开启时 |

`HF` 只清除设备型号字符串中的特定控制字符，不是哈希或签名。
`commonParams.app_version` 来自产品服务的 `appVersion`，当前安装为 3.4.20；
设备型号及 OS 信息来自设备信息对象。设备型号不是用户自定义的设备名称。

进一步追踪到 `iCubeSystemInformationService`：

- 导入 `electron.ahaDeviceService`，从 `deviceInfo.model` 和 `deviceInfo.manufacturer`
  读取型号、制造商；签到的 brand header 实际使用 **model**。
- Windows 的 `osName` 固定映射为小写 `windows`，不是 `Windows` 或 `win32`。
- Windows 的 `osVersion` 来自 Node `os.version()`；`os.release()` 单独保存为 release，
  不能把 Python 的 `platform.release()` 拼接值视为同一个来源。
- 主进程事件服务初始化时等待系统信息与设备解析，再填入 commonParams。
  签到头构造读取该对象的当时值，可选字段为空时不发送。

这些来源分别对应补充证据的 `system_information_service`、
`main_metadata_initialization` 和 `common_params_mapping`。

## 4. 设备身份不是登录流程随意生成的字符串

原生 device service 导入 `electron/main.ahaDeviceService`。
构造时读取 `deviceId.deviceId`、`deviceId.localDeviceId`，初始化时调用
`ahaDeviceService.getDeviceId(previousId)`，异步更新远端 device ID。
`guaranteedDeviceId` 优先使用主 device ID，为 `"0"` 时回退 local device ID。
因此领取时读到的是原生设备服务当时的状态，并非每次领取临时生成 ID。

main.js 已确认这一边界；Aha 内部的设备注册、硬件信息、缓存和原生请求细节
没有在本次 JS 静态复核中完全还原，不能宣称 Python 随机 ID 已等价复刻。
既有 EXE 分析见 `AHA_DEVICE_SERVICE_REVERSE_2026-11-19.md`，其中待验证项仍然有效。

## 5. 实际网络发送与结果处理

`mb` → `iCubeBaseTTNetService.fetchWithHeaders` → 内部 `c(request)` →
从 Electron 导入的 `net.fetch(url, options)`。
POST 请求体通过 `JSON.stringify(data || {})` 序列化，使用 AbortController 和 30000ms 超时。
领取显式 `retry:0`，没有失败自动重试。通用 wrapper 默认重试数也为 0。
JS 网络封装没有添加签到专用签名，可能的原生 header、默认 session、cookie、
User-Agent、TLS 或 Chromium/TTNet 内部处理仍需动态证据，不能仅凭静态 JS 断言完整 wire 等价。

### 5.1 不能忽略 session 的请求头拦截器

本次进一步发现，`mb → fetchWithHeaders → net.fetch` 之后还存在静态可达的
`webRequest` 请求头处理层，原表只列出了签到函数与 TTNet wrapper 的显式头。

`CodeWindow` 构造时调用 `bRe(this.s.webContents.session, services)`；该函数为 session
注册一个统一的 `onBeforeSendHeaders` 回调。匹配规则按注册顺序运行，将返回的头对象
合并后通过 `Object.assign(requestHeaders, overrides)` 覆盖原请求头。
标准窗口的 options builder `xf` 及其当前调用参数没有显式指定 session/partition。

| 规则 | 对签到 URL 的静态匹配条件 | 可能补充或覆盖的字段 |
|---|---|---|
| `solo-lite-websocket-headers` / `kRe` | URL pattern 含 `https://*/trae/*`；CN 域名、bootConfig 或动态允许来源通过其 filter；排除的 OAuth 路径不含签到 | 当前 auth service token 对应的 `Authorization`；store-region service 的 `X-User-Region`；配置开启时的环境头 |
| `marketplace-headers` / `SRe` | 将 `bootConfig.ug` 中的域名加入 patterns；排除的三个 OAuth 路径不含签到 | `X-Market-Client-Id: VSCode <editor version>`；`User-Agent: VSCode <editor version> (<nameShort>)`；条件分支下的其他 marketplace 头 |
| `reverse-proxy-gateway-target` / `DRe` | 存在 reverse-proxy registry 对应的重定向记录 | `Trae-Gateway-Target` |

`fRe` 的 editor version 参数来自 product service 的 `version`，不同于签到
`x-app-version` 使用的 `appVersion`；当前 package.json 的编辑器版本为 1.107.1。
`X-Market-User-Id` / `VSCode-SessionId` 还有条件分支，不能认定每次发送。

Electron 官方文档说明 `net.fetch` 使用 default session，且会触发已安装的 webRequest
handlers。结合本机静态窗口构造，这是需优先验证的原生/Python 差异；但当前没有捕获
该定制 Electron 的实际签到出站报文，不能将这些候选头全部标为本次实测已发送，
也不能认定它们是服务端必需字段或 9074 根因。

参考：[Electron net.fetch](https://www.electronjs.org/docs/latest/api/net#netfetchinput-init)、
[webRequest](https://www.electronjs.org/docs/latest/api/web-request#webrequestonbeforesendheadersfilter-listener)。
补充证据包含完整规则、header builder、窗口 session 绑定及 options 片段。

内置浏览器的 `persist:trae-webview` 是另一 partition，其自定义头、图片签名和 Google
登录 User-Agent 的代码不能直接套用到主进程签到请求。

### 5.2 响应、刷新和错误

状态响应必须含布尔 `enable` 和 `checked_in`；正数有限 `credits` 会缓存为该日签到展示值。
界面还读取可选 `did_checked_in` 和 `extra_credits`。
领取要求 HTTP 200；若含 `code`，必须是数字 0。非零 code 写入界面的
`businessFailure` 并提示错误。已检查的映射 `lTs` 显式处理
1002、2001、9004、9090、9093、9095；9074 没有独立分支，落入服务端 message 的默认显示逻辑。
workbench 里另一处数字 9074 是扩展管理的本地化索引，与签到业务码无关。

领取被接受后，主进程广播失效事件；界面刷新签到状态和积分用量。
来源有效时还可能启动附加抽奖，抽奖有单独接口，不是领取积分的前置请求。
日期按 UTC+8 计算，使用同步的服务器时间，缺失时回退本地时间。

## 6. 与当前 Python 实现的实际差异

| 项目 | Python 当前实现 | 判断 |
|---|---|---|
| 状态和领取路径、方法、请求体 | 已与 IDE JS 层一致 | 不应继续猜测路由或添加活动 ID |
| 鉴权 scheme | Cloud-IDE-JWT | 与该调用点一致 |
| 设备 ID | 独立 login 随机生成 14 位字符 | 与 Aha 服务不同，接受查询不等于通过领取的全部校验 |
| 型号 | 已改为读取 BIOS 注册表 SystemProductName；旧凭据的自定义名称会在内存补齐 | 原生来源是 Aha deviceInfo.model，二者尚未动态核对 |
| 版本 | 已从 product.json.appVersion 解析，并保存/加载 clientVersion | 已修复已知字段缺失；不是 9074 已解决的证据 |
| OS 类型 | 新登录使用 `Windows`，签到优先保留凭据 osInfo，fallback 使用 platform.system() | 原生是小写 `windows`，仍有明确的大小写差异 |
| OS 版本 | 优先使用凭据 osVersion；新登录/fallback 基于 Python platform 元数据 | 原生 Windows 取 Node os.version()，不能声明相同 |
| 超时 header | 已发送 x-rust-request-timeout=30000 | 已对齐显式 wrapper 字段 |
| did_checked_in | 已保留并处理 true 时跳过领取 | 已补齐本地 gate |
| session 请求头规则 | checkin.py 没有对应拦截层，也未显式设置 X-User-Region / X-Market-Client-Id / 原生 UA | 原生静态规则会匹配签到域名；实际最终头需动态核实 |
| 网络层 | httpx，trust_env=False | 与 Electron net.fetch 的 session、代理和 TLS 行为不完全相同 |
| 成功确认 | 已在 claim 被接受后再查一次状态，不因确认失败重发 claim | 可确认签到标记，不证明积分余额实际增加；原生还刷新用量 |

前次已实施的字段修复见 `TRAE_CN_CHECKIN_FIX_2026-11-19.md`。本次仅补充静态证据
并更新报告，没有替换设备 ID、修改凭据、操作客户端或发送领取请求。

## 7. 对 9074 的结论与下一步

用户提供的 Python 状态查询成功：`enable=true, checked_in=false, credits=100,
did_checked_in=false, extra_credits=100`；随后 execute 输出带有
`claim failed: ... code=9074; message='当前参与用户太多，请稍后再试'`，定位到领取阶段。
100 是状态接口字段，不是已到账余额证明。

用户随后报告原生客户端能够正常领取。这是用户提供的操作结果，不是本次抓包证据；
对照的精确时间、出站字段和请求身份没有共同记录。因此应将问题聚焦到客户端请求
差异与服务端条件差异，不能继续把“账号无法领取”或“全局拥挤”当作已确认原因。

9074 的服务端具体条件没有客户端代码证据，不能直接认定拥挤、封号、设备风控或验证码要求。
也不能因为 status 成功就认定当前身份已满足 claim 的所有检查。

后续实施顺序：
1. 先核对当前 Python token/device ID 的来源与原生对应关系，只记录相等与否，不输出秘密值；
   不把原生登录与 Python 独立登录产生的两个身份默认视为相同。
2. 按本报告处理明确的字段差异，尤其 OS 大小写、版本来源及 session 请求头层；
   header 对齐也不能等同于完整网络或设备注册复现。
3. 后续有可领取机会时，观察原生请求最终头与响应，再与 Python 对照；用户已完成原生成功操作，
   不要求为重复证明成功而再次领取，也不在已签到当天强制绕过 gate。
4. 只有实际 claim 成功、状态和积分用量得到确认后才更新验收；不自动循环重试，
   不把静态差异写成 9074 根因已确认或问题已修复。
