#include "diagram.h"
#include <QContextMenuEvent>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFile>
#include <QFormLayout>
#include <QGraphicsScene>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLineEdit>
#include <QMenu>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPainter>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSet>
#include <cmath>

EquipmentItem::EquipmentItem(QString device, QString equipment)
    : deviceId(std::move(device)), equipmentId(std::move(equipment)) {
    setFlags(ItemIsSelectable | ItemSendsGeometryChanges);
    setToolTip(QStringLiteral("点击查看遥测；右键操作设备"));
}

QRectF EquipmentItem::boundingRect() const { return {-95, -46, 190, 132}; }

void EquipmentItem::paint(QPainter *p, const QStyleOptionGraphicsItem *, QWidget *) {
    p->setRenderHint(QPainter::Antialiasing);
    QColor color = !online ? QColor("#748397") : telemetry["breaker_state"] == "closed"
        ? QColor("#b04436") : telemetry["breaker_state"] == "open"
        ? QColor("#157b65") : QColor("#748397");
    if (isSelected()) {
        p->setPen(QPen(QColor("#176b82"), 1.5, Qt::DashLine));
        p->setBrush(QColor("#e0eff4"));
        p->drawRoundedRect(boundingRect().adjusted(2, 2, -2, -2), 8, 8);
    }
    p->setPen(QPen(color, 3));
    p->setBrush(Qt::white);
    p->drawLine(0, -45, 0, -18);
    p->drawLine(0, 18, 0, 39);
    p->drawRect(-18, -18, 36, 36);
    if (online && telemetry["breaker_state"] == "closed") {
        p->fillRect(-13, -13, 26, 26, color);
    } else {
        p->drawLine(-10, 10, 10, -10);
    }
    p->setPen(QColor("#20364b"));
    p->drawText(QRectF(-92, 40, 184, 20), Qt::AlignCenter, deviceId);
    QString state = !online ? QStringLiteral("离线 / 无新数据")
        : telemetry["breaker_state"] == "closed" ? QStringLiteral("合闸")
        : telemetry["breaker_state"] == "open" ? QStringLiteral("分闸") : QStringLiteral("状态未知");
    if (pending) state += QStringLiteral(" · 指令处理中");
    p->drawText(QRectF(-90, 62, 180, 20), Qt::AlignCenter, state);
    setToolTip(deviceId + " / " + equipmentId + "\n" + state);
}

QVariant EquipmentItem::itemChange(GraphicsItemChange change, const QVariant &value) {
    if (change == ItemPositionChange) {
        auto point = value.toPointF();
        return QPointF(std::round(point.x() / 20.) * 20., std::round(point.y() / 20.) * 20.);
    }
    if (change == ItemPositionHasChanged && scene()) scene()->update();
    return QGraphicsObject::itemChange(change, value);
}

Diagram::Diagram(QWidget *parent) : QGraphicsView(parent) {
    setScene(new QGraphicsScene(this));
    scene()->setSceneRect(-100, -100, 1800, 1100);
    setRenderHint(QPainter::Antialiasing);
    setDragMode(RubberBandDrag);
    setAccessibleName(QStringLiteral("现场线路图，点击设备查看状态，右键设备控制"));
    addEquipment("power-meter-001", "breaker-001", {240, 220});
    addEquipment("power-meter-002", "breaker-002", {580, 220});
    wires.append(qMakePair(equipment[0], equipment[1]));
}

EquipmentItem *Diagram::addEquipment(const QString &device, const QString &target, QPointF pos) {
    auto *item = new EquipmentItem(device, target);
    scene()->addItem(item);
    equipment.append(item);
    item->setPos(pos);
    item->setFlag(QGraphicsItem::ItemIsMovable, editing);
    return item;
}

void Diagram::setEditing(bool enabled) {
    editing = enabled;
    tool = Select;
    wireStart = nullptr;
    for (auto *item : equipment) item->setFlag(QGraphicsItem::ItemIsMovable, enabled);
    viewport()->update();
}

EquipmentItem *Diagram::equipmentAt(QPoint point) const {
    return dynamic_cast<EquipmentItem *>(itemAt(point));
}

