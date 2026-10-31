#include "mainwindow.h"
#include <QCheckBox>
#include <QComboBox>
#include <QDateTime>
#include <QDir>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QGroupBox>
#include <QHeaderView>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QPlainTextEdit>
#include <QPushButton>
#include <QSettings>
#include <QSignalBlocker>
#include <QSpinBox>
#include <QSplitter>
#include <QTabWidget>
#include <QTableWidget>
#include <QVBoxLayout>
#include <cmath>

namespace {
QDoubleSpinBox *number(double maximum, double value, int decimals = 1) {
    auto spin = new QDoubleSpinBox;
    spin->setRange(0, maximum);
    spin->setDecimals(decimals);
    spin->setValue(value);
    spin->setKeyboardTracking(false);
    return spin;
}
} // namespace

MainWindow::MainWindow(const QString &configPath, const QString &stateDirectory, QWidget *parent)
    : MainWindow(configPath, stateDirectory, parent, nullptr) {}

MainWindow::MainWindow(const DeviceProfile &profile, const QString &stateDirectory, QWidget *parent)
    : MainWindow({}, stateDirectory, parent, &profile) {}

MainWindow::MainWindow(const QString &configPath, const QString &stateDirectory, QWidget *parent,
                       const DeviceProfile *initialProfile)
    : QMainWindow(parent), m_stateDirectory(stateDirectory) {
    createUi();
    if (initialProfile)
        applyProfile(*initialProfile);
    else if (!configPath.isEmpty())
        loadConfig(configPath);
    configureDevice();
    connect(&m_mqtt, &MqttTransport::problem, this, &MainWindow::reportProblem);
    connect(&m_mqtt, &MqttTransport::readyChanged, this, [this](bool ready) {
        m_connectionStatus->setText(ready ? "● 接続済み・指令を受付中" : "○ 未接続 / 接続待ち");
        m_once->setEnabled(ready && m_engine);
        m_start->setEnabled(ready && m_engine && !m_sendTimer.isActive());
        if (ready) {
            const auto status = QJsonDocument(QJsonObject{{"device_id", m_engine->deviceId()},
                                                          {"online", true},
                                                          {"boot_id", m_engine->bootId()}})
                                    .toJson(QJsonDocument::Compact);
            m_mqtt.publish(topic("status"), status, true);
            flushResults();
            if (m_autoSendRequested && !m_sendTimer.isActive())
                startSending();
        }
        emit statusChanged();
    });
    connect(&m_mqtt, &MqttTransport::messageReceived, this,
            [this](const QString &, const QByteArray &payload, int qos, bool retained) {
                auto json = QJsonDocument::fromJson(payload).object();
                addEvent(json["command_id"].toString(), json["operation"].toString(), "received",
                         "", payload);
                if (m_engine)
                    m_engine->receiveCommand(payload, qos, retained);
            });
    connect(&m_mqtt, &MqttTransport::published, this, [this](int mid) {
        if (m_telemetry.remove(mid))
            ++m_confirmed;
        if (m_results.contains(mid)) {
            const auto pending = m_results.take(mid);
            if (m_engine)
                m_engine->acknowledgeResult(pending.commandId, pending.payload);
        }
        refreshState();
    });
    connect(&m_sendTimer, &QTimer::timeout, this, &MainWindow::sendOnce);
    m_sendTimer.setTimerType(Qt::PreciseTimer);
    m_outboxTimer.setInterval(250);
    connect(&m_outboxTimer, &QTimer::timeout, this, &MainWindow::flushResults);
    m_outboxTimer.start();
    for (auto field : {m_host, m_equipment, m_username, m_ca, m_sourceIp})
        connect(field, &QLineEdit::editingFinished, this, &MainWindow::profileChanged);
    connect(m_tls, &QCheckBox::toggled, this, &MainWindow::profileChanged);
    connect(m_port, &QSpinBox::valueChanged, this, &MainWindow::profileChanged);
    connect(m_rate, &QDoubleSpinBox::valueChanged, this, &MainWindow::profileChanged);
    connect(m_delay, &QSpinBox::valueChanged, this, &MainWindow::profileChanged);
}

MainWindow::~MainWindow() {
    m_sendTimer.stop();
    m_outboxTimer.stop();
    m_mqtt.disconnectFromBroker();
    delete m_engine;
}

