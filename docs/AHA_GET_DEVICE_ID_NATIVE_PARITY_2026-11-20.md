# getDeviceId 原生模式还原与验收

日期：2026-11-20。目标：Windows x64、Trae CN 3.4.20；结论限于本版本。

## 当前结论

自研组件已接入独立的原生生命周期，覆盖原生缓存编解码、硬件采集回退、旧 ID 迁移、
地区状态、注册与激活的先后顺序、网络变化重试，以及 JavaScript 包装层的超时回退。
既有登录流程所需的严格校验仍属于登录适配层，不再用它替代原生 SDK 的判断。

**真实缓存命中路径已实证返回完全相同的 deviceId**：只读本机原生 TinyStorage，
使用原始二进制指令解密，再与 Python 解密、当前硬件 UUID、公开 getter、resolver
及 get_all_ids 的结果比较，全部一致。没有启动原生客户端、读取凭证文件或访问线上服务，
原生缓存前后字节未变化。验收产物仅保存布尔值，不保存真实设备标识。

新注册路径完成静态还原及离线验证，尚未执行线上端到端验收。服务端分配的 ID 不是
客户端根据硬件独立算出的散列，因此不能据此保证两次独立线上注册一定分配相同 ID。
当前证据也不等同于整个 Electron/TTNet 二进制逐字节复刻。

## 实现入口

| 文件 | 职责 |
| --- | --- |
| `trae2api/aha_device_service.py` | 对外 facade；`start_native_mode` 切换原生生命周期，随后公开 getter/resolver 均委托给它 |
| `trae2api/aha_native_lifecycle.py` | 原生缓存状态、pending getter、注册/激活通知时序、重试及 40 秒回退 |
| `trae2api/aha_native_semantics.py` | uint64 解析、启动条件、旧 ID 迁移及重试间隔 |
| `trae2api/aha_cache_codec.py` | 原生及旧版缓存信封、派生密钥、AES-CBC、摘要和 Base64 |
| `trae2api/aha_device_cache.py` | version=1.2 设备记录及有效性判定 |
| `trae2api/aha_tiny_storage.py` | TinyStorage、旧 Preferences 迁移、地区记录 |
| `trae2api/device_hardware.py` | 注册 UUID、localDeviceId、磁盘及 MAC 来源 |
| `trae2api/aha_native_backend.py` | 显式注入的 HTTP 传输适配器；不自动联网 |
| `tools/aha_native_oracle.py` | 在 Unicorn 中执行限定范围的原始 PE 指令，生成合成样本基准 |
| `tools/aha_cache_acceptance.py` | 可重复运行的本机只读缓存验收 |

离线读取原生缓存的入口示例：

```python
from pathlib import Path
from trae2api.aha_device_service import AhaDeviceService
from trae2api.login_identity import IdentityStore

# 在 async 函数中运行；此路径是独立档案，不能指向原生 TinyStorage。
service = AhaDeviceService(IdentityStore(Path("logs/local-native-profile.json")))
native = await service.start_native_mode(native_cache=True)  # 默认 allow_network=False
try:
    # 命中有效缓存时返回原生设备 ID；未命中时由包装层在 40 秒后本地回退。
    result = await service.resolve_device_id_async()
finally:
    await native.close()
```

`native_cache=True` 使用 `%APPDATA%/Trae CN/aha/TinyStorage`，默认只读。
自定义 user-data-dir 应显式传入 `NativeTinyStorage.for_native_client(client_root=...)`
作为 `storage`。写原生存储必须显式构造 `writable=True`，本轮未使用。
需要注册的调用必须另外显式注入 backend/HTTP client，并启用 `allow_network=True`；
本轮未执行该操作。使用者负责关闭原生生命周期，不应混用原生驱动与旧登录驱动。

## 逐项还原

### 设备身份与硬件

- 注册 UUID 优先来自 SMBIOS；无效或不可用时查询 WMI。WMI 的有效 BSTR 原样复制，
  包括空字符串，不再擅自转大写或做第二次 UUID 校验。
- 注册使用的 UUID 与 localDeviceId 分开保留。WMI 回退不会覆盖原始 SMBIOS 本地值；
  仅无硬件信息对象的本地回退路径生成 UUIDv4，不把它充作服务端分配的数字 ID。
