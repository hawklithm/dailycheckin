# 自研 getDeviceId 的原生逻辑对齐

> 后续实现及当前验收结论见 [原生模式还原与验收](AHA_GET_DEVICE_ID_NATIVE_PARITY_2026-11-20.md)。
> 下文保留上一阶段的 284 项测试结果与当时的缺口；缓存编解码、地区状态及生命周期等
> 已在后续阶段继续实现，且真实缓存命中路径已完成只读一致性验证。

日期：2026-11-20。目标：Windows x64 Trae CN 3.4.20。
本文件更新首版实现说明及调整前的一致性报告。

## 本轮结果

已对齐下列已确认的硬件回退、设备记录校验和异步获取行为，完整指定离线回归
**284 passed in 25.21s**。未执行线上设备注册、激活、登录、绑定或签到，未将这组测试
解释为已取得与原生相同的真实数字 deviceId。

关键改动位于：

- `trae2api/device_hardware.py`：硬件来源和 MAC 缓存。
- `trae2api/aha_device_cache.py`：已还原的明文设备记录及有效性判定。
- `trae2api/aha_device_service.py`：缓存状态、内存结果、异步等待及超时处理。
- `trae2api/login_identity.py`：独立档案中的设备记录迁移与持久化。

## 硬件处理

| 字段 | 当前处理 | 证据与限制 |
| --- | --- | --- |
| UUID | SMBIOS 优先；读取失败或 UUID 无效时查询 WMI，输出大写标准 UUID | 原生 GetHardwareInfo 的 WMI 查询常量；无可用 UUID 时仍报错，不随机构造注册硬件 |
| 磁盘 | 读取 HKLM 的 disk/Enum/Count，最多枚举 10 个；选择磁盘 0、系统盘、首个有效磁盘 | 枚举上限见 `0x01d3ba20`；系统盘辅助函数 `0x01d3bf20` 使用 `0x560000` 卷磁盘 extents IOCTL |
| MAC | 优先读取 HKCU 的 `Software\DeviceInfo\MacAddr` 下 `mac`；未命中再采集适配器并缓存 | 原生读写类型是 **REG_BINARY=3**，不是 REG_SZ；正常地址按 ASCII 字节保存，不附加 NUL |

MAC 缓存读取的类型检查见 `0x02846e92–0x02846ea8`，写入类型参数见
`0x028476fc`。正常缓存内容保留原样，不因为当前网卡发生变化就强制重采集。
缓存写入失败时仍返回采集结果。

Windows UUID 来源的系统定义可参考
[Win32_ComputerSystemProduct](https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-computersystemproduct)。
本项目使用固定、只读的本地 CIM 查询，设置隐藏进程和 15 秒执行上限，不拼接硬件字段到命令。

这些是来源、顺序及普通输入域的对齐，不构成全部 Windows 异常设备、适配器筛选和每种磁盘
驱动返回格式都已与原生逐字节对照的结论。本轮测试对注册表、WMI 和采集函数使用替身，
没有实际执行新加入的真实硬件读取/缓存写入。

## 设备记录与安装身份

独立身份档案新增可选 `ahaDeviceCache` 字段，内容采用已还原的明文结构：

```json
{
  "device_id_str": "12345",
  "install_id_str": "67890",
  "uuid": "33221100-5544-7766-8899-AABBCCDDEEFF",
  "version": "1.2"
}
```

以上均为测试值。整个 `.device.secret` 档案的版本仍为 1；1.2 只表示内部设备记录格式。
文件不是原生 TinyStorage 的加密编码，原生客户端不能据此直接读取我们的文件。

- 首次遇到旧档案时，在独立档案中迁移已有的已注册 ID，不重新生成 machineId 或安装密钥。
- 记录版本、字段类型或 UUID 不匹配时，作为设备缓存未命中处理，不再因 UUID 不同直接报错退出。
- 空/零/非普通正十进制的 device ID 不作为有效缓存；install ID 按原生记录结构要求为字符串，
  不在这个记录解析器中额外要求它是正数。
- 无效记录不会让旧的 `registered=true` 元数据绕过设备记录验证，也不会删除已存的安装密钥。
- 成功注册后，设备记录与登录适配器元数据通过同一次原子文件替换落盘，然后才按调用要求激活。
- 设备缓存损坏与登录私钥档案损坏分开处理。后者继续明确报错并保留文件。

P-256 安装密钥和激活状态仍属于本项目的登录适配器元数据，均不是原生 1.2 设备记录的字段，
也不是硬件可信证明。

