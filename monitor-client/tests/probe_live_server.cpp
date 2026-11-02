#include "serverprotocol.h"
#include "telemetrystream.h"
#include <QCoreApplication>
#include <QJsonArray>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QTimer>
#include <QUuid>
#include <cstdio>

// Runs against the isolated receiver/broker/Qt simulator started by pytest.
int main(int argc, char **argv) {
    QCoreApplication app(argc, argv);
    if (!ServerProtocol::loadCaFile(qEnvironmentVariable("TMRP_MONITOR_CA_FILE"))) return 2;
    const QUrl server(qEnvironmentVariable("TMRP_MONITOR_TEST_URL"));
    const QByteArray token = qgetenv("TMRP_API_CONTROL_TOKEN");
    if (server.isEmpty() || token.isEmpty()) return 2;
    TelemetryStream stream;
    QNetworkAccessManager network;
    const QString device = "power-meter-001";
    QString id;
    int stage = 0;
    bool submitted = false, acknowledged = false, completed = false;
    QTimer::singleShot(25000, &app, [&] { std::fprintf(stderr, "Live flow timed out at stage %d\n", stage); app.exit(3); });
    QObject::connect(&stream, &TelemetryStream::unavailable, &app, [&](const QString &why) {
        qWarning("Stream unavailable: %s", qPrintable(why));
    });
    QObject::connect(&stream, &TelemetryStream::snapshotReceived, &app, [&](const QJsonObject &snapshot) {
        if (!snapshot["control_allowed"].toBool() || !snapshot["mqtt_ready"].toBool()) return;
        QJsonObject telemetry;
        for (const auto &entry : snapshot["devices"].toArray()) {
            const auto row = entry.toObject();
            if (row["device_id"] == device && row["online"].toBool()) telemetry = row["telemetry"].toObject();
        }
        if (telemetry.isEmpty()) return;
        for (const auto &entry : snapshot["commands"].toArray()) {
            auto result = entry.toObject();
            if (result["command_id"] == id && result["status"] == "completed") completed = true;
        }
        const QString expected = stage == 0 ? "open" : "closed";
        if (submitted && acknowledged && completed && telemetry["breaker_state"] == expected) {
            if (stage == 1) {
                std::puts("PASS: Qt WSS telemetry -> HTTPS open/close -> Qt equipment -> durable results -> WSS state");
                stream.stop(); app.exit(0); return;
            }
            stage = 1; submitted = false; acknowledged = false; completed = false;
        }
        if (submitted) return;
        id = QUuid::createUuid().toString(QUuid::WithoutBraces);
        submitted = true;
        auto *reply = network.post(ServerProtocol::commandRequest(server, token, device),
            ServerProtocol::commandBody(id, stage == 0 ? "open_breaker" : "close_breaker"));
        QObject::connect(reply, &QNetworkReply::finished, &app, [&, reply] {
            reply->deleteLater();
            const auto body = QJsonDocument::fromJson(reply->readAll()).object();
            if (reply->error() != QNetworkReply::NoError || reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt() != 202
                || !ServerProtocol::matchesCommand(body, device, id)) {
                qWarning("Command failed: %s", qPrintable(reply->errorString())); app.exit(4); return;
            }
            acknowledged = true;
        });
    });
    stream.start(server, token);
    return app.exec();
}
