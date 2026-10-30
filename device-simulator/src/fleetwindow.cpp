#include "fleetwindow.h"
#include <QCheckBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QDoubleSpinBox>
#include <QFile>
#include <QFileDialog>
#include <QFileInfo>
#include <QFormLayout>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QSaveFile>
#include <QScrollArea>
#include <QSpinBox>
#include <QSplitter>
#include <QStackedWidget>
#include <QTableWidget>
#include <QVBoxLayout>

FleetWindow::FleetWindow(QString profilesPath, QString stateDirectory, QWidget *parent)
    : QMainWindow(parent), m_profilesPath(std::move(profilesPath)),
      m_stateDirectory(std::move(stateDirectory)) {
    setWindowTitle("TMRP · 模擬設備マネージャー");
    resize(1450, 980);
    auto central = new QWidget;
    auto layout = new QVBoxLayout(central);
    auto toolbar = new QHBoxLayout;
    auto title = new QLabel("TMRP  /  模擬設備一覧");
    title->setStyleSheet("font-size:20px;font-weight:600;color:#142f46");
    toolbar->addWidget(title);
    toolbar->addStretch();
    auto add = new QPushButton("設備を追加");
    add->setObjectName("addDevice");
    auto edit = new QPushButton("設定を編集");
    edit->setObjectName("editDevice");
    auto remove = new QPushButton("一覧から削除");
    remove->setObjectName("removeDevice");
    auto save = new QPushButton("設定一覧を保存");
    for (auto button : {add, edit, remove, save})
        toolbar->addWidget(button);
    layout->addLayout(toolbar);
    auto operations = new QHBoxLayout;
    auto connectButton = new QPushButton("全設備を接続"),
         send = new QPushButton("全設備の定期送信"), stop = new QPushButton("全定期送信を停止"),
         disconnectButton = new QPushButton("全設備を切断");
    for (auto button : {connectButton, send, stop, disconnectButton})
        operations->addWidget(button);
    operations->addStretch();
    layout->addLayout(operations);
    auto split = new QSplitter(Qt::Vertical);
    m_table = new QTableWidget(0, 6);
    m_table->setObjectName("deviceList");
    m_table->setHorizontalHeaderLabels(
        {"表示名 / 機器ID", "Broker IP : ポート", "送信元IP", "接続", "送信", "遮断器"});
    m_table->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    m_table->setSelectionBehavior(QAbstractItemView::SelectRows);
    m_table->setSelectionMode(QAbstractItemView::SingleSelection);
    m_table->setEditTriggers(QAbstractItemView::NoEditTriggers);
    m_table->setMinimumHeight(110);
    m_stack = new QStackedWidget;
    auto detailScroll = new QScrollArea;
    detailScroll->setWidgetResizable(true);
    detailScroll->setWidget(m_stack);
    split->addWidget(m_table);
    split->addWidget(detailScroll);
    split->setChildrenCollapsible(false);
    split->setSizes({160, 780});
    layout->addWidget(split, 1);
    m_notice = new QLabel("各設備は独立したMQTT接続と状態を持ちます。IPは通常Brokerの接続先です。");
    m_notice->setWordWrap(true);
    layout->addWidget(m_notice);
    setCentralWidget(central);
    connect(m_table, &QTableWidget::currentCellChanged, this, [this](int row, int, int, int) {
        if (row >= 0)
            m_stack->setCurrentIndex(row);
    });
    connect(add, &QPushButton::clicked, this, [this] { showEditor(true); });
    connect(edit, &QPushButton::clicked, this, [this] { showEditor(false); });
    connect(remove, &QPushButton::clicked, this, [this] {
        if (m_table->currentRow() < 0)
            return;
        if (QMessageBox::question(
                this, "設備を削除",
                "選択した設備を一覧から削除します。保存済みの設備状態・指令履歴は残します。") ==
            QMessageBox::Yes)
            removeDevice(m_table->currentRow());
    });
    connect(save, &QPushButton::clicked, this, [this] { saveProfiles(); });
    connect(connectButton, &QPushButton::clicked, this, &FleetWindow::connectAll);
    connect(send, &QPushButton::clicked, this, &FleetWindow::startAll);
    connect(stop, &QPushButton::clicked, this, &FleetWindow::stopAll);
    connect(disconnectButton, &QPushButton::clicked, this, &FleetWindow::disconnectAll);
    m_saveTimer.setSingleShot(true);
    m_saveTimer.setInterval(400);
    connect(&m_saveTimer, &QTimer::timeout, this, [this] { saveProfiles(); });
    if (!QDir().mkpath(QFileInfo(m_profilesPath).absolutePath())) {
        report("設定フォルダーを作成できません。");
        return;
    }
    m_lock = std::make_unique<QLockFile>(m_profilesPath + ".lock");
    if (!m_lock->tryLock(0)) {
        report("この設備一覧は別のアプリが使用中です。");
        return;
    }
    m_initialized = loadProfiles();
    if (m_initialized && !QFileInfo::exists(m_profilesPath))
        saveProfiles();
    refreshList();
    if (!m_panels.isEmpty())
        m_table->selectRow(0);
}

