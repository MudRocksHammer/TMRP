#include "deviceprofile.h"
#include "deviceengine.h"
#include <QHostAddress>
#include <cmath>

QJsonObject DeviceProfile::toJson() const {
    // Passwords belong to this session only, never to a profile export.
    return {{"name", name},
            {"device_id", connection.deviceId},
            {"equipment_id", equipmentId},
            {"host", connection.host},
            {"port", connection.port},
            {"source_ip", connection.sourceIp},
            {"username", connection.username},
            {"tls", connection.tls},
            {"ca_file", connection.caFile},
            {"rate_hz", rateHz},
            {"operation_delay_ms", operationDelayMs}};
}

DeviceProfile DeviceProfile::fromJson(const QJsonObject &json) {
    DeviceProfile profile;
    profile.name = json["name"].toString();
    profile.connection.deviceId = json["device_id"].toString();
    profile.equipmentId = json["equipment_id"].toString();
    profile.connection.host = json["host"].toString();
    profile.connection.port = json["port"].toInt(-1);
    if (json["port"].toDouble(-1) != profile.connection.port)
        profile.connection.port = -1;
    profile.connection.sourceIp = json["source_ip"].toString();
    profile.connection.username = json["username"].toString();
    profile.connection.tls = json["tls"].toBool();
    profile.connection.caFile = json["ca_file"].toString();
    if (!json["tls"].isBool() || (json.contains("source_ip") && !json["source_ip"].isString()) ||
        (json.contains("username") && !json["username"].isString()) ||
        (json.contains("ca_file") && !json["ca_file"].isString()))
        profile.connection.port = -1;
    profile.rateHz = json["rate_hz"].toDouble(-1);
    profile.operationDelayMs = json["operation_delay_ms"].toInt(-1);
    if (json["operation_delay_ms"].toDouble(-1) != profile.operationDelayMs)
        profile.operationDelayMs = -1;
    return profile;
}

QString DeviceProfile::validationError() const {
    if (name.trimmed().isEmpty() || name.size() > 128)
        return "表示名は1〜128文字で指定してください。";
    if (!DeviceEngine::validId(connection.deviceId) || !DeviceEngine::validId(equipmentId))
        return "機器ID・設備IDが不正です。";
    if (connection.host.isEmpty() || connection.host.trimmed() != connection.host ||
        connection.host.contains(QChar::Null) || connection.port < 1 || connection.port > 65535)
        return "Broker IP・ポートが不正です。";
    if (!connection.sourceIp.isEmpty() && QHostAddress(connection.sourceIp).isNull())
        return "送信元IPにはIPアドレスを指定してください。";
    if (!std::isfinite(rateHz) || rateHz < 0.1 || rateHz > 50 || operationDelayMs < 0 ||
        operationDelayMs > 30000)
        return "送信頻度は0.1〜50Hz、動作時間は0〜30000msです。";
    return {};
}