void MainWindow::createUi() {
    setWindowTitle("TMRP · Device Simulator");
    resize(1200, 880);
    auto root = new QWidget;
    auto layout = new QVBoxLayout(root);
    layout->setContentsMargins(24, 18, 24, 18);
    layout->setSpacing(12);
    auto title = new QLabel("TMRP  /  DEVICE SIMULATOR");
    title->setObjectName("title");
    auto subtitle = new QLabel("電力回線の模擬設備  ·  遥測送信 / 遮断器操作 / 指令応答");
    layout->addWidget(title);
    layout->addWidget(subtitle);
    auto metrics = new QHBoxLayout;
    m_connectionStatus = new QLabel("○ 未接続");
    m_breakerStatus = new QLabel;
    m_powerStatus = new QLabel;
    for (auto label : {m_connectionStatus, m_breakerStatus, m_powerStatus}) {
        label->setObjectName("metric");
        label->setMinimumHeight(55);
        metrics->addWidget(label, 1);
    }
    layout->addLayout(metrics);
    auto upper = new QHBoxLayout;
    auto connectionBox = new QVBoxLayout;
    m_connectionFields = new QGroupBox("01  接続・機器設定");
    auto form = new QFormLayout(m_connectionFields);
    m_device = new QComboBox;
    m_device->setEditable(true);
    m_device->setObjectName("deviceId");
    for (int i = 1; i <= 12; ++i)
        m_device->addItem(QString("power-meter-%1").arg(i, 3, 10, QChar('0')));
    m_equipment = new QLineEdit("breaker-001");
    m_equipment->setObjectName("equipmentId");
    connect(m_device, &QComboBox::currentTextChanged, this, [this](const QString &id) {
        if (id.startsWith("power-meter-"))
            m_equipment->setText("breaker-" + id.mid(12));
    });
    m_host = new QLineEdit("127.0.0.1");
    m_host->setObjectName("mqttHost");
    m_sourceIp = new QLineEdit;
    m_sourceIp->setPlaceholderText("自動選択（通常は空欄）");
    m_port = new QSpinBox;
    m_port->setRange(1, 65535);
    m_port->setValue(18884);
    m_port->setObjectName("mqttPort");
    m_username = new QLineEdit;
    m_password = new QLineEdit;
    m_password->setEchoMode(QLineEdit::Password);
    m_password->setText(QString::fromUtf8(qgetenv("TMRP_SIMULATOR_PASSWORD")));
    m_tls = new QCheckBox("TLSを使用する");
    m_ca = new QLineEdit;
    m_ca->setPlaceholderText("CA証明書のPEMファイル");
    auto caRow = new QWidget;
    auto caLayout = new QHBoxLayout(caRow);
    caLayout->setContentsMargins(0, 0, 0, 0);
    auto browse = new QPushButton("参照");
    caLayout->addWidget(m_ca);
    caLayout->addWidget(browse);
    connect(browse, &QPushButton::clicked, this, [this] {
        const auto path = QFileDialog::getOpenFileName(this, "CA証明書");
        if (!path.isEmpty())
            m_ca->setText(path);
    });
    form->addRow("機器ID", m_device);
    form->addRow("設備ID", m_equipment);
    form->addRow("Broker IP / ホスト名", m_host);
    form->addRow("ポート", m_port);
    form->addRow("送信元IP（任意）", m_sourceIp);
    form->addRow("ユーザー", m_username);
    form->addRow("パスワード", m_password);
    form->addRow(m_tls);
    form->addRow("CA", caRow);
    auto configButtons = new QHBoxLayout;
    auto load = new QPushButton("設定を読込");
    load->setObjectName("loadSingleConfig");
    auto save = new QPushButton("設定を保存");
    configButtons->addWidget(load);
    configButtons->addWidget(save);
    form->addRow(configButtons);
    connect(load, &QPushButton::clicked, this, [this] {
        const auto path = QFileDialog::getOpenFileName(this, "設定を読込", {}, "INI (*.ini)");
        if (!path.isEmpty())
            loadConfig(path);
    });
    connect(save, &QPushButton::clicked, this, &MainWindow::saveConfig);
    connectionBox->addWidget(m_connectionFields);
    auto connectionButtons = new QHBoxLayout;
    m_connect = new QPushButton("接続");
    m_connect->setObjectName("connectButton");
    m_disconnect = new QPushButton("切断");
    m_disconnect->setEnabled(false);
    connectionButtons->addWidget(m_connect);
    connectionButtons->addWidget(m_disconnect);
    connectionBox->addLayout(connectionButtons);
    connect(m_connect, &QPushButton::clicked, this, &MainWindow::startConnection);
    connect(m_disconnect, &QPushButton::clicked, this, &MainWindow::stopConnection);
    upper->addLayout(connectionBox, 1);
    auto deviceBox = new QVBoxLayout;
    auto transmission = new QGroupBox("02  遥測送信");
    auto transmitLayout = new QVBoxLayout(transmission);
    auto rateRow = new QHBoxLayout;
    m_rate = number(50, 1, 1);
    m_rate->setMinimum(0.1);
    m_rate->setSuffix(" Hz");
    m_rate->setObjectName("sendRate");
    rateRow->addWidget(new QLabel("送信頻度"));
    rateRow->addWidget(m_rate);
    m_start = new QPushButton("定期送信を開始");
    m_start->setObjectName("startSending");
    m_start->setEnabled(false);
    m_stop = new QPushButton("停止");
    m_stop->setObjectName("stopSending");
    m_stop->setEnabled(false);
    m_once = new QPushButton("1件送信");
    m_once->setObjectName("sendOnce");
    m_once->setEnabled(false);
    rateRow->addWidget(m_start);
    rateRow->addWidget(m_stop);
    rateRow->addWidget(m_once);
    transmitLayout->addLayout(rateRow);
    m_counter = new QLabel;
    m_counter->setWordWrap(true);
    transmitLayout->addWidget(m_counter);
    auto contract = new QLabel("QoS 1 / retainなし  ·  送信確認はBrokerへの到着を示します");
    contract->setWordWrap(true);
    transmitLayout->addWidget(contract);
    connect(m_start, &QPushButton::clicked, this, &MainWindow::startSending);
    connect(m_once, &QPushButton::clicked, this, &MainWindow::sendOnce);
    connect(m_stop, &QPushButton::clicked, this, &MainWindow::stopSending);
    deviceBox->addWidget(transmission);
    m_measurementFields = new QGroupBox("03  設備状態・模擬値");
    auto deviceForm = new QFormLayout(m_measurementFields);
    auto breakerButtons = new QHBoxLayout;
    m_open = new QPushButton("開く / OPEN");
    m_open->setObjectName("openBreaker");
    m_close = new QPushButton("閉じる / CLOSE");
    m_close->setObjectName("closeBreaker");
    breakerButtons->addWidget(m_open);
    breakerButtons->addWidget(m_close);
    deviceForm->addRow("ローカル操作", breakerButtons);
    m_remote = new QCheckBox("遠方操作を許可");
    m_remote->setObjectName("remoteEnabled");
    m_fault = new QCheckBox("操作インターロックを模擬");
    auto switches = new QHBoxLayout;
    switches->addWidget(m_remote);
    switches->addWidget(m_fault);
    deviceForm->addRow(switches);
    m_voltage = number(1000000, 10000);
    m_voltage->setSuffix(" V");
    m_current = number(10000, 100);
    m_current->setSuffix(" A");
    m_factor = number(1, .9, 2);
    m_factor->setSingleStep(.01);
    m_frequency = number(1000, 50, 2);
    m_frequency->setSuffix(" Hz");
    auto values = new QHBoxLayout;
    values->addWidget(m_voltage);
    values->addWidget(m_current);
    values->addWidget(m_factor);
    values->addWidget(m_frequency);
    deviceForm->addRow("電圧 / 電流 / 力率 / 周波数", values);
    m_quality = new QComboBox;
    m_quality->addItem("全測定値あり", "good");
    m_quality->addItem("B相電流が欠損", "partial");
    m_quality->addItem("全測定値が欠損", "unavailable");
    deviceForm->addRow("測定品質", m_quality);
    m_delay = new QSpinBox;
    m_delay->setRange(0, 30000);
    m_delay->setValue(300);
    m_delay->setSuffix(" ms");
    deviceForm->addRow("指令の模擬動作時間", m_delay);
    auto apply = new QPushButton("模擬値を反映");
    apply->setObjectName("applyMeasurements");
    deviceForm->addRow(apply);
    connect(apply, &QPushButton::clicked, this, &MainWindow::applyMeasurements);
    connect(m_open, &QPushButton::clicked, this, [this] {
        if (m_engine)
            m_engine->updateLocalState({{"closed", false}});
    });
    connect(m_close, &QPushButton::clicked, this, [this] {
        if (m_engine)
            m_engine->updateLocalState({{"closed", true}});
    });
    connect(m_remote, &QCheckBox::toggled, this, [this](bool value) {
        if (m_engine)
            m_engine->updateLocalState({{"remote_enabled", value}});
    });
    connect(m_fault, &QCheckBox::toggled, this, [this](bool value) {
        if (m_engine)
            m_engine->updateLocalState({{"fault", value}});
    });
    deviceBox->addWidget(m_measurementFields);
    upper->addLayout(deviceBox, 2);
    layout->addLayout(upper);
    m_identity = new QLabel;
    m_identity->setWordWrap(true);
    layout->addWidget(m_identity);
    auto tabs = new QTabWidget;
    auto history = new QSplitter(Qt::Vertical);
    m_events = new QTableWidget(0, 5);
    m_events->setObjectName("commandHistory");
    m_events->setHorizontalHeaderLabels({"時刻", "指令ID", "操作", "状態", "理由"});
    m_events->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    m_events->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_events->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_details = new QPlainTextEdit;
    m_details->setReadOnly(true);
    m_details->setMaximumBlockCount(200);
    m_details->setPlaceholderText("履歴を選択すると受信指令・結果のJSONを表示します。");
    history->addWidget(m_events);
    history->addWidget(m_details);
    history->setSizes({180, 75});
    connect(m_events, &QTableWidget::cellClicked, this, [this](int row, int) {
        m_details->setPlainText(m_events->item(row, 0)->data(Qt::UserRole).toString());
    });
    tabs->addTab(history, "受信指令・操作結果");
    m_payload = new QPlainTextEdit;
    m_payload->setReadOnly(true);
    m_payload->setMaximumBlockCount(200);
    tabs->addTab(m_payload, "直近の送信JSON");
    layout->addWidget(tabs, 1);
    m_problem = new QLabel("準備完了。接続先を確認して「接続」を押してください。");
    m_problem->setWordWrap(true);
    m_problem->setObjectName("notice");
    layout->addWidget(m_problem);
    setCentralWidget(root);
    setStyleSheet("QMainWindow { background: #f2f5fa; } QLabel#title { color:#12273c; "
                  "font-size:23px; font-weight:700; }"
                  "QLabel#metric { background:#142f46; color:#eef9ff; border-radius:8px; "
                  "padding:10px; font-size:16px; }"
                  "QGroupBox { background:white; border:1px solid #ced8e3; border-radius:6px; "
                  "margin-top:10px; padding-top:16px; font-weight:600; }"
                  "QGroupBox::title { subcontrol-origin:margin; left:12px; color:#23445a; }"
                  "QPushButton { padding:7px 10px; border:1px solid #adbecf; border-radius:4px; "
                  "background:#fff; color:#183b50; }"
                  "QPushButton:hover { background:#e0f3f6; } QPushButton:disabled { color:#8c99a8; "
                  "background:#eff2f5; }"
                  "QPushButton#connectButton, QPushButton#startSending { background:#087e8b; "
                  "color:white; border:0; }"
                  "QLineEdit,QDoubleSpinBox,QSpinBox,QComboBox { padding:4px; min-height:22px; "
                  "background:#fff; color:#183b50; selection-background-color:#087e8b; "
                  "selection-color:#fff; }"
                  "QLineEdit:disabled,QDoubleSpinBox:disabled,QSpinBox:disabled,QComboBox:disabled "
                  "{ background:#eff2f5; color:#63758a; }"
                  "QTableWidget,QPlainTextEdit { background:#fff; color:#183b50; "
                  "selection-background-color:#087e8b; selection-color:#fff; "
                  "border:1px solid #ced8e3; }"
                  "QLabel#notice { color:#854b14; padding:5px; }");
}

