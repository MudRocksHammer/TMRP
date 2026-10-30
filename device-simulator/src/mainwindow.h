#pragma once
#include "deviceengine.h"
#include "deviceprofile.h"
#include "mqtttransport.h"
#include <QHash>
#include <QMainWindow>
#include <QSet>

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QGroupBox;
class QLabel;
class QLineEdit;
class QPlainTextEdit;
class QPushButton;
class QSpinBox;
class QTableWidget;

class MainWindow : public QMainWindow {
    Q_OBJECT
  public:
    MainWindow(const QString &configPath, const QString &stateDirectory, QWidget *parent = nullptr);
    MainWindow(const DeviceProfile &profile, const QString &stateDirectory, QWidget *parent);
    ~MainWindow() override;
    DeviceEngine *engine() const { return m_engine; }
    bool connectionReady() const { return m_mqtt.ready(); }
    void setDeviceId(const QString &id);
    DeviceProfile profile() const;
    bool applyProfile(const DeviceProfile &profile);
    bool editable() const;
    void lockIdentity();
    bool sending() const { return m_sendTimer.isActive(); }
  signals:
    void profileChanged();
    void statusChanged();
  public slots:
    void startConnection();
    void startSending();
    void startWhenConnected();
    void sendOnce();
    void stopSending();
    void stopConnection();

  private:
    MainWindow(const QString &configPath, const QString &stateDirectory, QWidget *parent,
               const DeviceProfile *profile);
    void createUi();
    bool configureDevice();
    void refreshState();
    void applyMeasurements();
    void flushResults();
    void addEvent(const QString &id, const QString &operation, const QString &status,
                  const QString &reason, const QByteArray &payload = {});
    void reportProblem(const QString &message);
    void loadConfig(const QString &path);
    void saveConfig();
    QString topic(const QString &suffix) const;
    QString m_stateDirectory, m_displayName;
    bool m_connecting = false, m_identityLocked = false, m_autoSendRequested = false;
    MqttTransport m_mqtt;
    DeviceEngine *m_engine = nullptr;
    QTimer m_sendTimer, m_outboxTimer;
    struct Pending {
        QString commandId;
        QByteArray payload;
    };
    QHash<int, Pending> m_results;
    QSet<int> m_telemetry;
    quint64 m_sent = 0, m_confirmed = 0, m_skipped = 0;
    QLineEdit *m_host, *m_username, *m_password, *m_ca, *m_equipment, *m_sourceIp;
    QComboBox *m_device, *m_quality;
    QSpinBox *m_port, *m_delay;
    QDoubleSpinBox *m_rate, *m_voltage, *m_current, *m_factor, *m_frequency;
    QCheckBox *m_tls, *m_remote, *m_fault;
    QGroupBox *m_connectionFields, *m_measurementFields;
    QPushButton *m_connect, *m_disconnect, *m_start, *m_stop, *m_once, *m_open, *m_close;
    QLabel *m_connectionStatus, *m_breakerStatus, *m_powerStatus, *m_counter, *m_identity,
        *m_problem;
    QTableWidget *m_events;
    QPlainTextEdit *m_payload, *m_details;
};
