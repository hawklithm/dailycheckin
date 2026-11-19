# 签到使用原生登录身份

新增 `--native` 入口，配对使用当前原生登录 token 与有本地证据佐证的远端设备 ID，
替代之前“独立凭据身份 + 原生请求元数据”的组合。原来的 `--creds` 入口继续用于独立凭据；
两个来源互斥，不自动替换或覆盖 `trae2api.json`。

## 使用

```powershell
# 只读取、校验身份后查询，不领取
python -m trae2api.checkin --native --status-only

# 使用同一身份执行查询、按资格领取、领取后确认
python -m trae2api.checkin --native --execute
```

这两个命令不需要也不应附加 `--creds`。非标准安装仍支持
`TRAE2API_USER_DATA` 和 `TRAE2API_PRODUCT_JSON`。

## 身份选择

1. 从原生 user-data 的 `User/globalStorage/storage.json` 解密当前登录信息，
   使用其中 token；要求存在 userId 且 account.scope 为 marscode。
2. 只检查最新日期会话目录中的 main.log，不回退到更旧的已完成会话。
3. 读取 `[ICDRS] (init) resolve rdid` 与 initialization done 的设备证据，
   拒绝 ID=0、本地 fallback 或先完成远端解析后却出现不一致的初始化结果。
   原生 promise 可能在初始化超时之后才完成；这种情况下以后到的远端解析结果为准，
   对应已复核 JS 的 live ID 更新行为。
4. 要求这个远端 ID 对应当前 storage 中的 `iCubeAuthInfo://icube-dc:<ID>` 键。
   不任取首个设备记录，不解密设备私钥，不生成 ID，也不触发注册。
5. 地区从该会话日志中已记录的 getStoreRegion 取得，不使用独立凭据的 AIRegion 替代。
6. 每次 HTTP 请求之前重新加载并复核登录、设备、地区及会话。任何一项改变都停止发送，
   不自动拼接新旧上下文，不刷新或轮换 token。

原生登录 token 在本地检查已过期时，提示到原生客户端重新登录，不引导独立 login。
错误信息不输出 token 或设备 ID，Account / NativeIdentity 的 repr 也隐藏身份值。

## 验证

合成离线用例覆盖配对发送、只读行为、设备证据不匹配、本地 fallback、最新会话不完整、
超时后远端解析、过期 token、领取前账号/token/设备变化停止、CLI 状态查询及 dry-run。
相关回归 **66 passed**；修改模块 compileall 与 git diff --check 通过。

本机只读构造检查确认：

- 原生身份与原有独立凭据对应同一账号；
- 新入口的 token、远端设备 ID 均来自原生上下文，与原独立凭据值不同；
- 请求时身份复核通过，UA 仍为 VSCode 1.107.1 (Trae CN)，地区 CN；
- 原独立凭据文件字节未改变，未输出秘密值。

实际运行 `--native --status-only` 成功返回：
`action=status, enable=true, checked_in=false, credits=100, did_checked_in=false, extra_credits=100`。

随后在用户已有签到执行授权范围内，用新入口单次执行 `--native --execute` 验收：

```json
{"action":"checked_in","credits":100,"verified":true,"status":{"enable":true,"checked_in":true,"credits":100,"did_checked_in":true,"extra_credits":100}}
```

进程 exit code 0，领取被接受，复查 checked_in/did_checked_in 均为 true。
当前账号在该次原生身份模式下已完成签到，原独立凭据文件未被改写。
credits=100 仍是签到接口返回值，本次没有查询积分用量，不能单凭它证明余额增加了 100。
这支持登录设备上下文差异是本例的重要因素，但没有对 token 和设备 ID 分别做独立变量实验，
也不是 9074 在所有账号/条件下的通用原因证明。

## 仍有边界

日志证据对应设备初始化/解析时点，不是原生实时 getter 或最终出站报文。
只有日志与当前设备记录一致才可进入该模式；缺少证据时停止。
本机系统型号仍使用注册表近似 Aha deviceInfo.model，尚无值级动态对照。
当前网络栈仍为 httpx；原生 Electron 的 TLS、HTTP 协议、session cookie、自动头和
网络组件内部附加行为尚未完全观测，不能将身份对齐写成完整原生报文等价。
