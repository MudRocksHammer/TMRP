# TMRP 现场线路监控客户端

C++17 / Qt 6 Widgets 桌面客户端，通过 WebSocket 接收服务器监控网关的实时快照，通过 HTTP 发送控制指令。

当前仅客户端已切换到 WebSocket，仓库内服务器尚未实现 `/api/stream`。因此本版本暂时不能从现有服务器接收遥测；需要服务器后续实现下述推送协议。客户端不会回退到 HTTP 轮询。

## 界面操作

- 默认进入运行模式。断路器图形：红色实心为合闸，绿色斜线为分闸，灰色为离线或未知。
- 点击设备查看电压、电流、功率、频率、数据质量、UTC 采样时间和最近 60 个采样点的功率趋势。未收到真实数据时显示空值。
- 点击“编辑线路图”，用“选择 / 拖动”移动设备，位置按 20 单位网格吸附。
- 用“添加断路器”点击空白处，填写设备 ID 和断路器 ID，需与服务器白名单和模拟器配置一致。
- 用“连接设备”依次点击两台设备创建折线，再次点击起点取消。连线随设备移动。
- 编辑模式下右键可以修改绑定、删除设备连线或删除图中设备。删除图形不发送实际设备指令。
- 用“保存线路图 / 载入线路图”保存和恢复 JSON 布局；“适应画面”显示全部设备。布局只包含 ID、位置和连线，不包含令牌与遥测。
- 退出编辑模式后，右键在线设备选择“分闸 / 合闸”，核对设备和断路器后确认发送。离线、数据过期或指令处理中时不能操作。
- 下方控制记录显示指令 ID、提交、受理、完成、拒绝、失败或结果未知。发送成功不代表设备执行成功；图形状态只根据遥测更新。超时不自动重发。

线路只表达现场示意连接，不计算带电范围、保护逻辑或潮流。设备自身仍负责本地/远方模式及闭锁校验。

## 服务器网关启动

新增 `myproj.app.monitor_gateway`，与原 `tmrp-receiver` 并行运行并共用 MQTT broker。原接收器继续负责入库；网关提供实时转发和控制，不查询数据库历史。

```text
设备 ── telemetry ──> MQTT broker ──> 原接收器 / PostgreSQL
                           └──> 监控网关 ── WebSocket 快照（待服务器实现）──> Qt 客户端
设备 <── commands ── broker <── 网关 <── HTTP 控制请求 ── 客户端
设备 ── command-results ──> broker ──> 网关 ──> 客户端控制记录
```

在已安装本项目依赖的 Python 3.12 环境，从仓库根目录执行（Linux 服务器示例）：

```bash
export PYTHONPATH=src
# 生成并妥善保存令牌，用于客户端连接。不要将实际令牌提交到 Git。
export TMRP_MONITOR_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m myproj.app.monitor_gateway \
  --equipment monitor-client/config/equipment.example.json \
  --mqtt-host 127.0.0.1 --mqtt-port 1883 --port 8081
```

Windows PowerShell 可设置 `$env:PYTHONPATH = 'src'` 和 `$env:TMRP_MONITOR_TOKEN`，再执行同一个 Python 模块。令牌至少 24 字符，客户端填写相同的值，也可从 `TMRP_MONITOR_TOKEN` 环境变量读取；客户端不保存令牌。

`config/equipment.example.json` 是设备 ID 到断路器 ID 的白名单，默认两台设备对应模拟器配置。增加设备需修改映射并重启网关。客户端布局与此映射不一致时，设备不能控制。

MQTT 认证使用 `--mqtt-username` 与 `TMRP_MQTT_PASSWORD` 环境变量。远程 broker 需要 `--ca-file` 验证 TLS，或使用本机 SSH 隧道。MQTT 用户需有订阅遥测和结果、发布设备 `/commands` 的权限，订阅需授予 QoS 1。

网关仅监听服务器本机 `127.0.0.1`。在客户端计算机建立 SSH 隧道：

```bash
ssh -N -L 8081:127.0.0.1:8081 user@your-server
```

客户端填写 `http://127.0.0.1:8081` 和令牌，点击“连接服务器”。也支持用户配置的 HTTPS 反向代理根地址，使用系统证书验证，不忽略 TLS 错误、不跟随重定向。地址不带路径。

## 协议与状态