void Diagram::drawBackground(QPainter *p, const QRectF &area) {
    p->fillRect(area, QColor("#f7fafc"));
    p->setPen(QPen(QColor("#dce5ec"), 1));
    const int left = int(std::floor(area.left() / 20.)) * 20;
    const int top = int(std::floor(area.top() / 20.)) * 20;
    for (int x = left; x < area.right(); x += 20)
        for (int y = top; y < area.bottom(); y += 20) p->drawPoint(x, y);
    p->setPen(QPen(QColor("#637c90"), 3));
    for (const auto &wire : wires) {
        const auto a = wire.first->pos() + QPointF(0, -45);
        const auto b = wire.second->pos() + QPointF(0, -45);
        double bus = qMin(a.y(), b.y()) - 55;
        p->drawLine(a, QPointF(a.x(), bus));
        p->drawLine(QPointF(a.x(), bus), QPointF(b.x(), bus));
        p->drawLine(QPointF(b.x(), bus), b);
    }
}

void Diagram::drawForeground(QPainter *p, const QRectF &) {
    if (!wireStart) return;
    p->setPen(QPen(QColor("#c47a19"), 2, Qt::DashLine));
    p->drawEllipse(wireStart->pos(), 28, 28);
}

void Diagram::mousePressEvent(QMouseEvent *event) {
    auto *item = equipmentAt(event->pos());
    if (event->button() == Qt::LeftButton && editing && tool == Add && !item) {
        auto *added = addEquipment("", "", mapToScene(event->pos()));
        bindEquipment(added);
        if (added->deviceId.isEmpty()) removeEquipment(added);
        return;
    }
    if (event->button() == Qt::LeftButton && editing && tool == Wire && item) {
        if (!wireStart) {
            wireStart = item;
            if (notice) notice(QStringLiteral("选择线路另一端设备；再次点击起点可取消"));
        } else {
            if (wireStart != item && !wires.contains({wireStart, item}) && !wires.contains({item, wireStart}))
                wires.append(qMakePair(wireStart, item));
            wireStart = nullptr;
            scene()->invalidate();
        }
        viewport()->update();
        return;
    }
    QGraphicsView::mousePressEvent(event);
    if (item && selected) selected(item);
}

