# Telemetry Message Contract

## Purpose

TelemetryMessage表示IoT设备在特定时间产生的一条遥测消息。

## Time

event_time使用ISO 8601格式，并且必须包含时区。

系统内部统一使用UTC。推荐格式：

2026-09-28T05:30:15.123Z

event_time表示设备产生消息的时间，不是Collector收到消息的时间。

## Required Fields

- schema_version
- device_id
- sequence_no
- event_time
- message_type

## Optional Measurement Fields

以下字段允许为null：

- battery_percent
- temperature_c
- network_rssi

status_flags缺失时是否自动使用空数组，将由数据模型决定。

## Validation Rules

- schema_version当前必须为1.0
- device_id不能为空
- sequence_no必须大于或等于0
- event_time必须是包含时区的ISO 8601时间
- battery_percent必须在0至100之间
- status_flags中的每个元素必须是字符串

## Unknown Fields

初期版本拒绝未知字段。

这样可以尽早发现字段拼写错误和协议不一致。未来需要兼容新字段时，再重新评估这一规则。

## Units

- battery_percent: 百分比
- temperature_c: 摄氏度
- network_rssi: dBm

## Message Identity

初期使用device_id和sequence_no的组合作为消息唯一标识。

同一设备不能重复使用sequence_no。