FleetWindow::~FleetWindow() {
    m_saveTimer.stop();
    if (m_initialized)
        saveProfiles();
    for (auto panel : m_panels) {
        disconnect(panel, nullptr, this, nullptr);
        delete panel;
    }
}

void FleetWindow::report(const QString &message) {
    m_error = message;
    m_notice->setText(message);
}

bool FleetWindow::loadProfiles() {
    if (!QFileInfo::exists(m_profilesPath))
        return appendDevice(DeviceProfile{});
    QFile file(m_profilesPath);
    if (file.size() > 1024 * 1024 || !file.open(QIODevice::ReadOnly)) {
        report("設備一覧ファイルを読めません（上限1MiB）。");
        return false;
    }
    QJsonParseError error;
    const auto document = QJsonDocument::fromJson(file.readAll(), &error);
    const auto root = document.object();
    if (error.error != QJsonParseError::NoError || root["schema_version"] != "1.0" ||
        !root["devices"].isArray() || root["devices"].toArray().size() > 64) {
        report("設備一覧の形式が不正です。既存ファイルは上書きしません。");
        return false;
    }
    QList<DeviceProfile> profiles;
    QSet<QString> ids;
    for (const auto &entry : root["devices"].toArray()) {
        auto profile = DeviceProfile::fromJson(entry.toObject());
        if (!profile.validationError().isEmpty() || ids.contains(profile.connection.deviceId)) {
            report("設備一覧に不正な設定・重複した機器IDがあります。");
            return false;
        }
        if (!profile.connection.caFile.isEmpty() &&
            QFileInfo(profile.connection.caFile).isRelative())
            profile.connection.caFile =
                QFileInfo(m_profilesPath).dir().absoluteFilePath(profile.connection.caFile);
        profile.connection.password = qEnvironmentVariable("TMRP_SIMULATOR_PASSWORD");
        ids.insert(profile.connection.deviceId);
        profiles.append(profile);
    }
    for (const auto &profile : profiles)
        if (!appendDevice(profile))
            return false;
    return true;
}

bool FleetWindow::appendDevice(const DeviceProfile &profile) {
    if (m_panels.size() >= 64) {
        report("同時管理の上限は64設備です。");
        return false;
    }
    if (!profile.validationError().isEmpty()) {
        report(profile.validationError());
        return false;
    }
    for (auto panel : m_panels)
        if (panel->profile().connection.deviceId == profile.connection.deviceId) {
            report("同じ機器IDは追加できません。");
            return false;
        }
    auto panel = new MainWindow(profile, m_stateDirectory, m_stack);
    if (!panel->engine()) {
        report("設備状態を開けません。別プロセスでの使用・設備IDの変更を確認してください。");
        delete panel;
        return false;
    }
    panel->setWindowFlags(Qt::Widget);
    panel->lockIdentity();
    m_panels.append(panel);
    m_stack->addWidget(panel);
    connect(panel, &MainWindow::profileChanged, this, [this] {
        refreshList();
        m_saveTimer.start();
    });
    connect(panel, &MainWindow::statusChanged, this, &FleetWindow::refreshList);
    return true;
}

