#pragma once
#include <QObject>
#include <atomic>
#include <functional>

struct mosquitto;
struct mosquitto_message;

struct ConnectionOptions {
    QString host = "127.0.0.1";
    int port = 18884;
    QString deviceId = "power-meter-001";
    QString username, password, caFile, sourceIp;
    bool tls = false;
    QString validationError() const;
};

class MqttTransport : public QObject {
    Q_OBJECT
  public:
    explicit MqttTransport(QObject *parent = nullptr);
    ~MqttTransport() override;
    bool connectToBroker(const ConnectionOptions &options);
    void disconnectFromBroker();
    int publish(const QString &topic, const QByteArray &payload, bool retain = false);
    bool ready() const { return m_ready; }
  signals:
    void readyChanged(bool ready);
    void problem(const QString &message);
    void messageReceived(const QString &topic, const QByteArray &payload, int qos, bool retained);
    void published(int mid);

  private:
    static void onConnect(mosquitto *, void *, int);
    static void onDisconnect(mosquitto *, void *, int);
    static void onSubscribe(mosquitto *, void *, int, int, const int *);
    static void onMessage(mosquitto *, void *, const mosquitto_message *);
    static void onPublish(mosquitto *, void *, int);
    void post(std::function<void()> function);
    mosquitto *m_client = nullptr;
    ConnectionOptions m_options;
    std::atomic<unsigned> m_generation{0};
    std::atomic<int> m_queuedCommands{0};
    std::atomic<bool> m_overflowReported{false};
    bool m_ready = false;
    bool m_loopStarted = false;
};
