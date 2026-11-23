# 参数对齐后仍返回 9074：剩余差异复核

> 后续已新增 `--native` 模式，对齐这里发现的登录设备上下文差异，并已完成一次 verified=true 的线上签到，见
> [实现与验证](TRAE_CN_CHECKIN_NATIVE_IDENTITY_2026-11-20.md)。本报告保留修改前差异证据，
> 网络层与动态字段的未知项仍然有效。

## 本轮证据

- 用户授权执行修改后的 `python -m trae2api.checkin --creds .\trae2api\trae2api.json --execute`，
  返回 exit code 1，错误明确发生在 claim 阶段，业务码仍为 9074。
- 本次复核只读取源码、本地凭据和运行中原生客户端的当前会话日志；没有再发起领取。
- 当前主进程 PID 50844，启动于本地时间 2026-11-19 22:20 左右；对应日志目录为
  `%APPDATA%/Trae CN/logs/20261119T222004/`。
- 仅输出/记录身份比较的布尔结果，不输出 token、设备 ID、machine ID 或其摘要值。

## 已确认的身份差异

当前会话 main.log 中的 `[ICDRS] (init) resolve rdid` 和 initialization done 记录一致：
原生使用了已解析的远端 device ID，且该 ID 不同于本地 fallback ID。

| 检查 | 结果 |
|---|---|
| 原生初始化最终 ID 等于该日志的远端 ID | true |
| 原生初始化最终 ID 等于该日志的本地 ID | false |
| 原生远端 ID 是数字字符串 | true |
| 原生登录设备密钥项后缀等于该远端 ID | true |
| 脚本发送的设备 ID 等于该远端 ID | false |
| 脚本 ID 符合本项目随机生成器的 14 位格式 | true |
| 脚本与当前原生凭据存储对应同一 userId | true |
| 脚本 token 等于当前原生凭据存储 token | false |

这比只比较原生登录设备密钥项更强：已核对运行中客户端所属会话的真实设备解析日志。
但日志反映初始化时点，不是本次出站 header 抓包；当前存储 token 也不等同于已经观察到
运行时最终 Authorization。token 不同本身不是错误，不同登录会话可以有不同有效 token。

脚本请求由“独立凭据文件的 token/设备 ID”与“本机原生配置的 marketplace 标识/系统信息”
共同构成。上一轮只对齐了已知字段与 header 规则，未将其登录设备上下文改为原生上下文。
尚不能根据 ID 格式或未实现注册流程，断言服务端一定因这一点拒绝或该 ID 从未被接受。

## 已对齐与尚未观察的字段

本轮重新构造请求，未发送网络请求，确认 URL、POST、16 字节 body `{"req_source":1}`、
User-Agent `VSCode 1.107.1 (Trae CN)`、X-Market-Client-Id、X-User-Region=CN、
产品版本 3.4.20、windows / Windows 10 Education、超时头及两个 marketplace 身份头均存在。
原生日志记录 store region 为 CN。

UA 等字段按原生静态代码生成，不能将“构造符合源码”写成“与原生最终出站报文逐字相同”。
当前 main.log 没有可用于比较的原生 deviceModel / 系统信息输出；型号仍由 Python 注册表
读取，尚未证明等于 Aha deviceInfo.model。

## 网络层

| 项目 | 原生 | 当前脚本 | 判断 |
|---|---|---|---|
| 代理 | 当前会话多次记录 Applying direct network mode | trust_env=False，当前无 HTTP/HTTPS/ALL_PROXY | 都有直连证据，代理可降低排查优先级 |
| Windows 代理 | ProxyEnable=0；虽然保留 ProxyServer 值，但未启用 | 不采用 Windows 系统代理 | 不能仅凭存在历史 ProxyServer 就说原生走代理 |
| 网络栈 | Electron net.fetch / 定制原生网络组件 | httpx / Python SSL | 仍不同 |
| HTTP 协议 | 未捕获该次原生领取的协商结果 | 当前 Client 未开启 HTTP/2 | 存在实现差异，未证明两端实际协议不同 |
| session/cookie | 未捕获最终请求是否携带 cookie | 新建 httpx.Client，构造时 cookie jar 为空 | 未证明原生需要或发送 cookie |
| 自动头及原生附加处理 | 尚无最终报文 | Accept=*/*，gzip/deflate/br/zstd，keep-alive 等 httpx 默认值 | 不因 UA 对齐就认定剩余 wire 相同 |

## 对照时间与结论

当前 main.log 中最近一次原生 claim 的 request/response 时间字段为
`2026-11-19T23:52:21`，HTTP 200，随后刷新 status。
此处保留日志原始时间字段，不额外推断其时区。
HTTP 200 本身不证明业务成功，成功另有用户操作反馈。
修改后的脚本失败是 11 月 20 日的后续执行，两者不是同一轮动态配对请求，
不能排除时间相关的服务端条件变化。

最明确的剩余差异是登录设备上下文；网络实现仍有未知项。
下一步应先固定同一组有效登录身份及原生设备 ID，再比较发送路径，避免身份和网络同时变化。
尚无证据将 9074 精确归因于某个字段、TLS、设备注册或服务端拥挤。