void MainWindow::setDeviceId(const QString &id) {
    m_device->setCurrentText(id);
    configureDevice();
}

bool MainWindow::configureDevice() {
    const QString id = m_device->currentText(), equipment = m_equipment->text();
    if (!DeviceEngine::validId(id) || !DeviceEngine::validId(equipment)) {
        reportProblem("機器ID・設備IDが不正です。");
        return false;
    }
    if (m_engine && m_engine->deviceId() == id && m_engine->equipmentId() == equipment)
        return true;
    if (m_engine && m_engine->busy()) {
        reportProblem("指令の完了後に機器を切り替えてください。");
        return false;
    }
    delete m_engine;
    m_engine = nullptr;
    auto candidate =
        new DeviceEngine(id, equipment, QDir(m_stateDirectory).filePath(id + ".sqlite"), this);
    connect(candidate, &DeviceEngine::problem, this, &MainWindow::reportProblem);
    if (!candidate->initialize()) {
        reportProblem(candidate->error());
        delete candidate;
        return false;
    }
    m_engine = candidate;
    const auto initial = m_engine->state();
    m_voltage->setValue(initial["voltage"].toDouble());
    m_current->setValue(initial["current"].toDouble());
    m_factor->setValue(initial["power_factor"].toDouble());
    m_frequency->setValue(initial["frequency"].toDouble());
    m_quality->setCurrentIndex(m_quality->findData(initial["quality"].toString()));
    m_engine->setOperationDelay(m_delay->value());
    connect(m_delay, &QSpinBox::valueChanged, m_engine, &DeviceEngine::setOperationDelay);
    connect(m_engine, &DeviceEngine::stateChanged, this, [this] {
        refreshState();
        if (m_mqtt.ready())
            sendOnce();
    });
    connect(m_engine, &DeviceEngine::busyChanged, this,
            [this](bool busy) { m_measurementFields->setEnabled(!busy); });
    connect(m_engine, &DeviceEngine::commandResult, this, [this](const QJsonObject &result) {
        const auto bytes = QJsonDocument(result).toJson(QJsonDocument::Compact);
        addEvent(result["command_id"].toString(), "", result["status"].toString(),
                 result["reason"].toString(), bytes);
        if (result["reason"] == "command_id_conflict")
            m_mqtt.publish(topic("command-results"), bytes);
        else
            flushResults();
    });
    refreshState();
    return true;
}

