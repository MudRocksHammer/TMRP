#pragma once

#include <QJsonObject>
#include <QObject>
#include <QTimer>
#include <QUrl>

class QWebSocket;

// Receives complete snapshots; the server must send one at least every 5 seconds.
class TelemetryStream final : public QObject {
    Q_OBJECT
public:
    explicit TelemetryStream(QObject *parent = nullptr);
    void start(const QUrl &gateway, const QByteArray &token);
    void stop();

signals:
    void snapshotReceived(const QJsonObject &snapshot);
    void unavailable(const QString &reason);

private:
    void open();
    void discardSocket();
    void fail(const QString &reason);
    QWebSocket *socket_ = nullptr;
    QTimer retry_;
    QTimer timeout_;
    QUrl endpoint_;
    QByteArray token_;
    bool active_ = false;
};
