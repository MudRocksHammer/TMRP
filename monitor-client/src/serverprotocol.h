#pragma once

#include <QFile>
#include <QJsonDocument>
#include <QJsonObject>
#include <QNetworkRequest>
#include <QSslCertificate>
#include <QSslConfiguration>
#include <QUrl>

// Shared by the UI and the real-server integration probe.
namespace ServerProtocol {
inline bool loadCaFile(const QString &path) {
    if (path.isEmpty()) return true;
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly)) return false;
    const auto certificates = QSslCertificate::fromData(file.readAll());
    if (certificates.isEmpty()) return false;
    auto config = QSslConfiguration::defaultConfiguration();
    auto authorities = config.caCertificates();
    authorities.append(certificates);
    config.setCaCertificates(authorities);
    QSslConfiguration::setDefaultConfiguration(config);
    return true;
}

inline QNetworkRequest commandRequest(QUrl base, const QByteArray &token, const QString &device) {
    base.setPath("/api/v1/devices/" + device + "/commands");
    QNetworkRequest request(base);
    request.setRawHeader("Authorization", "Bearer " + token);
    request.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
    request.setTransferTimeout(4000);
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
    return request;
}

inline QByteArray commandBody(const QString &id, const QString &operation) {
    return QJsonDocument(QJsonObject{{"command_id", id}, {"operation", operation},
                                   {"expires_in_seconds", 15}}).toJson(QJsonDocument::Compact);
}

inline bool matchesCommand(const QJsonObject &response, const QString &device, const QString &id) {
    const auto command = response["command"].toObject();
    return command["command_id"] == id && command["device_id"] == device;
}
}