void Diagram::bindEquipment(EquipmentItem *item) {
    QDialog dialog(this);
    dialog.setWindowTitle(QStringLiteral("绑定设备"));
    auto *form = new QFormLayout(&dialog);
    QLineEdit device(item->deviceId), target(item->equipmentId);
    form->addRow(QStringLiteral("设备 ID"), &device);
    form->addRow(QStringLiteral("断路器 ID"), &target);
    QDialogButtonBox buttons(QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    form->addRow(&buttons);
    QObject::connect(&buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    QObject::connect(&buttons, &QDialogButtonBox::accepted, &dialog, [&] {
        const QRegularExpression id("^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$");
        if (!id.match(device.text()).hasMatch() || !id.match(target.text()).hasMatch()) {
            QMessageBox::warning(&dialog, QStringLiteral("绑定失败"), QStringLiteral("ID 需为 1–128 个英文字母、数字、下划线、连字符或点。"));
            return;
        }
        for (auto *other : equipment) if (other != item && other->deviceId == device.text()) {
            QMessageBox::warning(&dialog, QStringLiteral("绑定失败"), QStringLiteral("此设备已在线路图中。"));
            return;
        }
        item->deviceId = device.text();
        item->equipmentId = target.text();
        item->online = false;
        item->telemetry = {};
        item->update();
        dialog.accept();
    });
    dialog.exec();
}

void Diagram::removeEquipment(EquipmentItem *item) {
    if (selected) selected(nullptr);
    for (qsizetype i = wires.size(); i-- > 0;)
        if (wires[i].first == item || wires[i].second == item) wires.removeAt(i);
    if (wireStart == item) wireStart = nullptr;
    equipment.removeOne(item);
    delete item;
    scene()->invalidate();
}

void Diagram::contextMenuEvent(QContextMenuEvent *event) {
    auto *item = equipmentAt(event->pos());
    if (!item) return;
    if (selected) selected(item);
    QMenu menu(this);
    if (editing) {
        auto *bind = menu.addAction(QStringLiteral("绑定设备 ID…"));
        auto *disconnect = menu.addAction(QStringLiteral("删除此设备的连线"));
        auto *remove = menu.addAction(QStringLiteral("删除图中设备"));
        auto *action = menu.exec(event->globalPos());
        if (action == bind) bindEquipment(item);
        if (action == disconnect) {
            for (qsizetype i = wires.size(); i-- > 0;)
                if (wires[i].first == item || wires[i].second == item) wires.removeAt(i);
            scene()->invalidate();
        }
        if (action == remove) removeEquipment(item);
    } else {
        auto *open = menu.addAction(QStringLiteral("分闸"));
        auto *close = menu.addAction(QStringLiteral("合闸"));
        open->setEnabled(item->online && !item->pending);
        close->setEnabled(item->online && !item->pending);
        menu.addSeparator();
        menu.addAction(item->online ? QStringLiteral("操作结果以设备回执为准") : QStringLiteral("离线或数据过期，无法控制"))->setEnabled(false);
        auto *action = menu.exec(event->globalPos());
        if (action && (action == open || action == close) && control)
            control(item, action == open ? "open_breaker" : "close_breaker");
    }
}

void Diagram::save(const QString &path) {
    QJsonArray nodes, connections;
    for (auto *item : equipment) nodes.append(QJsonObject{
        {"device_id", item->deviceId}, {"equipment_id", item->equipmentId},
        {"x", item->pos().x()}, {"y", item->pos().y()}});
    for (const auto &wire : wires) connections.append(QJsonArray{wire.first->deviceId, wire.second->deviceId});
    QSaveFile file(path);
    QByteArray bytes = QJsonDocument(QJsonObject{{"schema_version", "1.0"}, {"nodes", nodes}, {"wires", connections}}).toJson();
    if (!file.open(QIODevice::WriteOnly) || file.write(bytes) != bytes.size() || !file.commit()) {
        if (notice) notice(QStringLiteral("保存失败：") + file.errorString());
        return;
    }
    if (notice) notice(QStringLiteral("线路图已保存：") + path);
}

bool Diagram::load(const QString &path, QString &error) {
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly) || file.size() > 1024 * 1024) {
        error = QStringLiteral("无法读取文件或文件超过 1 MB"); return false;
    }
    QJsonParseError parse;
    auto document = QJsonDocument::fromJson(file.readAll(), &parse);
    const auto object = document.object();
    auto fail = [&] { error = QStringLiteral("线路图格式无效，原图已保留"); return false; };
    if (parse.error != QJsonParseError::NoError || object["schema_version"] != "1.0"
        || !object["nodes"].isArray() || !object["wires"].isArray()) return fail();
    const auto nodes = object["nodes"].toArray(), connections = object["wires"].toArray();
    if (nodes.size() > 200 || connections.size() > 1000) return fail();
    QSet<QString> ids, edges;
    const QRegularExpression validId("^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$");
    for (const auto &entry : nodes) {
        auto n = entry.toObject();
        auto id = n["device_id"].toString();
        if (!validId.match(id).hasMatch() || !validId.match(n["equipment_id"].toString()).hasMatch()
            || ids.contains(id) || !n["x"].isDouble() || !n["y"].isDouble()
            || std::abs(n["x"].toDouble()) > 10000 || std::abs(n["y"].toDouble()) > 10000) return fail();
        ids.insert(id);
    }
    for (const auto &entry : connections) {
        auto edge = entry.toArray();
        if (edge.size() != 2 || !ids.contains(edge[0].toString()) || !ids.contains(edge[1].toString())
            || edge[0] == edge[1]) return fail();
        auto names = QStringList{edge[0].toString(), edge[1].toString()};
        names.sort();
        auto key = names.join('/');
        if (edges.contains(key)) return fail();
        edges.insert(key);
    }
    if (selected) selected(nullptr);
    wireStart = nullptr;
    wires.clear();
    qDeleteAll(equipment);
    equipment.clear();
    QMap<QString, EquipmentItem *> byId;
    for (const auto &entry : nodes) {
        auto n = entry.toObject();
        auto *item = addEquipment(n["device_id"].toString(), n["equipment_id"].toString(), {n["x"].toDouble(), n["y"].toDouble()});
        byId.insert(item->deviceId, item);
    }
    for (const auto &entry : connections) {
        auto e = entry.toArray();
        wires.append(qMakePair(byId[e[0].toString()], byId[e[1].toString()]));
    }
    scene()->invalidate();
    return true;
}