void MainWindow::startConnection() {
    if (!configureDevice())
        return;
    ConnectionOptions options;
    options.deviceId = m_device->currentText();
    options.host = m_host->text();
    options.port = m_port->value();
    options.username = m_username->text();
    options.password = m_password->text();
    options.tls = m_tls->isChecked();
    options.caFile = m_ca->text();
    options.sourceIp = m_sourceIp->text();
    m_telemetry.clear();
    m_results.clear();
    if (m_mqtt.connectToBroker(options)) {
        m_connecting = true;
        m_connectionFields->setEnabled(false);
        m_connect->setEnabled(false);
        m_disconnect->setEnabled(true);
        m_problem->setText("接続中。指令Topicの購読完了を待っています。");
    }
    emit statusChanged();
}

QString MainWindow::topic(const QString &suffix) const {
    return "tmrp/devices/" + m_engine->deviceId() + "/" + suffix;
}

void MainWindow::startSending() {
    if (!m_engine || !m_mqtt.ready())
        return;
    m_sendTimer.start(qRound(1000 / m_rate->value()));
    m_start->setEnabled(false);
    m_stop->setEnabled(true);
    m_rate->setEnabled(false);
    sendOnce();
    emit statusChanged();
}

void MainWindow::sendOnce() {
    if (!m_engine || !m_mqtt.ready() || m_telemetry.size() + m_results.size() >= 100) {
        ++m_skipped;
        refreshState();
        return;
    }
    const auto data = m_engine->telemetry();
    const auto payload = QJsonDocument(data).toJson(QJsonDocument::Compact);
    const int mid = m_mqtt.publish(topic("telemetry"), payload);
    if (mid >= 0) {
        m_telemetry.insert(mid);
        ++m_sent;
        m_payload->setPlainText(QJsonDocument(data).toJson(QJsonDocument::Indented));
    } else
        ++m_skipped;
    refreshState();
}

