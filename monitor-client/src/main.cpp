#include "diagram.h"
#include "telemetrystream.h"
#include <QApplication>
#include <QDateTime>
#include <QFileDialog>
#include <QFormLayout>
#include <QFontDatabase>
#include <QGraphicsScene>
#include <QHeaderView>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QMainWindow>
#include <QMessageBox>
#include <QNetworkAccessManager>
#include <QNetworkReply>
#include <QPainter>
#include <QPainterPath>
#include <QPalette>
#include <QPushButton>
#include <QSettings>
#include <QSplitter>
#include <QStatusBar>
#include <QTableWidget>
#include <QTimer>
#include <QToolBar>
#include <QUuid>
#include <QVBoxLayout>
#include <cmath>
#include <limits>

class Trend final : public QWidget {
public:
    QVector<double> values;
    explicit Trend(QWidget *parent = nullptr) : QWidget(parent) { setMinimumHeight(160); }
protected:
    void paintEvent(QPaintEvent *) override {
        QPainter p(this);
        p.setRenderHint(QPainter::Antialiasing);
        QRectF plot = QRectF(rect()).adjusted(48, 15, -15, -25);
        if (values.isEmpty()) {
            p.setPen(QColor("#637c90"));
            p.drawText(plot, Qt::AlignCenter, QStringLiteral("等待设备遥测")); return;
        }
        double low = 0, high = 1;
        for (double value : values) if (std::isfinite(value)) {
            low = qMin(low, value); high = qMax(high, value);
        }
        high += (high - low) * .1;
        for (int i = 0; i <= 4; ++i) {
            double y = plot.bottom() - plot.height() * i / 4.;
            p.setPen(QColor("#b5c4d0"));
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y));
            p.setPen(QColor("#637c90"));
            p.drawText(QRectF(0, y - 10, 42, 20), Qt::AlignRight, QString::number(low + (high - low) * i / 4., 'f', 0));
        }
        QPainterPath path;
        bool gap = true;
        for (qsizetype i = 0; i < values.size(); ++i) {
            if (!std::isfinite(values[i])) { gap = true; continue; }
            QPointF point(plot.left() + plot.width() * double(i) / qMax(1., double(values.size() - 1)),
                          plot.bottom() - plot.height() * (values[i] - low) / (high - low));
            if (gap) path.moveTo(point); else path.lineTo(point);
            gap = false;
        }
        p.setPen(QPen(QColor("#087e8b"), 2)); p.drawPath(path);
    }
};

struct Pending {
    QString device;
    int row;
    qint64 sent;
    bool terminal = false;
};

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    app.setOrganizationName("TMRP");
    app.setApplicationName("MonitorClient");
    app.setStyle("Fusion");
    QPalette palette;
    palette.setColor(QPalette::Window, QColor("#edf2f6"));
    palette.setColor(QPalette::WindowText, QColor("#20364b"));
    palette.setColor(QPalette::Base, Qt::white);
    palette.setColor(QPalette::Text, QColor("#20364b"));
    palette.setColor(QPalette::Button, QColor("#e3ebf1"));
    palette.setColor(QPalette::ButtonText, QColor("#20364b"));
    palette.setColor(QPalette::Highlight, QColor("#176b82"));
    palette.setColor(QPalette::HighlightedText, Qt::white);
    app.setPalette(palette);
    app.setFont(QFont("Microsoft YaHei UI", 10));
    QString fontPath = qEnvironmentVariable("TMRP_MONITOR_FONT");
#ifdef Q_OS_WIN
    if (fontPath.isEmpty() && app.platformName() == "offscreen")
        fontPath = qEnvironmentVariable("WINDIR", "C:/Windows") + "/Fonts/msyh.ttc";