- 磁盘枚举读取注册表 Count，上限 10，选择磁盘 0、系统盘、首个有效磁盘。
  系统盘定位使用卷 extents IOCTL，序列号来自存储描述符。
- MAC 优先使用原生注册表缓存，要求 REG_BINARY，保留缓存中的 ASCII 表示；
  缓存未命中才采集适配器，缓存写入失败不丢弃采集结果。

### 缓存与迁移

- 当前信封头 `746305100000`，兼容旧头 `123920200203`；32 字节种子、两级 SHA-512
  派生、AES-128-CBC、明文 SHA-512 摘要和 Base64 均已还原。
- 原生种子由 `_time64`、32 位 `srand`、MSVCRT `rand` 生成；相同明文和时间输入的
  加密结果与原始指令逐字节一致。这是缓存格式，不是设备真实性证明。
- 解密匹配原生仅检查最后一个 padding 字节及摘要的行为；没有额外强制所有 padding
  字节相同。对短帧和未对齐密文采用有界失败，不复刻原生潜在的越界内存访问。
- Base64 对齐和无效字符检查匹配原生样本；设备记录要求 version=1.2、UUID 精确匹配、
  deviceId 可按原生 uint64 解析且非零，installId 为字符串。原生允许的 `+0001`
  不能被登录层的十进制正整数策略提前拒绝。
- TinyStorage 新键存在时，即使内容为空也不回退旧档案；缺失时读取旧 Preferences。
  旧 root 直接设备键覆盖其嵌套 tiny_storage_data 同名键；只读模式只构造迁移视图。
- 旧 ID setter 拒绝空串和 `"0"`，其余先保留 oldId；仅当前内存 ID 非空时才覆盖并写缓存。
  数字解析属于此处的统计记录，不应误作为 setter 的接受条件。

### 启动、注册、激活和包装层

- deviceId 无效或为零时需要注册；有效 ID 且 appRegion 为 CN 时不要求地区记录；
  非 CN 时检查 RegionInfo 的 optional.has_value。该条件不是未明含义的 SDK 配置开关。
- RegionInfo 解密后是 JSON dictionary 即 ready，包括空 dictionary。更新时内存保留
  未提供的可选 query/headers，而原生落盘序列化的是 incoming 参数，已分别实现。
- 注册包的已有 ID 经原生 uint64 转 double；失败解析保留原生的数字前缀/溢出结果，
  不统一强制置零。gzip JSON 及请求字段有离线检查。
- 注册响应为 HTTP 200、net_error=0、两个字段均为字符串时，先写内存，随后判断
  deviceId 不是空串或 `"0"`。有效响应先保存设备记录，再发激活请求。
- 实际 GetDeviceId 入口构造的四字节请求上下文为零，默认先通知待决 getter，再激活。
  回调中的 byte2/byte3 延迟通知分支也已保留，但不赋予没有证据的业务含义。
- 激活 JSON 中 is_activated 只用于原生诊断；HTTP 200 且 net_error=0 才是本路径的完成条件。
  既有登录流程更严格的激活检查仍留在其适配器中。
- 默认提前通知后，激活失败不重新注册；延迟通知分支的激活失败会重试整条工作流。
- 重试为每 5 次增加 1 秒、最高 30 秒，计数按 uint32 运算；不是指数退避。
  network type=6 时不设重试定时器，后续非 6 网络变化可取消旧定时器并从 attempt=0 重启。
- SDK 空内存 getter 保持 pending；包装层 40 秒超时后回退 localDeviceId，保留 remoteDeviceId，
  后续真实结果仍可更新 main/remote。关闭时清理后台任务及 pending future。
- 原生下载上限 1 MiB；HTTP 适配器有界读取并跟随重定向。原生 SimpleURLLoader 的
  OnReceiveRedirect 在未设置重定向回调时进入 FollowRedirect 路径，见下方证据。

## 验证证据

原始机器码执行基准针对固定映像 SHA-256：

```text
eac5743ab3eafa528ae766a11a814cd0d8ea1c54cb948c66027e71479fe00ede
```