void MainWindow::flushResults() {
    if (!m_engine || !m_mqtt.ready())
        return;
    for (const auto &result : m_engine->pendingResults()) {
        if (m_telemetry.size() + m_results.size() >= 100)
            break;
        const auto bytes = QJsonDocument(result).toJson(QJsonDocument::Compact);
        bool inflight = false;
        for (const auto &entry : m_results)
            if (entry.payload == bytes) {
                inflight = true;
                break;
            }
        if (inflight)
            continue;
        const int mid = m_mqtt.publish(topic("command-results"), bytes);
        if (mid >= 0)
            m_results.insert(mid, {result["command_id"].toString(), bytes});
    }
}

void MainWindow::refreshState() {
    if (!m_engine)
        return;
    const auto state = m_engine->state();
    m_breakerStatus->setText(
        QString("遮断器  %1").arg(state["closed"].toBool() ? "CLOSED / 閉" : "OPEN / 開"));
    const double power = state["closed"].toBool() ? std::sqrt(3.0) * state["voltage"].toDouble() *
                                                        state["current"].toDouble() *
                                                        state["power_factor"].toDouble() / 1000
                                                  : 0;
    m_powerStatus->setText(QString("有効電力  %1 kW").arg(power, 0, 'f', 1));
    m_counter->setText(QString("送信要求 %1  /  Broker確認 %2  /  送信待ち %3  /  送信見送り %4")
                           .arg(m_sent)
                           .arg(m_confirmed)
                           .arg(m_telemetry.size() + m_results.size())
                           .arg(m_skipped));
    m_identity->setText(QString("%1 → %2  ·  状態版 %3  ·  boot %4")
                            .arg(m_engine->deviceId(), m_engine->equipmentId())
                            .arg(state["state_version"].toInteger())
                            .arg(m_engine->bootId()));
    const QSignalBlocker remoteBlock(m_remote), faultBlock(m_fault);
    m_remote->setChecked(state["remote_enabled"].toBool());
    m_fault->setChecked(state["fault"].toBool());
    emit statusChanged();
}

