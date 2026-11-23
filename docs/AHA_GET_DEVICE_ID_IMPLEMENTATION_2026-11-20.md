# Trae CN getDeviceId：开源组件比对与独立实现

> 当前实现与验收以 [原生模式还原与验收](AHA_GET_DEVICE_ID_NATIVE_PARITY_2026-11-20.md)
> 为准。本文保留首版实现时的分析与结论，后续已补齐原生缓存格式及生命周期。

日期：2026-11-20。安装包基线：Windows x64 Trae CN 3.4.20。

> 后续已补入硬件回退、REG_BINARY MAC 缓存、设备记录校验及异步等待逻辑。
> 当前实现和验证边界以 `AHA_GET_DEVICE_ID_ALIGNMENT_2026-11-20.md` 为准。
> 以下保留首版实现及其验证记录。

## 结论与公开来源

安装包同时存在两条不同的设备 ID 链路：

1. **`@vscode/deviceid 0.1.1`**：Microsoft 的 MIT 开源组件。安装包中的
   `out-build/vs/base/node/id.js` 通过动态 import 调用它。
2. **`electron/main.ahaDeviceService`**：`iCubeDeviceRegisterMainService` 实际调用的
   Aha 原生设备服务。签到所用主设备 ID 来自这条链路。

截至本次检索，未找到与当前 Aha 原生 DeviceService 对应、可核对版本的公开源码。
这不构成对其法律许可性质的断言；能确定的是，不能用 Microsoft 的组件替代此服务。
安装包声明 Electron 为 `npm:@aha-kit/electron@39.2.7-release.1.61.0`，仅有 Electron
上游源码也不足以证明这个扩展已公开或与上游相同。

公开原始来源：

