# Aha 设备服务：离线逆向记录

## 证据与结论

目标为本机 `D:\Users\marcus\AppData\Local\Programs\Trae CN\Trae CN.exe`，SHA-256 `eac5743ab3eafa528ae766a11a814cd0d8ea1c54cb948c66027e71479fe00ede`；以下原生代码地址均为 PE RVA。静态分析使用 PE 异常表、RIP 相对地址交叉引用及 x64 反汇编，不读取或展示本机真实 ID，不调用注册和签到服务。源码级准确性及其他版本适用性未验证。

结论：`ahaDeviceService.getDeviceId()` 涉及设备注册、缓存及设备信息。生成一个 UUID 与获取已注册的远程 `device_id_str` 是不同的事。目前没有足够证据声称本地合成值符合服务端要求；也不能证明完整硬件信息是服务端风控依据。

## 路径

1. 客户端 `out/main.js` 的设备注册服务调用 Electron `ahaDeviceService.getDeviceId`，签到使用 `guaranteedDeviceId`，优先异步返回的设备 ID，本地 ID 是回退。
2. EXE 的 `electron_browser_device_service` 字符串及绑定位于文件偏移 `0xaa3327d`；对应源码路径字符串 `aha/electron/shell/browser/api/electron_api_device_service.cc`。这是原生绑定，并非 `@vscode/deviceid` 的实现；后者虽然也使用 UUID，但没有证据表明是签到设备 ID 的实现。
3. `CalcLocalDeviceId` 的日志引用所在函数为 RVA `0x1d5ee60`。它调用 RVA `0x1d370d0` 获取设备信息对象，非空时调用 `0x1d384b0` 获取 UUID 并保存，另有 `local_device_id use Uuid` 回退分支。尚未解出该回退函数具体算法和生命周期。
4. Windows 设备信息初始化代码 RVA `0x1d39fe0` 使用 `GetSystemFirmwareTable`，provider 签名是 `RSMB`，读取原始 SMBIOS 数据。由 C++ 虚表项解析可见获取 UUID 调用 `0x1d3aaf0`；它按 UUID 的字段字节序输出大写 `%02X...` 格式，等价于 Python `str(uuid.UUID(bytes_le=raw_16_bytes)).upper()`。例如字节 `00112233445566778899aabbccddeeff` 对应 `33221100-5544-7766-8899-AABBCCDDEEFF`。此结论是对本版本 Windows 分支的静态解读。
5. 设备服务常量字符串位于文件偏移 `0xbd80df0` 起，含 `BuildRegisterDeviceRequest`、`RegisterDevice`、`ParseRegisterDeviceResponse`、`device_id_str`、`install_id_str`、`ActiveDevice`。注册请求的可见参数模板含 `aid`、`channel`、`os`、`os_version`、`device_platform`、`version_code`，另有 `pc_uuid`、`pc_serial` 等字段；还出现 `magic_tag`、`ss_app_log`、时区和设备型号。单凭字符串不能确定每个字段的编码、值、是否始终发送或它们各自的校验意义。
6. 同区域字符串出现 `SELECT UUID FROM Win32_ComputerSystemProduct`、无效 UUID（全 0／全 F）、磁盘序列号采集、MAC 缓存、`aha.device.device_id`，及“cache uuid is not equal system uuid or cache did is local did”。这支持设备服务存在硬件信息采集与缓存一致性检查；字符串本身不能证明具体分支顺序、所有字段的服务端用途或缓存加密格式。
7. `device_id_str`、`install_id_str` 出现在注册响应解析及缺失字段错误附近，支持其由注册响应提供。注册 URL 的实际来源、完整请求与响应结构、设备 ID 的服务端分配规则和验证规则仍需进一步还原。无法离线证明合成 ID 已注册或者能用于签到。

## 离线候选与账号关联

`trae2api/device_identity.py` 为指定的非秘密账号标识创建独立且持久化的虚拟 SMBIOS UUID（随机 UUIDv4，经 SMBIOS 字节序输出），只模拟第 4 步的 UUID 格式转换。它**不是**对 `getDeviceId` 的完整复刻，不进行注册、激活或服务端通信；不会自动修改签到凭据或替换 `x-device-id`。合成 UUID 是测试候选值，输出明确标记 `registered: false`、`server_accepted: unknown`。

```powershell
python -m trae2api.device_identity --account-id account-A --directory D:\workspace\trae2api\device-profiles
```

使用同一个账号标识和目录会复用同一值，不同账号创建独立值。账号标识使用 SHA-256 作为文件名索引，不应传入 token、手机号等敏感值；简单 ID 的哈希可被猜测。备份 profile 目录可保持稳定，删除或丢失后新生成的值会不同。生成过程无网络请求；文件创建基于硬链接的原子发布，文件系统不支持硬链接时会报错。不要将这些候选值误认作已被 Aha 注册的设备 ID。

## 后续缺口

- 跟进 `BuildRegisterDeviceRequest`、网络配置、序列化和响应状态机，确认注册及激活 URL、JSON 形状、缓存键与绑定关系；逐项标注静态证据，不能由字段名推断。
- 进一步定位 UUID 为空时的生成与持久化算法、WMI 和 SMBIOS 选择条件，以及设备服务如何回退。
- 建立本地假服务和合成账号数据做回归，不连接真实服务。只有得到用户后续授权的线上观察，才能验证远程是否接受、结果是否持久和账号绑定关系。

离线测试：`D:\workspace\workbuddy2api\.venv\Scripts\python.exe -m pytest tests/test_device_identity_offline.py tests/test_checkin_offline.py -q`。