void MainWindow::applyMeasurements() {
    if (!m_engine)
        return;
    if (!m_engine->updateLocalState({{"voltage", m_voltage->value()},
                                     {"current", m_current->value()},
                                     {"power_factor", m_factor->value()},
                                     {"frequency", m_frequency->value()},
                                     {"quality", m_quality->currentData().toString()}}))
        reportProblem("模擬値を反映できません。入力値・指令処理中の状態を確認してください。");
}

void MainWindow::addEvent(const QString &id, const QString &operation, const QString &status,
                          const QString &reason, const QByteArray &payload) {
    if (m_events->rowCount() >= 500)
        m_events->removeRow(0);
    const int row = m_events->rowCount();
    m_events->insertRow(row);
    const QStringList values = {QTime::currentTime().toString("HH:mm:ss.zzz"), id, operation,
                                status, reason};
    for (int column = 0; column < values.size(); ++column)
        m_events->setItem(row, column, new QTableWidgetItem(values[column]));
    const auto json = QJsonDocument::fromJson(payload);
    const QString text = json.isNull() ? QString::fromUtf8(payload)
                                       : QString::fromUtf8(json.toJson(QJsonDocument::Indented));
    m_events->item(row, 0)->setData(Qt::UserRole, text);
    m_details->setPlainText(text);
    m_events->scrollToBottom();
}

void MainWindow::reportProblem(const QString &message) {
    m_problem->setText(message);
    addEvent("", "", "error", message);
}

void MainWindow::loadConfig(const QString &path) {
    if (!QFileInfo(path).isFile() || QFileInfo(path).size() > 16384) {
        reportProblem("設定ファイルを読み込めません（上限16KiB）。");
        return;
    }
    QSettings settings(path, QSettings::IniFormat);
    m_device->setCurrentText(settings.value("device/id", "power-meter-001").toString());
    m_equipment->setText(settings.value("device/equipment_id", "breaker-001").toString());
    m_host->setText(settings.value("mqtt/host", "127.0.0.1").toString());
    m_port->setValue(settings.value("mqtt/port", 18884).toInt());
    m_username->setText(settings.value("mqtt/username").toString());
    m_password->setText(QString::fromUtf8(qgetenv("TMRP_SIMULATOR_PASSWORD")));
    m_tls->setChecked(settings.value("mqtt/tls", false).toBool());
    auto ca = settings.value("mqtt/ca_file").toString();
    if (!ca.isEmpty() && QFileInfo(ca).isRelative())
        ca = QFileInfo(path).dir().absoluteFilePath(ca);
    m_ca->setText(ca);
    m_sourceIp->setText(settings.value("mqtt/source_ip").toString());
    m_rate->setValue(settings.value("telemetry/rate_hz", 1).toDouble());
    m_delay->setValue(settings.value("device/operation_delay_ms", 300).toInt());
}