bool FleetWindow::addDevice(const DeviceProfile &profile) {
    if (!m_initialized || !appendDevice(profile))
        return false;
    if (!saveProfiles()) {
        auto panel = m_panels.takeLast();
        disconnect(panel, nullptr, this, nullptr);
        m_stack->removeWidget(panel);
        delete panel;
        refreshList();
        return false;
    }
    refreshList();
    m_table->selectRow(m_panels.size() - 1);
    return true;
}

bool FleetWindow::updateDevice(int index, const DeviceProfile &profile) {
    auto panel = device(index);
    if (!m_initialized || !panel)
        return false;
    const auto old = panel->profile();
    if (!panel->applyProfile(profile)) {
        report(
            "接続・送信・操作を停止して編集してください。機器IDと設備IDは追加後に変更できません。");
        return false;
    }
    if (!saveProfiles()) {
        panel->applyProfile(old);
        refreshList();
        return false;
    }
    refreshList();
    return true;
}

bool FleetWindow::removeDevice(int index) {
    auto panel = device(index);
    if (!m_initialized || !panel)
        return false;
    if (panel->engine()->busy()) {
        report("指令実行中の設備は削除できません。");
        return false;
    }
    m_panels.removeAt(index);
    if (!saveProfiles()) {
        m_panels.insert(index, panel);
        return false;
    }
    disconnect(panel, nullptr, this, nullptr);
    panel->stopConnection();
    m_stack->removeWidget(panel);
    delete panel;
    refreshList();
    if (!m_panels.isEmpty())
        m_table->selectRow(qMin(index, int(m_panels.size()) - 1));
    return true;
}

bool FleetWindow::saveProfiles() {
    if (!m_initialized)
        return false;
    QJsonArray values;
    for (auto panel : m_panels) {
        const auto profile = panel->profile();
        if (!profile.validationError().isEmpty()) {
            report("不正な設定があるため一覧を保存しませんでした。");
            return false;
        }
        values.append(profile.toJson());
    }
    QSaveFile file(m_profilesPath);
    const auto bytes = QJsonDocument(QJsonObject{{"schema_version", "1.0"}, {"devices", values}})
                           .toJson(QJsonDocument::Indented);
    if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size() || !file.commit()) {
        report("設備一覧を保存できません。");
        return false;
    }
    m_notice->setText("設定一覧を保存しました。パスワードは保存されません。");
    return true;
}

void FleetWindow::refreshList() {
    const int selected = m_table->currentRow();
    const QSignalBlocker block(m_table);
    m_table->setRowCount(m_panels.size());
    for (int row = 0; row < m_panels.size(); ++row) {
        auto panel = m_panels[row];
        const auto profile = panel->profile();
        QStringList values = {
            profile.name + " / " + profile.connection.deviceId,
            profile.connection.host + ":" + QString::number(profile.connection.port),
            profile.connection.sourceIp.isEmpty() ? "自動" : profile.connection.sourceIp,
            panel->connectionReady() ? "接続済み"
            : panel->editable()      ? "未接続"
                                     : "接続待ち",
            panel->sending() ? QString::number(profile.rateHz) + " Hz" : "停止",
            panel->engine()->state()["closed"].toBool() ? "CLOSED" : "OPEN"};
        for (int column = 0; column < values.size(); ++column) {
            if (!m_table->item(row, column))
                m_table->setItem(row, column, new QTableWidgetItem);
            m_table->item(row, column)->setText(values[column]);
        }
    }
    if (selected >= 0 && selected < m_panels.size())
        m_table->selectRow(selected);
}

void FleetWindow::connectAll() {
    for (auto panel : m_panels)
        if (panel->editable())
            panel->startConnection();
}
void FleetWindow::startAll() {
    for (auto panel : m_panels)
        panel->startWhenConnected();
}
void FleetWindow::stopAll() {
    for (auto panel : m_panels)
        panel->stopSending();
}
void FleetWindow::disconnectAll() {
    for (auto panel : m_panels)
        panel->stopConnection();
}