#endif
    if (!fontPath.isEmpty()) {
        int id = QFontDatabase::addApplicationFont(fontPath);
        auto families = QFontDatabase::applicationFontFamilies(id);
        if (!families.isEmpty()) app.setFont(QFont(families.first(), 10));
    }
    app.setStyleSheet(R"(
        QMainWindow { background: #edf2f6; }
        QLabel { color: #20364b; }
        QLineEdit { padding: 6px; border: 1px solid #bdcad6; border-radius: 4px; }
        QPushButton { padding: 7px 14px; }
        QToolBar { padding: 5px; spacing: 7px; background: #e3ebf1; }
        QTableWidget { background: white; border: 1px solid #cbd5df; }
        QHeaderView::section { background: #e4ebf1; padding: 6px; border: 0; }
    )");
    QMainWindow window;
    window.setWindowTitle(QStringLiteral("TMRP · 现场线路监控"));
    window.resize(1380, 900);
    QSettings settings;
    auto *root = new QWidget;
    auto *layout = new QVBoxLayout(root);
    auto *connection = new QHBoxLayout;
    auto *url = new QLineEdit(settings.value("gateway", "http://127.0.0.1:8081").toString());
    url->setAccessibleName(QStringLiteral("服务器监控网关地址"));
    auto *token = new QLineEdit(qEnvironmentVariable("TMRP_MONITOR_TOKEN"));
    token->setEchoMode(QLineEdit::Password);
    token->setPlaceholderText(QStringLiteral("访问令牌（不保存）"));
    token->setAccessibleName(QStringLiteral("服务器访问令牌"));
    auto *connect = new QPushButton(QStringLiteral("连接服务器"));
    connection->addWidget(new QLabel(QStringLiteral("服务器")));
    connection->addWidget(url, 2); connection->addWidget(token, 1); connection->addWidget(connect);
    layout->addLayout(connection);
    auto *status = new QLabel(QStringLiteral("未连接 · 图中设备尚无真实状态"));
    status->setWordWrap(true); layout->addWidget(status);
    auto *split = new QSplitter;
    auto *diagram = new Diagram; split->addWidget(diagram);
    auto *details = new QWidget; details->setMinimumWidth(280);
    auto *detailLayout = new QVBoxLayout(details);
    auto *name = new QLabel(QStringLiteral("点击图中的断路器查看遥测"));
    name->setWordWrap(true); detailLayout->addWidget(name);
    auto *form = new QFormLayout;
    QStringList keys{"voltage_ab_v", "current_a_a", "active_power_kw", "frequency_hz", "breaker_state", "quality", "event_time"};
    QStringList labels{QStringLiteral("线电压 AB / V"), QStringLiteral("A 相电流 / A"), QStringLiteral("有功功率 / kW"), QStringLiteral("频率 / Hz"), QStringLiteral("断路器"), QStringLiteral("数据质量"), QStringLiteral("采样时间 / UTC")};
    QVector<QLabel *> values;
    for (const auto &label : labels) {
        auto *value = new QLabel(QStringLiteral("—")); value->setWordWrap(true);
        values.append(value); form->addRow(label, value);
    }
    detailLayout->addLayout(form);
    detailLayout->addWidget(new QLabel(QStringLiteral("有功功率 / kW · 最近 60 个采样点")));
    auto *trend = new Trend; detailLayout->addWidget(trend);
    auto *legend = new QLabel(QStringLiteral("■ 红色实心：合闸\n□ 绿色斜线：分闸\n□ 灰色：离线或状态未知\n\n线路仅表达现场示意连接，不计算潮流或带电范围。"));
    legend->setWordWrap(true); detailLayout->addWidget(legend);
    detailLayout->addStretch(); split->addWidget(details); split->setSizes({970, 360});
    layout->addWidget(split, 1);
    layout->addWidget(new QLabel(QStringLiteral("控制记录 · 提交 / 受理不代表执行成功；完成状态以设备回执为准")));
    auto *commands = new QTableWidget(0, 4);
    commands->setHorizontalHeaderLabels({QStringLiteral("本地时间"), QStringLiteral("设备 / 断路器"), QStringLiteral("操作 / 指令 ID"), QStringLiteral("结果")});
    commands->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    commands->setEditTriggers(QAbstractItemView::NoEditTriggers);
    commands->setMaximumHeight(180); layout->addWidget(commands);
    window.setCentralWidget(root);
    auto *toolbar = window.addToolBar(QStringLiteral("线路图绘制"));
    auto *edit = toolbar->addAction(QStringLiteral("编辑线路图")); edit->setCheckable(true);
    auto *select = toolbar->addAction(QStringLiteral("选择 / 拖动"));
    auto *add = toolbar->addAction(QStringLiteral("添加断路器"));
    auto *wire = toolbar->addAction(QStringLiteral("连接设备"));
    toolbar->addSeparator();
    auto *save = toolbar->addAction(QStringLiteral("保存线路图"));
    auto *load = toolbar->addAction(QStringLiteral("载入线路图"));
    auto *fit = toolbar->addAction(QStringLiteral("适应画面"));
    select->setEnabled(false); add->setEnabled(false); wire->setEnabled(false);
    EquipmentItem *current = nullptr;
    QMap<QString, QVector<double>> histories;
    QMap<QString, QString> lastSamples;
    QMap<QString, Pending> pending;
    QNetworkAccessManager network;
    TelemetryStream stream;
    bool receiving = false, connected = false;
    qint64 lastSnapshot = 0;
    QUrl base;
    QByteArray credential;
    int generation = 0;
    auto render = [&] {
        if (!current) {
            name->setText(QStringLiteral("点击图中的断路器查看遥测"));
            for (auto *value : values) value->setText(QStringLiteral("—"));
            trend->values.clear(); trend->update(); return;
        }
        name->setText(current->deviceId + "\n" + current->equipmentId + (current->online ? QStringLiteral(" · 在线") : QStringLiteral(" · 离线 / 数据过期")));
        for (qsizetype i = 0; i < keys.size(); ++i) {
            auto v = current->telemetry[keys[i]];
            QString text = v.isDouble() ? QString::number(v.toDouble(), 'f', 2) : v.toString();
            if (text.isEmpty()) text = QStringLiteral("—");
            if (text == "closed") text = QStringLiteral("合闸");
            if (text == "open") text = QStringLiteral("分闸");
            if (text == "unknown") text = QStringLiteral("未知");
            values[i]->setText(text);
        }
        trend->values = histories.value(current->deviceId); trend->update();
    };
    diagram->selected = [&](EquipmentItem *item) { current = item; render(); };
    diagram->notice = [&](const QString &message) { window.statusBar()->showMessage(message, 7000); };
    auto refreshPending = [&] {
        for (auto *item : diagram->equipment) {
            item->pending = false;
            for (const auto &p : pending) if (!p.terminal && p.device == item->deviceId) item->pending = true;
            item->update();
        }
    };
    auto offline = [&] {
        connected = false;
        for (auto *item : diagram->equipment) { item->online = false; item->update(); }
        render();
    };
    auto request = [&](QString path) {
        QUrl target = base; target.setPath(path);
        QNetworkRequest r(target);
        r.setRawHeader("Authorization", "Bearer " + credential);
        r.setHeader(QNetworkRequest::ContentTypeHeader, "application/json");
        r.setTransferTimeout(4000);
        r.setAttribute(QNetworkRequest::RedirectPolicyAttribute, QNetworkRequest::ManualRedirectPolicy);
        return r;
    };
    QObject::connect(&stream, &TelemetryStream::snapshotReceived, &window, [&](const QJsonObject &snapshot) {
        connected = true; lastSnapshot = QDateTime::currentMSecsSinceEpoch();
        for (auto *item : diagram->equipment) {
            item->online = false;
            for (const auto &entry : snapshot["devices"].toArray()) {
                auto d = entry.toObject();
                if (d["device_id"] != item->deviceId || d["equipment_id"] != item->equipmentId) continue;
                item->telemetry = d["telemetry"].toObject();
                item->online = snapshot["mqtt_ready"].toBool() && d["online"].toBool();
                QString sample = item->telemetry["boot_id"].toString() + ":" + QString::number(item->telemetry["sequence_no"].toDouble(), 'f', 0);
                if (!item->telemetry.isEmpty() && lastSamples.value(item->deviceId) != sample) {
                    auto &history = histories[item->deviceId];
                    auto power = item->telemetry["active_power_kw"];
                    history.append(power.isDouble() ? power.toDouble() : std::numeric_limits<double>::quiet_NaN());
                    if (history.size() > 60) history.removeFirst();
                    lastSamples[item->deviceId] = sample;
                }
            }
            item->update();
        }
        const QMap<QString, QString> translated{{"submitted", QStringLiteral("已提交，等待设备")}, {"accepted", QStringLiteral("设备已受理")}, {"completed", QStringLiteral("执行完成")}, {"rejected", QStringLiteral("设备拒绝")}, {"failed", QStringLiteral("执行失败")}, {"unknown", QStringLiteral("超时，结果未知，请核实设备状态")}};
        for (const auto &entry : snapshot["commands"].toArray()) {
            auto command = entry.toObject(); auto id = command["command_id"].toString();
            auto found = pending.find(id);
            if (found == pending.end() || found->device != command["device_id"].toString()) continue;
            auto state = command["status"].toString();
            if (!translated.contains(state)) continue;
            auto reason = command["result"].toObject()["reason"].toString();
            commands->item(found->row, 3)->setText(translated[state] + (reason.isEmpty() ? "" : " / " + reason));
            found->terminal = state == "completed" || state == "rejected" || state == "failed" || state == "unknown";
        }
        refreshPending(); render();
        status->setText(snapshot["mqtt_ready"].toBool() ? QStringLiteral("服务器已连接 · WebSocket 实时遥测 · 运行模式下右键设备控制") : QStringLiteral("网关已连接，但 MQTT 尚未就绪；设备控制已禁用"));
    });
    QObject::connect(&stream, &TelemetryStream::unavailable, &window, [&](const QString &reason) {
        offline(); status->setText(reason);
    });
    QObject::connect(connect, &QPushButton::clicked, &window, [&] {
        if (receiving) {
            receiving = false; stream.stop(); ++generation; offline(); credential.clear();
            connect->setText(QStringLiteral("连接服务器")); url->setEnabled(true); token->setEnabled(true);
            status->setText(QStringLiteral("已断开服务器")); return;
        }
        QUrl candidate(url->text().trimmed());
        bool local = candidate.host() == "127.0.0.1" || candidate.host() == "localhost" || candidate.host() == "::1";
        if (!candidate.isValid() || candidate.host().isEmpty() || !candidate.userInfo().isEmpty()
            || !candidate.query().isEmpty() || !candidate.fragment().isEmpty()
            || (candidate.path() != "" && candidate.path() != "/")
            || !(candidate.scheme() == "https" || (candidate.scheme() == "http" && local))
            || token->text().size() < 24) {
            QMessageBox::warning(&window, QStringLiteral("连接设置无效"), QStringLiteral("请输入 HTTPS 服务地址或本机 HTTP 隧道地址（不含路径），以及至少 24 字符的访问令牌。")); return;
        }
        base = candidate; credential = token->text().toUtf8(); ++generation;
        histories.clear(); lastSamples.clear();
        for (auto *item : diagram->equipment) item->telemetry = {};
        settings.setValue("gateway", candidate.toString());
        url->setEnabled(false); token->setEnabled(false); connect->setText(QStringLiteral("断开服务器"));
        receiving = true;
        status->setText(QStringLiteral("正在连接 WebSocket，等待遥测快照…"));
        stream.start(base, credential);
    });
    QTimer watchdog; watchdog.setInterval(1000);
    QObject::connect(&watchdog, &QTimer::timeout, &window, [&] {
        qint64 now = QDateTime::currentMSecsSinceEpoch();
        if (connected && now - lastSnapshot > 5000) { offline(); status->setText(QStringLiteral("服务器响应超时，设备状态已过期")); }
        for (auto &p : pending) if (!p.terminal && now - p.sent > 22000) {
            p.terminal = true;
            commands->item(p.row, 3)->setText(QStringLiteral("超时，结果未知；核实设备状态后再操作"));
        }
        refreshPending();
    });
    watchdog.start();
    diagram->control = [&](EquipmentItem *item, const QString &operation) {
        if (!connected || !item->online || item->pending || diagram->editing) return;
        const QString device = item->deviceId, equipment = item->equipmentId;
        const auto epoch = generation;
        const QString action = operation == "open_breaker" ? QStringLiteral("分闸") : QStringLiteral("合闸");
        if (QMessageBox::question(&window, QStringLiteral("确认设备操作"),
            QStringLiteral("向服务器发送 %1 指令？\n设备：%2\n断路器：%3").arg(action, device, equipment),
            QMessageBox::Yes | QMessageBox::No, QMessageBox::No) != QMessageBox::Yes) return;
        if (epoch != generation || !connected || !item->online || item->pending) return;
        const QString id = QUuid::createUuid().toString(QUuid::WithoutBraces);
        int row = commands->rowCount(); commands->insertRow(row);
        const QStringList cells{QDateTime::currentDateTime().toString("HH:mm:ss"), device + " / " + equipment, action + " / " + id, QStringLiteral("发送中")};
        for (int i = 0; i < cells.size(); ++i) commands->setItem(row, i, new QTableWidgetItem(cells[i]));
        commands->scrollToBottom();
        pending.insert(id, {device, row, QDateTime::currentMSecsSinceEpoch(), false});
        refreshPending();
        auto payload = QJsonDocument(QJsonObject{{"command_id", id}, {"device_id", device}, {"equipment_id", equipment}, {"operation", operation}}).toJson(QJsonDocument::Compact);
        auto *reply = network.post(request("/api/commands"), payload);
        QObject::connect(reply, &QNetworkReply::finished, &window, [&, reply, id] {
            reply->deleteLater();
            auto &p = pending[id];
            if (p.terminal) return;
            auto object = QJsonDocument::fromJson(reply->readAll()).object();
            int code = reply->attribute(QNetworkRequest::HttpStatusCodeAttribute).toInt();
            if (code >= 400 && code < 500 && object.contains("error")) {
                commands->item(p.row, 3)->setText(QStringLiteral("网关拒绝：") + object["error"].toString()); p.terminal = true;
            } else if (reply->error() != QNetworkReply::NoError || code != 202 || object["command_id"] != id) {
                commands->item(p.row, 3)->setText(QStringLiteral("发送结果未知，正在等待设备回执"));
            } else if (commands->item(p.row, 3)->text() == QStringLiteral("发送中")) {
                commands->item(p.row, 3)->setText(QStringLiteral("已提交，等待设备回执"));
            }
            refreshPending();
        });
    };
    QObject::connect(edit, &QAction::toggled, &window, [&](bool enabled) {
        diagram->setEditing(enabled);
        select->setEnabled(enabled); add->setEnabled(enabled); wire->setEnabled(enabled);
        window.statusBar()->showMessage(enabled ? QStringLiteral("编辑模式：拖动设备或选择添加、连线工具；右键修改绑定、删除设备或连线") : QStringLiteral("运行模式：点击设备查看遥测，右键控制"));
    });
    QObject::connect(select, &QAction::triggered, &window, [&] { diagram->tool = Diagram::Select; diagram->wireStart = nullptr; diagram->viewport()->update(); });
    QObject::connect(add, &QAction::triggered, &window, [&] { diagram->tool = Diagram::Add; diagram->wireStart = nullptr; window.statusBar()->showMessage(QStringLiteral("点击图中空白位置添加断路器")); });
    QObject::connect(wire, &QAction::triggered, &window, [&] { diagram->tool = Diagram::Wire; diagram->wireStart = nullptr; window.statusBar()->showMessage(QStringLiteral("依次点击两台设备创建连线")); });
    QObject::connect(save, &QAction::triggered, &window, [&] {
        auto path = QFileDialog::getSaveFileName(&window, QStringLiteral("保存线路图"), "site-diagram.json", "JSON (*.json)");
        if (!path.isEmpty()) diagram->save(path);
    });
    QObject::connect(load, &QAction::triggered, &window, [&] {
        if (QMessageBox::question(&window, QStringLiteral("载入线路图"), QStringLiteral("载入将替换当前布局。请先保存需要保留的修改，是否继续？")) != QMessageBox::Yes) return;
        auto path = QFileDialog::getOpenFileName(&window, QStringLiteral("载入线路图"), {}, "JSON (*.json)");
        if (path.isEmpty()) return;
        QString error;
        if (!diagram->load(path, error)) QMessageBox::warning(&window, QStringLiteral("载入失败"), error);
        else { histories.clear(); lastSamples.clear(); refreshPending(); }
    });
    QObject::connect(fit, &QAction::triggered, &window, [&] {
        if (!diagram->equipment.isEmpty()) diagram->fitInView(diagram->scene()->itemsBoundingRect().adjusted(-80, -100, 80, 80), Qt::KeepAspectRatio);
    });
    window.show(); diagram->centerOn(400, 240);
    if (app.arguments().contains("--screenshot")) QTimer::singleShot(400, &window, [&] {
        window.grab().save("monitor-client/build/monitor-preview.png");
    });
    if (app.arguments().contains("--smoke-test")) QTimer::singleShot(1500, &app, &QApplication::quit);
    return app.exec();
}
