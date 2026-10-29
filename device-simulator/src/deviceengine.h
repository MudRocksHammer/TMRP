#pragma once

#include <QDateTime>
#include <QJsonObject>
#include <QLockFile>
#include <QObject>
#include <QSqlDatabase>
#include <QTimer>
#include <memory>

class DeviceEngine : public QObject {
    Q_OBJECT
public:
    DeviceEngine(QString deviceId, QString equipmentId, QString databasePath,
                 QObject *parent = nullptr);
    ~DeviceEngine() override;
    bool initialize();
    QString error() const { return m_error; }
    QString deviceId() const { return m_device; }
    QString equipmentId() const { return m_equipment; }
    QString bootId() const { return m_boot; }
    QJsonObject state() const { return m_state; }
    bool busy() const { return !m_active.isEmpty(); }
    void setOperationDelay(int milliseconds);
    bool updateLocalState(const QJsonObject &changes);
    QJsonObject telemetry();
    void receiveCommand(const QByteArray &payload, int qos = 1, bool retained = false);
    QList<QJsonObject> pendingResults() const;
    bool acknowledgeResult(const QString &id, const QByteArray &payload);
    static bool validId(const QString &value);

signals:
    void stateChanged();
    void commandResult(const QJsonObject &result);
    void problem(const QString &message);
    void busyChanged(bool busy);

private:
    bool executeSql(const QString &statement);
    bool persistState(const QJsonObject &state);
    bool storeResult(const QString &id, const QByteArray &request, const QJsonObject &result);
    QJsonObject result(const QString &id, const QString &status, const QString &reason) const;
    void finishCommand();
    void fail(const QString &message);
    QString m_device, m_equipment, m_path, m_boot, m_error;
    QSqlDatabase m_db;
    std::unique_ptr<QLockFile> m_lock;
    QJsonObject m_state, m_active;
    QByteArray m_activeRequest;
    QTimer m_operation;
    qint64 m_sequence = 0;
    int m_delay = 300;
};

