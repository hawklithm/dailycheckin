# 签到脚本的原生 deviceId 来源选择

> 历史记录：此文描述旧行为。当前 `get-device-id` 是默认值，使用项目按账号保存的设备，不再读取原生设备缓存或会话日志；`existing` 使用原生设备。最新用法见项目 README。

`python -m trae2api.checkin` 在 `--native` 模式下支持
`--device-id-source existing|get-device-id`。未提供时默认为 `existing`，保持原有行为。
该参数不能与 `--creds` 搭配。

支持模块方式 `python -m trae2api.checkin`，也支持 PyCharm 直接运行
`trae2api/checkin.py`。在 PyCharm 运行配置的参数栏填写
`--native --device-id-source get-device-id --status-only`；不带参数会显示必需参数提示。

| 选项 | deviceId 来源 |
| --- | --- |
| `existing` | 原生客户端最新会话 main.log 中的 `resolve rdid`，保留初始化完成/本地回退校验 |
| `get-device-id` | 自研 `NativeAhaDeviceService.get_device_id()`；通过原生缓存解码和当前硬件 UUID 校验加载 TinyStorage 记录 |

两种模式均读取当前原生登录身份，检查存在对应 deviceId 的原生 OAuth 设备记录，
并在每次签到请求前按所选来源重新核对账号、设备、会话与地区。该检查只确认本地记录
一致性，不能替代服务端对设备与账号绑定关系的验证。

自研模式使用同一原生用户数据目录：优先 `TRAE2API_USER_DATA`，否则
`%APPDATA%/Trae CN`。TinyStorage 只读，支持现有的旧 Preferences 读取逻辑，
不创建独立安装身份档案。缓存无效、缺失或硬件不匹配会报错；不切回日志中的 ID、
不把本地 UUID 用于签到，也不自动注册新设备。原生日志仍用于取得会话和 store region，
自研模式不要求日志包含 deviceId 的 resolve 记录。

查询状态，使用已有 ID：

```powershell
python -m trae2api.checkin --native --device-id-source existing --status-only
```

查询状态，使用自研 getter：

```powershell
python -m trae2api.checkin --native --device-id-source get-device-id --status-only
```

需要实际签到时，将 `--status-only` 替换为 `--execute`。两者均不提供时是 dry run，
不会读取登录凭证或设备缓存，也不会发送请求。

代码入口：`trae2api/checkin.py` 的 `main` / `Account.from_native`；
`trae2api/native_identity.py` 的 `NativeIdentity.load` / `_implemented_device_id`。
新增选项的验证使用合成凭证、临时缓存及 HTTP MockTransport，没有运行线上签到。
指定回归：`test_native_identity`、`test_checkin_offline`、`test_checkin_profile`、
`test_aha_device_service`、`test_aha_tiny_storage`、`test_aha_native_lifecycle`，
共 **132 passed**；记录位于 `logs/checkin-device-id-source-20261120.xml`。