void FleetWindow::showEditor(bool adding) {
    if (!m_initialized)
        return;
    const int index = m_table->currentRow();
    auto panel = device(index);
    if (!adding && (!panel || !panel->editable())) {
        report("編集する設備の接続・送信・操作を停止してください。");
        return;
    }
    DeviceProfile profile = adding ? DeviceProfile{} : panel->profile();
    if (adding) {
        for (int number = 1; number <= 65; ++number) {
            const auto suffix = QString("%1").arg(number, 3, 10, QChar('0'));
            const auto id = "power-meter-" + suffix;
            bool used = false;
            for (auto entry : m_panels)
                used |= entry->profile().connection.deviceId == id;
            if (!used) {
                profile.connection.deviceId = id;
                profile.equipmentId = "breaker-" + suffix;
                profile.name = "回線 " + suffix;
                break;
            }
        }
        if (panel) {
            const auto id = profile.connection.deviceId;
            profile.connection = panel->profile().connection;
            profile.connection.deviceId = id;
        }
    }
    QDialog dialog(this);
    dialog.setWindowTitle(adding ? "模擬設備を追加" : "設備の接続設定");
    auto form = new QFormLayout(&dialog);
    auto name = new QLineEdit(profile.name), id = new QLineEdit(profile.connection.deviceId),
         equipment = new QLineEdit(profile.equipmentId),
         host = new QLineEdit(profile.connection.host),
         source = new QLineEdit(profile.connection.sourceIp),
         username = new QLineEdit(profile.connection.username),
         password = new QLineEdit(profile.connection.password),
         ca = new QLineEdit(profile.connection.caFile);
    id->setEnabled(adding);
    equipment->setEnabled(adding);
    password->setEchoMode(QLineEdit::Password);
    auto port = new QSpinBox;
    port->setRange(1, 65535);
    port->setValue(profile.connection.port);
    auto rate = new QDoubleSpinBox;
    rate->setRange(.1, 50);
    rate->setValue(profile.rateHz);
    rate->setSuffix(" Hz");
    auto delay = new QSpinBox;
    delay->setRange(0, 30000);
    delay->setValue(profile.operationDelayMs);
    delay->setSuffix(" ms");
    auto tls = new QCheckBox("TLSを使用");
    tls->setChecked(profile.connection.tls);
    source->setPlaceholderText("このPCのIP。通常は空欄");
    form->addRow("表示名", name);
    form->addRow("機器ID", id);
    form->addRow("設備ID", equipment);
    form->addRow("Broker IP / ホスト名", host);
    form->addRow("ポート", port);
    form->addRow("送信元IP（任意）", source);
    form->addRow("ユーザー", username);
    form->addRow("パスワード（今回のみ）", password);
    form->addRow(tls);
    auto caRow = new QHBoxLayout;
    caRow->addWidget(ca);
    auto browse = new QPushButton("参照");
    caRow->addWidget(browse);
    form->addRow("CA証明書", caRow);
    connect(browse, &QPushButton::clicked, &dialog, [&] {
        const auto path = QFileDialog::getOpenFileName(&dialog, "CA証明書");
        if (!path.isEmpty())
            ca->setText(path);
    });
    form->addRow("送信頻度", rate);
    form->addRow("動作時間", delay);
    auto hint = new QLabel("任意の機器IDはサーバーの台帳にも登録してください。\n遠隔BrokerはTLS、SS"
                           "Hトンネルは127.0.0.1を指定します。");
    form->addRow(hint);
    auto errors = new QLabel;
    errors->setWordWrap(true);
    form->addRow(errors);
    auto buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    form->addRow(buttons);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, [&] {
        profile.name = name->text();
        profile.connection.deviceId = id->text();
        profile.equipmentId = equipment->text();
        profile.connection.host = host->text();
        profile.connection.port = port->value();
        profile.connection.sourceIp = source->text();
        profile.connection.username = username->text();
        profile.connection.password = password->text();
        profile.connection.tls = tls->isChecked();
        profile.connection.caFile = ca->text();
        profile.rateHz = rate->value();
        profile.operationDelayMs = delay->value();
        if (adding ? addDevice(profile) : updateDevice(index, profile))
            dialog.accept();
        else
            errors->setText(m_error);
    });
    dialog.exec();
}
