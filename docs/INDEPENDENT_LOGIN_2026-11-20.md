# 独立登录补齐：设备注册与稳定身份

本轮保留原生客户端、`checkin --native` 和现有凭据文件。修改的是独立 login 及其设备配置。
没有从原生登录读取 token、设备 ID 或设备私钥来生成独立凭据。

## 新流程

1. 根据 `--creds` 路径加载独立设备配置；首次生成并持久化 machine ID 和 P-256 密钥。
2. 读取真实 Windows SMBIOS UUID、磁盘序列号、MAC、型号、制造商和 CPU 品牌。
3. 没有注册缓存时调用 Aha 设备注册接口，要求服务端返回有效的 device_id_str/install_id_str。
   不再将随机 14 位字符串当作已注册设备 ID。
4. 激活返回 message=success、data.is_activated=1 后标记激活完成。
5. 用同一组设备 ID、machine ID、公钥打开官方 PKCE 登录页并交换授权码。
6. 成功获取 UserID 后，才原子替换指定的独立凭据文件。

设备配置保存在凭据文件旁的 `<文件名>.device.secret`，包含私钥，已有 `.gitignore` 的
`*.secret` 会排除它。该文件需保留，重复登录复用 ID/密钥，只更新 PKCE 和登录 trace。
原生凭据文件不在此流程的读写路径中。

旧独立凭据中的 machine ID 和私钥会在迁移时读取；旧设备 ID 仍标为未验证。
首次注册获得不同远端 ID 时，创建与该新 ID 配对的独立密钥；原凭据文件保持到新登录成功。
损坏的设备配置不会被静默重建；硬件 UUID 改变时要求使用另一条凭据路径。

## 已确认的注册协议

原生版本：Trae CN 3.4.20，EXE SHA-256：
`eac5743ab3eafa528ae766a11a814cd0d8ea1c54cb948c66027e71479fe00ede`。

原生启动配置提供：aid=787976、channel=stable、package=com.trae.app、language=zh-CN。
以下地址均由该配置获得，而非猜测路径：

| 操作 | POST 地址 |
|---|---|
| 注册 | https://log.snssdk.com/service/2/desktop/device_register/ |
| 激活 | https://log.snssdk.com/service/2/app_alert_check/ |

本轮进一步定位的 PE RVA：

- BuildRegisterDeviceRequest：0x284a710–0x284b430。
- RegisterDevice：0x284a240–0x284a5ce。
- DoRequest：0x2849d30 起。
- 设备硬件信息构造：0x2846a70–0x28489cd；Windows/PC 初始化在 0x2846bec–0x2846c0c。
- mc 字段写入：0x284ac5e；原生设备 MAC 使用 GetAdaptersAddresses，并以大写十六进制和连字符格式输出。
- 注册响应 device_id_str/install_id_str 解析：0x284c490–0x284c81e。

注册 URL 参数包括 aid/channel/os/os_version/device_platform/version_code/pc_uuid/pc_serial。
注册层使用 **Windows / PC**，与 OAuth DeviceInfo 的 OSInfo=windows、DeviceType=PC 要区分。
JSON header 包含 device_id、install_id、aid、os、device_platform、mc、channel、package、language、
app_version、os_version、device_model、时区、app_region、app_language、display_name、pc_uuid、pc_serial；
外层包含 header、Unix 毫秒 _gen_time 和 magic_tag=ss_app_log。

原生 RegisterDevice 的压缩调用对应 deflateInit2(-1, 8, 31, 9, 0)，即 gzip framing。
独立 HTTP 请求必须明确发送 `Content-Encoding: gzip` 和 `Content-Type: application/json`。
本轮真实验证中，缺少 gzip 声明时 HTTP 200 但 device_id/install_id 为零；加入后返回有效的
device_id_str/install_id_str。原生底层在哪一层附加此头尚未捕获，不能把这项结果写成完整 wire 等价。

## OAuth 与文件处理修复

- `--creds` 现已真正传给登录流程；此前入口接受但忽略了此参数。
- DeviceBrand 使用制造商，DeviceCPU 使用 CPU 品牌，OSInfo/OSVersion 使用当前系统值。
- plugin_version 使用产品 tronBuildVersion（本机 2.3.103559），不同于 appVersion=3.4.20。
- 登录 HTTP 使用显式客户端 UA，避免 urllib/httpx 的 Python 默认 UA；未声称与原生 OAuth 最终 UA 已抓包比对。
- `/login-confirm`、`/login-success` 只显示等待，收到有效 AuthCode 才完成回调。
- malformed authCodeInfo 不结束登录，超时/失败/成功均关闭回调服务器。
- 用户信息请求失败或缺少 UserID 时停止，不覆盖原凭据。
- TokenExpireDuration 按当前时间加毫秒时长处理。
- 保存前复核独立设备配置未改变；使用临时私密文件与 os.replace 替换凭据。
- 独立凭据重新加载时，从持久化私钥恢复公钥，供既有 DeviceProof 逻辑使用。

本轮没有更改共享 token 刷新策略，也没有轮换原生 refresh token。

## 使用

```powershell
# 仅注册/激活并持久化独立设备，不打开浏览器、不交换登录 token
python -m trae2api login --creds .\trae2api\trae2api.json --prepare-device

# 设备就绪后进入官网授权；授权完成后才替换指定独立凭据
python -m trae2api login --creds .\trae2api\trae2api.json
```

也可以指定另一条凭据路径，设备配置与该路径配套。不要用 `--native`，它属于签到入口。

## 验证与限制

离线回归覆盖注册 gzip/body、缓存复用、激活失败恢复、无效 ID、凭据保存、CLI 参数转发、
回调确认/错误、SMBIOS 字节序和相关原生签到回归。本轮相关检查 81 项通过。
包含既有协议观测工具的最终离线回归为 **129 passed、12 subtests passed**；compileall 与
git diff --check 通过。原生签到的 native_identity/checkin/checkin_profile 实现文件未修改。

真实隔离测试路径为 `logs/independent-login-validation/`（被 Git 排除）：

- 注册和激活均成功，输出 action=device_prepared、registered=true、activated=true；
- 独立远端设备 ID 与现有原生 ID 不同；
- 原生 15 个既有进程均保留，原生状态查询仍返回已签到；
- 为观测而启动的参考实例使用另一数据目录，已关闭；它没有发生新的注册请求，不能作为注册 wire 抓包证据。

**尚未完成真实浏览器授权、真实 ExchangeToken 和新独立凭据签到验收**。
上述阶段在合成服务中通过，但不能用设备注册/激活成功代替完整登录或签到成功。
实现目前面向 Windows x64、已审查的 CN 配置；系统 API 与网络栈未完整模拟 Aha 的所有回退分支。
