# get_device_id 与原生 Aha 的一致性复核

> 本文为调整前的复核记录。后续代码和真实缓存只读验收见
> [原生模式还原与验收](AHA_GET_DEVICE_ID_NATIVE_PARITY_2026-11-20.md)，
> 已实证缓存命中路径取得相同 deviceId；不代表线上新注册已验收。

日期：2026-11-20。

> 本报告记录本轮调整前的结果。后续实现状态见
> `AHA_GET_DEVICE_ID_ALIGNMENT_2026-11-20.md`，不能把下表全部当作当前仍存在的差异。

## 结论

**实现不完全一致；尚未验证能返回与原生完全相同的真实 deviceId，也不能保证该结果。**
当前独立服务复现了已确认的部分状态处理，不是原生 Aha 的完整等价实现。
数字 deviceId 来自服务端注册响应，不是已经还原的硬件到数字 ID 的本地计算公式。

本轮仅复核安装文件、源代码和指定离线测试，没有调用原生进程获取运行时返回值，
没有读取账号凭据或原生运行时缓存，也没有连接真实注册、激活、登录、签到服务。

## 当前安装包基线确认

重新计算本机 Trae CN 安装文件 SHA-256，均与已有静态分析基线一致：

| 文件 | SHA-256 |
| --- | --- |
| Trae CN.exe | eac5743ab3eafa528ae766a11a814cd0d8ea1c54cb948c66027e71479fe00ede |
| resources/app/out/main.js | 433e32bd7821ab4b05e46be1fc1b74043315884ba3ec58c45c99d94f58fd6816 |

同时确认当前 main.js 中仍存在 Electron `ahaDeviceService` 的导入、初始设备 ID 读取和
`getDeviceId` 调用。原生语义证据来自同一 EXE 的
`AHA_DEVICE_CACHE_STATIC_EVIDENCE_2026-11-20.json`，不是运行了一个替代的“原生模型”。

## 一致点和差异

| 项目 | 原生链路已确认行为 | 当前独立实现 | 判断 |
| --- | --- | --- | --- |
| 注册 ID 来源 | 复制注册响应中的 device_id_str/install_id_str | 保存并返回响应中的两个字段 | 来源一致；不是本地生成数字 ID |
| 保存与激活 | 注册成功先写缓存，再进入激活 | 先保存 registered 状态，再按要求激活 | 顺序一致；完整调度不同 |
| 已有 ID 的获取 | 从 SDK 内存返回，来源可以是原生缓存或注册响应 | 从独立 IdentityStore 读取 | 数据来源不同，不自动共享同一个 ID |
| 持久化格式 | TinyStorage，封装后的记录版本 1.2 | 独立 .device.secret，档案版本 1 | 不一致 |
| UUID 不符 | 原生缓存校验失败，不复用该记录 | 抛错，保留档案，不自动重新注册 | 不一致 |
| 无远程 ID | 原生 getter 排队等待，JS 层另有超时和本地备用 ID | 默认离线立即返回结果对象，device_id 为 "0" | 返回时机及接口语义不同 |
| 本地备用 ID | 有设备信息对象时取其 UUID；对象不存在时另有随机回退 | 使用硬件 UUID；必要 UUID 缺失就抛错 | 常规来源相近，回退不同 |
| UUID 读取 | SMBIOS，存在 WMI 回退 | SMBIOS；没有 WMI 回退 | 边界条件不一致 |
| 磁盘序列号 | 多候选路径 | 当前只尝试 PhysicalDrive0 | 可能导致注册参数不同 |
| MAC | 优先用户注册表缓存，缺失时采集并缓存 | 直接采集适配器地址 | 可能导致注册参数不同 |
| 启动刷新/旧 ID 迁移/重试 | 地区、配置、旧 ID 和网络恢复调度参与 | 未完整复刻 | 不一致 |
| 响应检查 | 已见字段读取及 device ID 非空、非 "0" 检查 | 两个 ID 均要求正十进制字符串 | 独立实现更严格；不能声称完全等价 |

代码位置：`trae2api/aha_device_service.py:58`、`trae2api/aha_registration.py`、
`trae2api/device_hardware.py:56`、`:74`、`:104`。
原生 getter RVA `0x0284a040`，响应解析 `0x0284c490`，缓存校验 `0x0284c9e0`。

## “相同硬件”为什么不足以证明“相同数字 ID”

在没有刷新或迁移介入、两边都接受对应记录的条件下，如果两个缓存已经保存同一个数字 ID，
读取出来当然可以相同。若两边接受的注册响应包含同一个数字 ID，返回值也可以相同。

但本项目没有还原服务端设备分配和去重算法。客户端提交相同硬件字段，是否一定复用原 ID，
缺少证据；何况当前两个硬件读取器还可能提交不同的 MAC 或磁盘字段。
因此不能把“注册请求字段大体相同”推导成“真实 deviceId 必然完全相同”。

`local_device_id` 或 `guaranteed_device_id` 的 UUID 相等也不能替代数字设备 ID 的相等验证。

## 本轮测试与证据边界

执行：

```powershell
D:\Users\marcus\anaconda3\python.exe -m pytest tests/test_aha_device_service.py tests/test_independent_login.py -q
```

首轮：28 passed、1 failed。失败项为
`test_confirmation_does_not_finish_login_without_authcode` 的事件即时断言。
当前 handler 在发送 HTTP 成功响应之后才调用 `flow._done.set()`；客户端拿到响应与断言事件
之间可能存在调度竞争。这是由源码顺序支持的解释，未据此修改生产代码或测试。

随后运行全部 14 项设备服务测试及该失败项：

```powershell
D:\Users\marcus\anaconda3\python.exe -m pytest tests/test_aha_device_service.py tests/test_independent_login.py::test_confirmation_does_not_finish_login_without_authcode -q
```

结果：**15 passed in 38.02s**。设备服务测试两轮均通过，回调失败项复跑通过；
这不构成该时序竞争已修复或不存在的证据。

这些测试的服务端响应由 MockTransport 固定，硬件是测试夹具，验证的是本项目自己的行为。
包括此前的 235 项离线测试在内，都不能充当“已与真实原生运行结果取得同一 deviceId”的证据。

本轮结果分级：

- 安装包与既有反汇编基线相同：已确认。
- 本项目关键离线行为通过测试：已确认。
- 与完整原生实现等价：已发现明确差异。
- 本机两条真实链路返回完全相同数字 deviceId：未测试，不能确认。
