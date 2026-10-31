#include "telemetrystream.h"
#include <QJsonDocument>
#include <QNetworkRequest>
#include <QWebSocket>

TelemetryStream::TelemetryStream(QObject *parent) : QObject(parent) {
    retry_.setSingleShot(true);
    retry_.setInterval(2000);
    timeout_.setSingleShot(true);
    timeout_.setInterval(5000);
    connect(&retry_, &QTimer::timeout, this, &TelemetryStream::open);
    connect(&timeout_, &QTimer::timeout, this, [this] {
        fail(QStringLiteral("WebSocket 连接或遥测超时，正在重连"));
    });
}

void TelemetryStream::start(const QUrl &gateway, const QByteArray &token) {
    stop();
    endpoint_ = gateway;
    endpoint_.setScheme(gateway.scheme() == "https" ? "wss" : "ws");
    endpoint_.setPath("/api/stream");
    token_ = token;
    active_ = true;
    open();
}

void TelemetryStream::discardSocket() {
    if (!socket_) return;
    auto *old = socket_;
    socket_ = nullptr;
    old->disconnect(this);
    old->abort();
    old->deleteLater();
}

void TelemetryStream::stop() {
    active_ = false;
    retry_.stop();
    timeout_.stop();
    discardSocket();
    token_.clear();
}

void TelemetryStream::fail(const QString &reason) {
    if (!active_) return;
    timeout_.stop();
    discardSocket();
    retry_.start();
    emit unavailable(reason);
}

void TelemetryStream::open() {
    if (!active_) return;
    socket_ = new QWebSocket(QString(), QWebSocketProtocol::VersionLatest, this);
    socket_->setMaxAllowedIncomingFrameSize(4 * 1024 * 1024);
    socket_->setMaxAllowedIncomingMessageSize(4 * 1024 * 1024);
    connect(socket_, &QWebSocket::textMessageReceived, this, [this](const QString &message) {
        QJsonParseError error;
        const auto document = QJsonDocument::fromJson(message.toUtf8(), &error);
        const auto snapshot = document.object();
        if (error.error != QJsonParseError::NoError || !document.isObject()
            || !snapshot["devices"].isArray() || !snapshot["commands"].isArray()
            || !snapshot["mqtt_ready"].isBool()) {
            fail(QStringLiteral("WebSocket 快照格式无效，正在重连"));
            return;
        }
        timeout_.start();
        emit snapshotReceived(snapshot);
    });
    connect(socket_, &QWebSocket::binaryMessageReceived, this, [this](const QByteArray &) {
        fail(QStringLiteral("WebSocket 需要 JSON 文本快照，正在重连"));
    });
    connect(socket_, &QWebSocket::disconnected, this, [this] {
        fail(QStringLiteral("WebSocket 已断开，正在重连"));
    });
#if QT_VERSION >= QT_VERSION_CHECK(6, 5, 0)
    connect(socket_, &QWebSocket::errorOccurred, this, [this](QAbstractSocket::SocketError) {
#else
    connect(socket_, QOverload<QAbstractSocket::SocketError>::of(&QWebSocket::error), this, [this](QAbstractSocket::SocketError) {
#endif
        fail(QStringLiteral("WebSocket 连接失败，请检查网关是否支持 /api/stream；正在重连"));
    });
    QNetworkRequest request(endpoint_);
    request.setRawHeader("Authorization", "Bearer " + token_);
    request.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
    timeout_.start();
    socket_->open(request);
}
