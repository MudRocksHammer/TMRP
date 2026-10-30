#include "mqtttransport.h"
#include "deviceengine.h"
#include <QFileInfo>
#include <QHostAddress>
#include <QJsonDocument>
#include <QNetworkInterface>
#include <mosquitto.h>

QString ConnectionOptions::validationError() const {
    if (host.trimmed().isEmpty() || host != host.trimmed() || host.contains(QChar::Null) ||
        port < 1 || port > 65535 || !DeviceEngine::validId(deviceId))
        return "接続先・ポート・機器IDが不正です。";
    if (!tls && host != "127.0.0.1" && host != "localhost" && host != "::1")
        return "遠隔Brokerへの接続にはTLSとCA証明書を設定してください。";
    if (tls && (!QFileInfo(caFile).isFile() || !QFileInfo(caFile).isReadable()))
        return "読み取り可能なCA証明書（PEM）を指定してください。";
    if (username.contains(QChar::Null) || password.contains(QChar::Null))
        return "認証情報にNUL文字は使用できません。";
    if (!sourceIp.isEmpty() &&
        (QHostAddress(sourceIp).isNull() ||
         !QNetworkInterface::allAddresses().contains(QHostAddress(sourceIp))))
        return "送信元IPはこのPCに割り当てられたIPアドレスを指定してください。通常は空欄です。";
    return {};
}

MqttTransport::MqttTransport(QObject *parent) : QObject(parent) {
    // Keep global library lifetime until process exit; multiple windows/tests may
    // have clients alive concurrently. Static initialization is thread safe.
    static const int initialized = mosquitto_lib_init();
    Q_UNUSED(initialized);
}

MqttTransport::~MqttTransport() { disconnectFromBroker(); }

void MqttTransport::post(std::function<void()> function) {
    const unsigned generation = m_generation.load();
    QMetaObject::invokeMethod(
        this,
        [this, generation, function = std::move(function)] {
            if (generation == m_generation.load())
                function();
        },
        Qt::QueuedConnection);
}

bool MqttTransport::connectToBroker(const ConnectionOptions &options) {
    const auto error = options.validationError();
    if (!error.isEmpty()) {
        emit problem(error);
        return false;
    }
    disconnectFromBroker();
    m_options = options;
    const auto id = ("tmrp-sim-" + options.deviceId).toUtf8();
    // Commands sent while offline are not queued. The sender must retry until
    // an APPLICATION result, using the same command_id and deadline.
    m_client = mosquitto_new(id.constData(), true, this);
    if (!m_client) {
        emit problem("MQTTクライアントを作成できません。");
        return false;
    }
    mosquitto_connect_callback_set(m_client, &MqttTransport::onConnect);
    mosquitto_disconnect_callback_set(m_client, &MqttTransport::onDisconnect);
    mosquitto_subscribe_callback_set(m_client, &MqttTransport::onSubscribe);
    mosquitto_message_callback_set(m_client, &MqttTransport::onMessage);
    mosquitto_publish_callback_set(m_client, &MqttTransport::onPublish);
    mosquitto_reconnect_delay_set(m_client, 1, 10, true);
    mosquitto_int_option(m_client, MOSQ_OPT_PROTOCOL_VERSION, MQTT_PROTOCOL_V311);
    if (!options.username.isEmpty())
        mosquitto_username_pw_set(m_client, options.username.toUtf8().constData(),
                                  options.password.toUtf8().constData());
    int rc = MOSQ_ERR_SUCCESS;
    if (options.tls) {
        rc = mosquitto_tls_set(m_client, options.caFile.toUtf8().constData(), nullptr, nullptr,
                               nullptr, nullptr);
        if (rc == MOSQ_ERR_SUCCESS)
            rc = mosquitto_tls_opts_set(m_client, 1, "tlsv1.2", nullptr);
    }
    const auto statusTopic = ("tmrp/devices/" + options.deviceId + "/status").toUtf8();
    const auto will = QJsonDocument(QJsonObject{{"device_id", options.deviceId}, {"online", false}})
                          .toJson(QJsonDocument::Compact);
    if (rc == MOSQ_ERR_SUCCESS)
        rc = mosquitto_will_set(m_client, statusTopic.constData(), int(will.size()),
                                will.constData(), 1, true);
    if (rc == MOSQ_ERR_SUCCESS)
        rc = mosquitto_connect_bind_async(
            m_client, options.host.toUtf8().constData(), options.port, 20,
            options.sourceIp.isEmpty() ? nullptr : options.sourceIp.toUtf8().constData());
    if (rc == MOSQ_ERR_SUCCESS) {
        rc = mosquitto_loop_start(m_client);
        m_loopStarted = rc == MOSQ_ERR_SUCCESS;
    }
    if (rc != MOSQ_ERR_SUCCESS) {
        emit problem("MQTT接続開始に失敗しました: " + QString::fromUtf8(mosquitto_strerror(rc)));
        disconnectFromBroker();
        return false;
    }
    return true;
}

