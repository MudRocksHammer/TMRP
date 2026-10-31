#include "telemetrystream.h"
#include <QJsonArray>
#include <QJsonDocument>
#include <QNetworkRequest>
#include <QSignalSpy>
#include <QWebSocket>
#include <QWebSocketServer>
#include <QtTest>

class StreamTest final : public QObject {
    Q_OBJECT
    const QByteArray token = QByteArray(32, 'x');
    const QString snapshot = QStringLiteral(R"({"mqtt_ready":true,"devices":[{"device_id":"meter-1","equipment_id":"breaker-1","online":true,"telemetry":{"sequence_no":1,"active_power_kw":12.5}}],"commands":[]})");
private slots:
    void receivesAuthenticatedSnapshotsAndReconnects() {
        QWebSocketServer server("test", QWebSocketServer::NonSecureMode);
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        QSignalSpy connections(&server, &QWebSocketServer::newConnection);
        TelemetryStream stream;
        QSignalSpy received(&stream, &TelemetryStream::snapshotReceived);
        QSignalSpy unavailable(&stream, &TelemetryStream::unavailable);
        const QUrl gateway(QString("http://127.0.0.1:%1").arg(server.serverPort()));
        stream.start(gateway, token);
        QTRY_COMPARE(connections.count(), 1);
        auto *peer = server.nextPendingConnection();
        QVERIFY(peer);
        QCOMPARE(peer->requestUrl().path(), QString("/api/stream"));
        QCOMPARE(peer->request().rawHeader("Authorization"), "Bearer " + token);
        peer->sendTextMessage(snapshot);
        QTRY_COMPARE(received.count(), 1);
        const auto data = qvariant_cast<QJsonObject>(received.at(0).at(0));
        QCOMPARE(data["devices"].toArray().at(0).toObject()["telemetry"].toObject()["active_power_kw"].toDouble(), 12.5);
        peer->sendTextMessage(snapshot);
        QTRY_COMPARE(received.count(), 2);
        peer->close();
        QTRY_COMPARE(unavailable.count(), 1);
        QTRY_COMPARE_WITH_TIMEOUT(connections.count(), 2, 5000);
        auto *reconnected = server.nextPendingConnection();
        QVERIFY(reconnected);
        reconnected->sendTextMessage(snapshot);
        QTRY_COMPARE(received.count(), 3);
        stream.stop();
        QTest::qWait(2200);
        QCOMPARE(connections.count(), 2);
        QCOMPARE(unavailable.count(), 1);
        delete peer;
        delete reconnected;
    }

    void rejectsInvalidSnapshots_data() {
        QTest::addColumn<QString>("message");
        QTest::newRow("malformed") << QStringLiteral("{");
        QTest::newRow("missing-fields") << QStringLiteral(R"({"devices":[]})");
        QTest::newRow("wrong-types") << QStringLiteral(R"({"mqtt_ready":"true","devices":[],"commands":[]})");
    }
    void rejectsInvalidSnapshots() {
        QFETCH(QString, message);
        QWebSocketServer server("test", QWebSocketServer::NonSecureMode);
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        TelemetryStream stream;
        QSignalSpy connections(&server, &QWebSocketServer::newConnection);
        QSignalSpy received(&stream, &TelemetryStream::snapshotReceived);
        QSignalSpy unavailable(&stream, &TelemetryStream::unavailable);
        stream.start(QUrl(QString("http://127.0.0.1:%1").arg(server.serverPort())), token);
        QTRY_COMPARE(connections.count(), 1);
        auto *peer = server.nextPendingConnection();
        peer->sendTextMessage(message);
        QTRY_COMPARE(unavailable.count(), 1);
        QCOMPARE(received.count(), 0);
        stream.stop();
        delete peer;
    }

    void silentConnectionTimesOut() {
        QWebSocketServer server("test", QWebSocketServer::NonSecureMode);
        QVERIFY(server.listen(QHostAddress::LocalHost, 0));
        TelemetryStream stream;
        QSignalSpy connections(&server, &QWebSocketServer::newConnection);
        QSignalSpy unavailable(&stream, &TelemetryStream::unavailable);
        stream.start(QUrl(QString("http://127.0.0.1:%1").arg(server.serverPort())), token);
        QTRY_COMPARE(connections.count(), 1);
        auto *peer = server.nextPendingConnection();
        QTRY_COMPARE_WITH_TIMEOUT(unavailable.count(), 1, 7000);
        stream.stop();
        delete peer;
    }
};

QTEST_GUILESS_MAIN(StreamTest)
#include "test_telemetrystream.moc"
