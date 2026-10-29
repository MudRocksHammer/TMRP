#include "mainwindow.h"
#include <QCheckBox>
#include <QPushButton>
#include <QTemporaryDir>
#include <QtTest>

class WindowTest : public QObject {
    Q_OBJECT
private slots:
    void localControlsAndDisconnectedSending() {
        QTemporaryDir directory;
        MainWindow window({},directory.path()); window.show();
        QVERIFY(window.engine());
        auto open=window.findChild<QPushButton *>("openBreaker");
        auto close=window.findChild<QPushButton *>("closeBreaker");
        auto remote=window.findChild<QCheckBox *>("remoteEnabled");
        QVERIFY(open); QVERIFY(close); QVERIFY(remote);
        QTest::mouseClick(open,Qt::LeftButton); QVERIFY(!window.engine()->state()["closed"].toBool());
        QTest::mouseClick(close,Qt::LeftButton); QVERIFY(window.engine()->state()["closed"].toBool());
        QTest::mouseClick(remote,Qt::LeftButton,Qt::NoModifier,QPoint(8,remote->height()/2));
        QVERIFY(!window.engine()->state()["remote_enabled"].toBool());
        QVERIFY(!window.findChild<QPushButton *>("sendOnce")->isEnabled());
        QVERIFY(!window.findChild<QPushButton *>("startSending")->isEnabled());
        window.setDeviceId("power-meter-002"); QCOMPARE(window.engine()->equipmentId(),"breaker-002");
    }
};
QTEST_MAIN(WindowTest)
#include "test_window.moc"
