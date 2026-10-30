#pragma once
#include "mainwindow.h"
#include <QLockFile>
#include <QMainWindow>
#include <memory>

class QLabel;
class QStackedWidget;
class QTableWidget;

class FleetWindow : public QMainWindow {
    Q_OBJECT
  public:
    FleetWindow(QString profilesPath, QString stateDirectory, QWidget *parent = nullptr);
    ~FleetWindow() override;
    bool initialized() const { return m_initialized; }
    QString error() const { return m_error; }
    int deviceCount() const { return m_panels.size(); }
    MainWindow *device(int index) const { return m_panels.value(index, nullptr); }
    bool addDevice(const DeviceProfile &profile);
    bool updateDevice(int index, const DeviceProfile &profile);
    bool removeDevice(int index);
    bool saveProfiles();
  public slots:
    void connectAll();
    void startAll();
    void stopAll();
    void disconnectAll();

  private:
    bool appendDevice(const DeviceProfile &profile);
    void showEditor(bool adding);
    void refreshList();
    void report(const QString &message);
    bool loadProfiles();
    QList<MainWindow *> m_panels;
    QString m_profilesPath, m_stateDirectory, m_error;
    std::unique_ptr<QLockFile> m_lock;
    QTableWidget *m_table;
    QStackedWidget *m_stack;
    QLabel *m_notice;
    QTimer m_saveTimer;
    bool m_initialized = false;
};