## 获取、超时和并发

| API | 行为 |
| --- | --- |
| `get_device_id()` | 保留同步兼容入口；默认离线，已解析的远程 ID 直接复用内存 |
| `get_device_id_async()` | 对应原生 getter 的主要等待语义：已有远程 ID 立即返回，否则等待结果，不自动发 HTTP |
| `resolve_device_id_async()` | 对应 JS 包装层；默认等待 40 秒，超时后主 ID 使用本地 UUID，远程 ID 仍为 `"0"` |
| `register_device_async()` | 显式注册入口，要求已经传入 HTTP client；获取 ID 与要求激活分开 |
| `get_all_ids()` | 分别返回 deviceId、localDeviceId、remoteDeviceId |

40 秒来自当前安装包 `iCubeDeviceRegister.js` 中的 `O$=4e4`。
超时不会取消注册工作，迟到的远程结果仍更新主 ID 与远程 ID。注册开始前先发布已初始化的
本地/缓存状态，使超时等待不被正在进行的 HTTP 请求阻塞。

同一实例的多个调用者共享初始化和结果；并行注册操作串行进入，后续操作复用已保存的注册结果。
调用方取消等待不会取消其他等待者或丢弃已开始的注册工作。不同实例/进程仍通过原有档案排他锁
阻止同时写入，不实现未经确认的原生跨进程协调策略。

对外返回身份对象的隔离副本，调用方修改返回值不会更改服务内部 ID 或缓存记录。
硬件信息在同一服务实例内只初始化一次。

原有同步登录准备流程仍显式要求注册和激活，保持它的错误处理契约。新的异步 getter 负责
获取 ID 的等待语义，不将“获取到 ID”混同为“已激活”。

## 尚未等价的部分

本轮没有宣布整个 Aha SDK 完全等价。以下边界仍然存在：

1. 原生 TinyStorage 加解密封装及全部密钥来源没有完整还原，当前实现不读取或写入原生设备记录。
2. 地区/未命名配置位触发的后台刷新、旧 ID 参数迁移、自动重试时序未完整复刻；离线 getter 不会自动启动网络。
3. 原生无设备信息对象时的随机 localDeviceId 回退未复制；当前硬件读取失败仍报告错误。
4. 注册响应和登录激活适配器保留双 ID 正十进制校验；未声称与原生响应解析所有异常输入分支相同。
   设备记录数字解析器的符号、空白及溢出边界也未完全验证。
5. 原生配置会影响注册回调相对激活的交付时机；当前 getter 在已有有效设备 ID 时即可返回。
6. 服务端分配/去重算法未知。本地流程对齐不能证明两条真实链路最终返回同一个数字 ID。

## 验证记录

新增硬件和原生语义测试文件：`test_device_hardware_parity.py`、`test_aha_device_parity.py`。
覆盖缓存类型、回退顺序、旧记录迁移、损坏记录、UUID 不符、内存快取、返回对象隔离、
并发等待、并发注册、取消、超时、HTTP 进行中的超时，以及激活失败后设备 ID 仍可读取。

测试均使用测试硬件、假注册表、内存 MockTransport 或既有回环 HTTP mock。
原有本地登录回调测试改为有上限地等待完成事件，避免 handler 先发送 HTTP 响应、后设置事件
产生的即时断言竞争，生产回调流程未因此修改。

中间回归曾发现返回对象共享问题，已修复并增加测试；另一次回环 mock 连接发生 Windows 10053
中断，该项单独复跑通过，最终完整回归也通过，没有修改该 mock 的服务行为。

最终命令：

```powershell
D:\Users\marcus\anaconda3\python.exe -m pytest tests/test_device_hardware_parity.py tests/test_aha_device_parity.py tests/test_aha_device_service.py tests/test_sandbox_lab_config.py tests/test_sandbox_lab_client.py tests/test_sandbox_lab_runner.py tests/test_sandbox_lab_binding.py tests/test_independent_login.py tests/test_native_identity.py tests/test_checkin_offline.py tests/test_checkin_profile.py tests/test_client_metadata.py tests/test_gateway_body.py tests/test_device_identity_offline.py -q --tb=short --junitxml=logs/aha-device-alignment-20261120.xml
```

结果：**284 passed in 25.21s**。JUnit 在 `logs/aha-device-alignment-20261120.xml`。
补充静态证据在 `AHA_DEVICE_ALIGNMENT_EVIDENCE_2026-11-20.json`。