分析工具只将 PE section 映射至 Unicorn；禁止未知执行地址，不启动 EXE、不加载 OS 导入、
不提供网络或凭证。时间、内存分配等运行时通过有限替身提供，SHA-512 与 AES 运算执行
原始指令。迁移函数的统计记录通过无副作用替身隔离。

| 原始指令样本类别 | 数量 |
| --- | ---: |
| uint64 解析 | 96 |
| 启动条件 | 60 |
| 重试间隔 | 22 |
| Base64 | 19 |
| 旧 ID 迁移 | 40 |
| 注册 header 数值转换 | 96 |
| 缓存加密/往返 | 16 |
| 旧版及异常缓存解密 | 4 |
| 合计 | **353** |

固定样本：`tests/fixtures/aha_native_oracle_20261120.json`。
原始指令及来源摘要见 `AHA_NATIVE_PARITY_EVIDENCE_2026-11-20.json`。
完整指定离线回归 **688 passed，0 failed，0 skipped**；JUnit 记录在
`logs/aha-native-parity-20261120.xml`，用时约 47 秒。
其中包含 353 个原始指令样本，以及生命周期、迁移、硬件、重定向和既有登录/签到回归。
本地 mock 的异常请求处理另修复了拒绝请求前未消费 body 导致的 Windows 连接中断，
没有修改账号绑定或设备日限策略。

实际缓存验收：`AHA_REAL_CACHE_COMPARISON_2026-11-20.json`，主要结果均为 true：

- 原始机器码解密与 Python 解密一致；版本、当前硬件 UUID、原生数字检查通过。
- 原生缓存 deviceId 与公开 getter、resolver、get_all_ids 返回一致。
- 原生缓存字节未变化；未启动客户端、未访问线上服务、未打开凭证文件。

复现只读验收（本机安装位置示例）：

```powershell
D:\Users\marcus\anaconda3\python.exe tools/aha_cache_acceptance.py `
  'D:\Users\marcus\AppData\Local\Programs\Trae CN\Trae CN.exe' `
  --output docs/AHA_REAL_CACHE_COMPARISON_2026-11-20.json
```

原始指令工具需要可选分析依赖 Unicorn。本机安装于被忽略的
`logs/aha-oracle-deps`，未加入生产依赖。缓存缺失或硬件不符会报告失败，不会转而联网注册。

主要反汇编锚点：数字解析 `0x041f5160`；启动策略 `0x02849050`；旧 ID setter
`0x02849440`；注册入口及上下文 `0x0284a5d0`；注册完成 `0x0284b820`；激活完成
`0x0284d1a0`；重试 `0x0284e9e0`；网络变化 `0x0284d7f0`；缓存加密/解密
`0x033588d0/0x03358c70`；地区加载/保存 `0x02844ce0/0x02844110`；旧偏好迁移
`0x0284f6b0`；SimpleURLLoader redirect `0x025cf640`。

重定向交叉核对：目标映像 URLLoaderClient vtable 的 redirect 槽指向 `0x025cf640`。
未设置回调时 `0x025cf719` 不跳转，进入 `0x025cf724`，最终 `0x025cf827` 调用
URLLoader 的 FollowRedirect 序列化入口 `0x00a00b40`。该入口写入 Mojo 方法编号
`0x128a78af`；结构与 [Chromium 142 的 SimpleURLLoader 源码](https://chromium.googlesource.com/chromium/src/+/142.0.7444.175/services/network/public/cpp/simple_url_loader.cc)
一致。原生 Aha DoRequest 未设置重定向拦截回调，不能用 HTTPX 默认拒绝重定向替代。

## 验收边界

尚未验收全新硬件的线上注册分配、线上激活、真实账号绑定或签到。本轮不改变此前
“先不连接线上服务”的范围。HTTPX 适配器还原状态机需要的零/非零网络错误语义，
不复刻 TTNet 的完整错误编号、TLS 指纹和所有传输细节；JSON 浮点数值语义有原始指令
基准，但不宣称所有 HTTP 字节的序列化都与 Chromium 完全相同。
Windows API 的异常驱动输出、任意非法输入和原生内存安全缺陷也不属于已证明一致的范围。
这些限制不影响本轮已经完成的真实缓存命中、缓存格式及指定离线状态机验收。