- [Microsoft 仓库](https://github.com/microsoft/vscode-deviceid)。
- [getDeviceId 源码，固定提交](https://github.com/microsoft/vscode-deviceid/blob/bf3dad415c89d574e5ebb0f194ce54c0d17913cf/src/devdeviceid.ts)。
- [Windows 存储源码，同一提交](https://github.com/microsoft/vscode-deviceid/blob/bf3dad415c89d574e5ebb0f194ce54c0d17913cf/src/windows.cc)。
- [npm 0.1.1 版本元数据](https://registry.npmjs.org/@vscode%2Fdeviceid/0.1.1)。

当前仓库源码用于辅助理解，不冒充 0.1.1 的精确源码标签。精确版本比对使用 npm 发布的
0.1.1 归档，校验其发布元数据中的 SHA-1，再与本机安装文件比较。
完整文件摘要在 `DEVICEID_OPEN_SOURCE_COMPARISON_2026-11-20.json`。

## 文件与行为比对

| 项目 | 结果 |
| --- | --- |
| `dist/devdeviceid.js` | 原始字节不同；移除 sourceMappingURL 注释、统一换行并去除首尾空白后，与 npm 0.1.1 完全相同 |
| `dist/storage.js` | 同上；没有修改可执行代码来获得相同结果 |
| `LICENSE.txt` | 字节完全相同，MIT |
| 安装的 `build/Release/windows.node` | npm 归档中没有同路径文件，未声称二进制完全一致 |
| Aha 原生 DeviceService | 与上述 JS 组件不一致，证据来自 EXE 反汇编及实际调用关系 |

| 行为 | Microsoft deviceid | 当前 Aha 原生服务 |
| --- | --- | --- |
| 主 ID 来源 | 本地生成随机 UUID v4 并保存 | 注册响应的 `device_id_str`；同时有 `install_id_str` |
| Windows 存储 | 公开源码使用 HKCU 的 Microsoft/DeveloperTools 注册表项 | TinyStorage 的 `aha.device.device_id`，含编码/加密层 |
| 硬件字段 | 核心生成函数不读取硬件 | 注册提交 UUID、磁盘序列号、MAC 等上下文 |
| 缓存验证 | 读取已有字符串，缺失/读取失败则生成 UUID | 解码记录、版本及非零 ID 检查，缓存 UUID 与当前硬件 UUID 比较 |
| 网络注册/激活 | 无 | 有；注册成功先保存缓存，再进入激活 |
| 本地备用 ID | 所生成 UUID 就是该组件的返回值 | 另有 localDeviceId，通常来自硬件 UUID，与服务端数字 ID 分开 |

原生证据复核基线：EXE SHA-256
`eac5743ab3eafa528ae766a11a814cd0d8ea1c54cb948c66027e71479fe00ede`。
入口和关键 RVA：桥接 `0x004c29f0`，getter `0x0284a040`，注册 `0x0284a240`，
响应解析 `0x0284c490`，缓存解码/验证 `0x0284c9e0`。
逐段证据见 `AHA_DEVICE_CACHE_STATIC_EVIDENCE_2026-11-20.json`，完整解释见
`AHA_GET_DEVICE_ID_STATIC_REVIEW_2026-11-20.md`。

## 我们的独立实现

新增 `trae2api/aha_device_service.py` 的 `AhaDeviceService.get_device_id()`，并让现有
`TraeLoginFlow.prepare_device()` 调用它，集中处理以下状态：

```text
读取真实硬件 → 加锁读取独立档案 → 检查缓存硬件 UUID
  ├─ 已注册：返回缓存中的数字设备 ID
  └─ 未注册：默认只返回单独的本地备用 ID
       └─ 显式允许网络且传入 HTTP client：注册并保存服务端返回的 ID
            └─ 调用方要求激活：激活成功后再保存 activated=true
```

- 返回对象分别提供 `device_id`、`install_id`、`local_device_id`、`guaranteed_device_id`。
  未注册时前两个是 `"0"`，备用 UUID 不会被标记成注册成功。
- 默认不创建 HTTP client、不请求网络。即使传入 client，也需要显式打开 `allow_network`。
- `require_activation` 与获取 ID 分开；缓存存在不能证明已激活。现有登录流程显式要求激活。
- 注册后先保存，激活失败保留设备 ID 和安装密钥，下次只补激活。
- 新建/迁移的安装身份会持久化；旧档案里的未验证 ID 不会直接作为已注册 ID 返回。
- 使用既有独立 `.device.secret` 文件及原子写入/排他锁。硬件不符或档案损坏时明确报错，
  不自动轮换设备身份。P-256 属于我们的登录安装身份，不代表 Aha 提供了硬件可信证明。

离线调用示例（会创建自己的安装身份文件，不接触原生缓存）：

```python
from pathlib import Path
from trae2api.aha_device_service import AhaDeviceService
from trae2api.login_identity import IdentityStore

service = AhaDeviceService(IdentityStore(Path("local.account.json")))
result = service.get_device_id()
# result.source 为 local/cache；本地备用 UUID 与远程数字 ID 是不同字段。
```

## 与原生完整 SDK 的边界

这是按已确认行为写出的独立同步实现，复用已有注册请求构造器及真实硬件读取器，
不是原生 SDK 的二进制兼容克隆：

- 不读取、解密或写入原生 TinyStorage；独立档案格式版本仍为 1，不冒充 Aha 的记录版本 1.2。
- 不模拟尚未确认的服务端设备分配、硬件去重算法，数字 ID 必须由注册响应提供。
- 未复制启动地区/配置触发的刷新、旧 ID 参数迁移、回调队列、超时与后台重试调度。
  本地同步接口在网络错误时抛错，调用方可另行执行默认离线读取。
- 既有硬件读取器与原生仍有差异：当前没有原生 WMI UUID 回退、磁盘多候选回退，
  也没有原生 HKCU MAC 缓存逻辑。无法读取必要 UUID 时失败，不生成新硬件身份替代。
- 注册响应采用本项目原有的更严格检查：device/install ID 都必须是正十进制字符串。
  这不代表反汇编证明了原生对这两个字段做完全相同的检查。

## 验证

新增 `tests/test_aha_device_service.py`，使用固定的测试硬件和 `httpx.MockTransport`，
并禁止该测试模块通过真实 HTTP transport 发请求。覆盖默认离线、缓存重用、
注册/激活分离、先保存后激活、激活恢复、注册失败、迁移的未验证 ID、硬件不符、
损坏档案、排他锁以及缺失硬件 UUID。

新增服务测试与原有独立登录测试：**29 passed**。
包含本地实验室、独立登录、设备签名、签到判断和请求构造的指定离线回归：
**235 passed in 15.31s**。命令如下（未运行包含线上探测的整个 tests 目录）：

```powershell
D:\Users\marcus\anaconda3\python.exe -m pytest tests/test_aha_device_service.py tests/test_sandbox_lab_config.py tests/test_sandbox_lab_client.py tests/test_sandbox_lab_runner.py tests/test_sandbox_lab_binding.py tests/test_independent_login.py tests/test_native_identity.py tests/test_checkin_offline.py tests/test_checkin_profile.py tests/test_client_metadata.py tests/test_gateway_body.py tests/test_device_identity_offline.py -q
```

本轮网络访问仅用于公开源码/公开包的检索比对；未执行真实设备注册、激活、账号绑定或签到。