- `WebSocket /api/stream`（客户端约定，服务器待实现）：根地址的 `http` 自动转换为 `ws`，`https` 自动转换为 `wss`，升级请求携带 `Authorization: Bearer <token>`。仍在界面填写 HTTP/HTTPS 根地址，用于同时确定控制接口地址。
- 每条 WebSocket 消息为完整的 JSON 文本快照，结构沿用原 `GET /api/snapshot` 的响应：`mqtt_ready`（布尔）、`devices`（数组）、`commands`（数组）。设备与命令条目结构不变，不能只推送增量。首次连接和重连后立即推送完整快照，之后有变化即推送；空闲时也需至少每 3 秒重复推送一次快照，满足客户端 5 秒超时窗口。WebSocket ping/pong 不代替快照。
- 示例：`{"mqtt_ready":true,"devices":[{"device_id":"power-meter-001","equipment_id":"breaker-001","online":true,"telemetry":{"boot_id":"boot-1","sequence_no":1,"active_power_kw":12.5}}],"commands":[]}`。控制回执同样通过快照中的 `commands` 推送。
- 连接失败、断开、无效消息或 5 秒未收到有效快照时，立即标记设备离线并禁用控制，2 秒后自动重连。主动断开不重连。重连不会重发控制指令，相同采样按 `boot_id` 和 `sequence_no` 去重。单条消息上限为 4 MiB。
- `POST /api/commands`：继续使用 HTTP；JSON 包含 `command_id`（UUID）、`device_id`、`equipment_id`、`operation`（`open_breaker` / `close_breaker`），要求 `Authorization: Bearer <token>`。
- 网关增加 `schema_version: 1.0`、`message_type: command`、UTC `issued_at`、15 秒后的 `expires_at`，以 QoS 1、非 retained 发布到 `tmrp/devices/{device_id}/commands`，兼容现有模拟器协议。
- 网关订阅 `tmrp/devices/+/telemetry` 和 `tmrp/devices/+/command-results`。遥测复用 `PowerValidator`，丢弃 retained、重复与乱序采样。结果需匹配设备、断路器、指令 ID 和协议类型。
- 10 秒无新遥测，或采样时间距离服务器时钟超过 15 秒时标记离线；客户端 5 秒未获得有效快照也标记设备过期。设备与服务器需要时钟同步。
- 指令 20 秒未获终态时标记 `unknown`，迟到的有效终态仍可更新结果。相同 ID 在缓存内重复提交不会再次发布。
- 网关状态保存在内存，最多 500 条控制记录，重启后清空；不是持久审计系统。客户端记录仅在当前会话内保留。设备端已有持久指令去重。未知结果需核实设备状态，不应假设操作失败。

## 构建运行

需要 CMake、C++17 编译器和 Qt 6.4 以上 Widgets、Network、WebSockets；默认构建测试还需 Qt Test。将 Qt 路径替换为实际安装位置，也可在 Qt Creator 中打开 `CMakeLists.txt`。

```powershell
cmake -S monitor-client -B monitor-client/build -DCMAKE_PREFIX_PATH="C:/Qt/6.8.3/msvc2022_64"
cmake --build monitor-client/build --config Release
& "C:/Qt/6.8.3/msvc2022_64/bin/windeployqt.exe" monitor-client/build/Release/tmrp-monitor-client.exe monitor-client/build/Release/test_monitor_diagram.exe monitor-client/build/Release/test_monitor_stream.exe
& ./monitor-client/build/Release/tmrp-monitor-client.exe
```

Linux 上可运行 `monitor-client/build/tmrp-monitor-client`。可以通过 `TMRP_MONITOR_FONT` 指定本机中文字体文件。

## 验证

```powershell
python -m pytest tests/units/app/test_monitor_gateway.py -q
ctest --test-dir monitor-client/build -C Release --output-on-failure
```

Windows 无窗口测试需要 Qt `platforms/qoffscreen.dll`（可从 Qt 安装目录复制到可执行文件的 `platforms/` 目录）。客户端流测试使用本地 `QWebSocketServer`，验证认证请求、快照接收、异常消息、断线重连、主动断开与数据超时。网关测试使用模拟 MQTT 发布器和真实本机 HTTP 请求，覆盖鉴权、指令映射、重复提交、离线禁控、回执匹配及超时；不代替远程服务器和实际设备的联调。
