#pragma once

#include <QGraphicsObject>
#include <QGraphicsView>
#include <QJsonObject>
#include <functional>

class EquipmentItem final : public QGraphicsObject {
public:
    QString deviceId;
    QString equipmentId;
    QJsonObject telemetry;
    bool online = false;
    bool pending = false;
    explicit EquipmentItem(QString device, QString equipment);
    QRectF boundingRect() const override;
    void paint(QPainter *, const QStyleOptionGraphicsItem *, QWidget *) override;
protected:
    QVariant itemChange(GraphicsItemChange, const QVariant &) override;
};

class Diagram final : public QGraphicsView {
public:
    enum Tool { Select, Add, Wire };
    Tool tool = Select;
    bool editing = false;
    QList<EquipmentItem *> equipment;
    QList<QPair<EquipmentItem *, EquipmentItem *>> wires;
    EquipmentItem *wireStart = nullptr;
    std::function<void(EquipmentItem *)> selected;
    std::function<void(EquipmentItem *, QString)> control;
    std::function<void(QString)> notice;
    explicit Diagram(QWidget *parent = nullptr);
    EquipmentItem *addEquipment(const QString &, const QString &, QPointF);
    void setEditing(bool enabled);
    void save(const QString &path);
    bool load(const QString &path, QString &error);
    void removeEquipment(EquipmentItem *item);
protected:
    void drawBackground(QPainter *, const QRectF &) override;
    void drawForeground(QPainter *, const QRectF &) override;
    void mousePressEvent(QMouseEvent *) override;
    void contextMenuEvent(QContextMenuEvent *) override;
private:
    EquipmentItem *equipmentAt(QPoint point) const;
    void bindEquipment(EquipmentItem *item);
};
