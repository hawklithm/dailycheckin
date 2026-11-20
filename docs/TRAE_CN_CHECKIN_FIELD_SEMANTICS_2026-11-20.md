# 签到字段语义与设备限制复核

2026-11-20 直接复核当前安装的 Trae CN 3.4.20 源文件。未修改原生客户端。
原文片段、文件 SHA-256 和零起始字符偏移保存在
`TRAE_CN_CHECKIN_FIELD_EVIDENCE_2026-11-20.json`。

## 原生字段语义

`node_modules/@byted-icube/webcomponents/dist/index.js` 的 `renderCheckin()`：

- `checked_in` 映射到 `checkedIn`，表示账号今日已签到。
- `did_checked_in` 映射到 `didCheckedIn`；当它为 true、`checkedIn` 为 false 时，
  原生选择 `trae.ide.checkin.deviceLimitTooltip`，英文默认文案为
  `This device has checked in today. Come back tomorrow.`。
- 其他已签到状态选择 `trae.ide.checkin.claimedTooltip`，英文默认文案为
  `This account has checked in today. Come back tomorrow.`。
- 任一个字段为 true 都禁用签到按钮；点击处理也检查两者。

Workbench 的 `claimIdeCheckinCredits()` 要求 `enable === true`、
`checkedIn === false`、`didCheckedIn !== true`，另有状态就绪、账号范围和业务错误检查。
主进程抽奖控制器的 `_1e()` 也将任一字段为 true 归类为 `signed`；
这是活动参与判定，不能单凭设备字段证明当前账号已领取积分。

因此 `checked_in=false, did_checked_in=true` 是原生明确处理的设备限制状态，
不是两个字段矛盾。此处仅确认原生客户端的字段解释，未还原服务端的设备识别或去重算法。

## Python 修正

原有跳过领取的条件与原生一致，予以保留。修正两处语义混用：

1. 账号 `checked_in=true` 继续返回 `already_checked_in`；
   只有设备字段为 true 时改为 `device_already_checked_in`，并保留状态字段供诊断。
2. claim 被接受后，仅当复查 `checked_in=true` 才返回 `verified=true`。
   若仅设备字段为 true，则保留 `claim_accepted, verified=false`，不重试领取。

`verified` 仍只确认账号签到标记，不能证明实际余额增加。

## 本轮验证

离线命令：

```powershell
& 'D:\Users\marcus\anaconda3\python.exe' -m pytest tests/test_independent_login.py tests/test_native_identity.py tests/test_checkin_offline.py tests/test_checkin_profile.py tests/test_client_metadata.py tests/test_gateway_body.py -q
```

结果：exit code 0，**82 passed in 5.30s**。包括设备限制不报成账号签到、
两字段组合与领取后确认不会因设备字段误报成功的针对性回归。

2026-11-20 09:51（UTC+8）使用当前原生账号调用修正后的执行流程：

- 登录凭据成功加载，设备证据匹配；与旧独立凭据对应不同账号。
- 状态接口 HTTP 200：`enable=true, checked_in=false, did_checked_in=true`。
- 结果：`action=device_already_checked_in`。仅一次 status 请求，**零次 claim 请求**。
- 原生逻辑此时同样阻止领取。本轮没有新账号签到成功的证据，也没有绕过设备限制。
- 独立凭据文件字节未改变，未刷新 token、注册设备、导出凭据或修改原生存储。

脱敏执行报告：`logs/checkin-validation-20261120/field-fix-attempt-095102.json`（Git 忽略）。