void MainWindow::saveConfig() {
    const auto path = QFileDialog::getSaveFileName(this, "設定を保存", {}, "INI (*.ini)");
    if (path.isEmpty())
        return;
    QSettings settings(path, QSettings::IniFormat);
    settings.clear();
    settings.setValue("device/id", m_device->currentText());
    settings.setValue("device/equipment_id", m_equipment->text());
    settings.setValue("device/operation_delay_ms", m_delay->value());
    settings.setValue("telemetry/rate_hz", m_rate->value());
    settings.setValue("mqtt/host", m_host->text());
    settings.setValue("mqtt/port", m_port->value());
    settings.setValue("mqtt/username", m_username->text());
    settings.setValue("mqtt/tls", m_tls->isChecked());
    settings.setValue("mqtt/ca_file", m_ca->text());
    settings.sync();
    settings.setValue("mqtt/source_ip", m_sourceIp->text());
    settings.sync();
    m_problem->setText(settings.status() == QSettings::NoError
                           ? "設定を保存しました。パスワードは保存していません。"
                           : "設定を保存できませんでした。");
}

bool MainWindow::editable() const {
    return !m_connecting && !m_sendTimer.isActive() && (!m_engine || !m_engine->busy());
}

void MainWindow::stopSending() {
    m_autoSendRequested = false;
    m_sendTimer.stop();
    m_stop->setEnabled(false);
    m_start->setEnabled(m_mqtt.ready());
    m_rate->setEnabled(true);
    emit statusChanged();
}

void MainWindow::startWhenConnected() {
    m_autoSendRequested = true;
    if (m_mqtt.ready())
        startSending();
    else if (!m_connecting)
        startConnection();
}

void MainWindow::stopConnection() {
    stopSending();
    m_mqtt.disconnectFromBroker();
    m_telemetry.clear();
    m_results.clear();
    m_connecting = false;
    m_connectionFields->setEnabled(true);
    m_connect->setEnabled(true);
    m_disconnect->setEnabled(false);
    refreshState();
}

DeviceProfile MainWindow::profile() const {
    DeviceProfile value;
    value.name = m_displayName.isEmpty() ? m_device->currentText() : m_displayName;
    value.connection.deviceId = m_device->currentText();
    value.equipmentId = m_equipment->text();
    value.connection.host = m_host->text();
    value.connection.port = m_port->value();
    value.connection.sourceIp = m_sourceIp->text();
    value.connection.username = m_username->text();
    value.connection.password = m_password->text();
    value.connection.tls = m_tls->isChecked();
    value.connection.caFile = m_ca->text();
    value.rateHz = m_rate->value();
    value.operationDelayMs = m_delay->value();
    return value;
}

bool MainWindow::applyProfile(const DeviceProfile &value) {
    if (!editable() || !value.validationError().isEmpty())
        return false;
    if (m_engine && (m_engine->deviceId() != value.connection.deviceId ||
                     m_engine->equipmentId() != value.equipmentId))
        return false;
    const QSignalBlocker block(this);
    m_displayName = value.name;
    m_device->setCurrentText(value.connection.deviceId);
    m_equipment->setText(value.equipmentId);
    m_host->setText(value.connection.host);
    m_port->setValue(value.connection.port);
    m_sourceIp->setText(value.connection.sourceIp);
    m_username->setText(value.connection.username);
    m_password->setText(value.connection.password);
    m_tls->setChecked(value.connection.tls);
    m_ca->setText(value.connection.caFile);
    m_rate->setValue(value.rateHz);
    m_delay->setValue(value.operationDelayMs);
    return true;
}

void MainWindow::lockIdentity() {
    m_identityLocked = true;
    m_device->setEnabled(false);
    m_equipment->setEnabled(false);
    findChild<QPushButton *>("loadSingleConfig")->setEnabled(false);
}