void MqttTransport::disconnectFromBroker() {
    ++m_generation;
    if (m_client) {
        mosquitto_disconnect(m_client);
        if (m_loopStarted)
            mosquitto_loop_stop(m_client, true);
        mosquitto_destroy(m_client);
        m_client = nullptr;
    }
    ++m_generation; // Also discard callbacks posted while the old loop stopped.
    m_queuedCommands = 0;
    m_overflowReported = false;
    m_loopStarted = false;
    m_ready = false;
    emit readyChanged(false);
}

int MqttTransport::publish(const QString &topic, const QByteArray &payload, bool retain) {
    if (!m_client || !m_ready)
        return -1;
    int mid = 0;
    const auto rc = mosquitto_publish(m_client, &mid, topic.toUtf8().constData(),
                                      int(payload.size()), payload.constData(), 1, retain);
    if (rc != MOSQ_ERR_SUCCESS) {
        emit problem("MQTT送信に失敗しました: " + QString::fromUtf8(mosquitto_strerror(rc)));
        return -1;
    }
    return mid;
}

void MqttTransport::onConnect(mosquitto *client, void *object, int rc) {
    auto self = static_cast<MqttTransport *>(object);
    if (rc != 0) {
        self->post([self, rc] {
            self->m_ready = false;
            emit self->readyChanged(false);
            emit self->problem("Brokerが接続を拒否しました（コード " + QString::number(rc) +
                               "）。");
        });
        return;
    }
    const auto topic = ("tmrp/devices/" + self->m_options.deviceId + "/commands").toUtf8();
    if (mosquitto_subscribe(client, nullptr, topic.constData(), 1) != MOSQ_ERR_SUCCESS)
        self->post([self] { emit self->problem("指令Topicを購読できません。"); });
}

void MqttTransport::onSubscribe(mosquitto *, void *object, int, int count, const int *granted) {
    auto self = static_cast<MqttTransport *>(object);
    const bool ok = count == 1 && granted[0] == 1;
    self->post([self, ok] {
        self->m_ready = ok;
        emit self->readyChanged(ok);
        if (!ok)
            emit self->problem("BrokerがQoS 1の指令購読を許可していません。");
    });
}

void MqttTransport::onDisconnect(mosquitto *, void *object, int rc) {
    auto self = static_cast<MqttTransport *>(object);
    self->post([self, rc] {
        self->m_ready = false;
        emit self->readyChanged(false);
        if (rc)
            emit self->problem("MQTT切断。再接続を待っています。");
    });
}

void MqttTransport::onMessage(mosquitto *, void *object, const mosquitto_message *message) {
    auto self = static_cast<MqttTransport *>(object);
    if (message->payloadlen > 16384) {
        self->post([self] { emit self->problem("受信指令が16KiBを超えています。"); });
        return;
    }
    const QString topic = QString::fromUtf8(message->topic);
    if (self->m_queuedCommands.fetch_add(1) >= 128) {
        --self->m_queuedCommands;
        if (!self->m_overflowReported.exchange(true))
            self->post([self] {
                emit self->problem("指令受信待ちが上限128件に達しました。送信側から同じ指令IDで再試"
                                   "行してください。");
            });
        return;
    }
    const QByteArray payload(static_cast<const char *>(message->payload), message->payloadlen);
    const int qos = message->qos;
    const bool retain = message->retain;
    self->post([self, topic, payload, qos, retain] {
        if (--self->m_queuedCommands < 64)
            self->m_overflowReported = false;
        emit self->messageReceived(topic, payload, qos, retain);
    });
}

void MqttTransport::onPublish(mosquitto *, void *object, int mid) {
    auto self = static_cast<MqttTransport *>(object);
    self->post([self, mid] { emit self->published(mid); });
}
