#include "diagram.h"
#include <QFile>
#include <QContextMenuEvent>
#include <QGraphicsScene>
#include <QImage>
#include <QMenu>
#include <QPainter>
#include <QTemporaryDir>
#include <QTimer>
#include <QtTest>

class DiagramTest final : public QObject {
    Q_OBJECT
private slots:
    void rightClickControlsRequireOnlineDevice() {
        Diagram diagram;
        diagram.resize(900, 500);
        diagram.show();
        diagram.centerOn(400, 220);
        auto *item = diagram.equipment[0];
        QString operation;
        diagram.control = [&](EquipmentItem *target, QString action) {
            QCOMPARE(target, item);
            operation = action;
        };
        bool inspected = false;
        QTimer::singleShot(10, &diagram, [&] {
            auto *menu = qobject_cast<QMenu *>(QApplication::activePopupWidget());
            if (!menu) return;
            inspected = !menu->actions()[0]->isEnabled() && !menu->actions()[1]->isEnabled();
            menu->close();
        });
        auto point = diagram.mapFromScene(item->pos());
        QContextMenuEvent offline(QContextMenuEvent::Mouse, point, diagram.viewport()->mapToGlobal(point));
        QApplication::sendEvent(diagram.viewport(), &offline);
        QVERIFY(inspected);
        QVERIFY(operation.isEmpty());
        item->online = true;
        QTimer::singleShot(10, &diagram, [&] {
            auto *menu = qobject_cast<QMenu *>(QApplication::activePopupWidget());
            if (!menu) return;
            menu->setActiveAction(menu->actions()[0]);
            QTest::keyClick(menu, Qt::Key_Return);
        });
        QContextMenuEvent online(QContextMenuEvent::Mouse, point, diagram.viewport()->mapToGlobal(point));
        QApplication::sendEvent(diagram.viewport(), &online);
        QCOMPARE(operation, QString("open_breaker"));
    }
    void drawingRoundTrip() {
        QTemporaryDir temp;
        QVERIFY(temp.isValid());
        Diagram diagram;
        diagram.setEditing(true);
        auto *third = diagram.addEquipment("power-meter-003", "breaker-003", {411, 319});
        QCOMPARE(third->pos(), QPointF(420, 320));
        diagram.wires.append(qMakePair(diagram.equipment[1], third));
        QString path = temp.filePath("site.json");
        diagram.save(path);
        Diagram loaded;
        QString error;
        QVERIFY2(loaded.load(path, error), qPrintable(error));
        QCOMPARE(loaded.equipment.size(), 3);
        QCOMPARE(loaded.wires.size(), 2);
        QCOMPARE(loaded.equipment[2]->deviceId, QString("power-meter-003"));
        QCOMPARE(loaded.equipment[2]->equipmentId, QString("breaker-003"));
        QCOMPARE(loaded.equipment[2]->pos(), QPointF(420, 320));
        QVERIFY(!loaded.equipment[2]->online);
        loaded.removeEquipment(loaded.equipment[1]);
        QCOMPARE(loaded.equipment.size(), 2);
        QVERIFY(loaded.wires.isEmpty());
    }
    void invalidFilePreservesDrawing() {
        QTemporaryDir temp;
        QFile file(temp.filePath("bad.json"));
        QVERIFY(file.open(QIODevice::WriteOnly));
        file.write(R"({"schema_version":"1.0","nodes":[],"wires":[["missing","target"]]})");
        file.close();
        Diagram diagram;
        auto *original = diagram.equipment[0];
        QString error;
        QVERIFY(!diagram.load(file.fileName(), error));
        QCOMPARE(diagram.equipment[0], original);
        QCOMPARE(diagram.wires.size(), 1);
    }
    void selectAndRender() {
        Diagram diagram;
        diagram.resize(900, 500);
        diagram.show();
        diagram.centerOn(400, 220);
        EquipmentItem *selected = nullptr;
        diagram.selected = [&](EquipmentItem *item) { selected = item; };
        auto *first = diagram.equipment[0];
        QTest::mouseClick(diagram.viewport(), Qt::LeftButton, Qt::NoModifier,
                          diagram.mapFromScene(first->pos()));
        QCOMPARE(selected, first);
        first->online = true;
        first->telemetry = {{"breaker_state", "closed"}};
        QImage image(900, 500, QImage::Format_ARGB32);
        image.fill(Qt::white);
        QPainter painter(&image);
        diagram.render(&painter);
        QVERIFY(!image.isNull());
        diagram.setEditing(true);
        QVERIFY(first->flags().testFlag(QGraphicsItem::ItemIsMovable));
        diagram.setEditing(false);
        QVERIFY(!first->flags().testFlag(QGraphicsItem::ItemIsMovable));
    }
};
QTEST_MAIN(DiagramTest)
#include "test_diagram.moc"
