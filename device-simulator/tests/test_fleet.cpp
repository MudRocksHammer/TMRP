#include "fleetwindow.h"
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QTemporaryDir>
#include <QtTest>

class FleetTest : public QObject {
    Q_OBJECT
  private slots:
    void addEditRemoveReloadAndIsolation() {
        QTemporaryDir directory;
        const auto path = directory.filePath("devices.json");
        {
            FleetWindow fleet(path, directory.path());
            QVERIFY(fleet.initialized());
            QCOMPARE(fleet.deviceCount(), 1);
            DeviceProfile second;
            second.name = "回線002";
            second.connection.deviceId = "power-meter-002";
            second.equipmentId = "breaker-002";
            second.connection.host = "192.168.237.128";
            second.connection.port = 8883;
            second.connection.tls = true;
            second.connection.password = "not-written-to-json";
            second.rateHz = 2;
            QVERIFY(fleet.addDevice(second));
            QCOMPARE(fleet.deviceCount(), 2);
            QVERIFY(!fleet.addDevice(second));
            QVERIFY(fleet.device(0)->engine()->updateLocalState({{"closed", false}}));
            QVERIFY(fleet.device(1)->engine()->state()["closed"].toBool());
            QVERIFY(fleet.device(0)->engine()->bootId() != fleet.device(1)->engine()->bootId());
            second.connection.port = 8884;
            QVERIFY(fleet.updateDevice(1, second));
            QCOMPARE(fleet.device(1)->profile().connection.port, 8884);
            QFile file(path);
            QVERIFY(file.open(QIODevice::ReadOnly));
            const auto bytes = file.readAll();
            QVERIFY(!bytes.contains("not-written-to-json"));
            QVERIFY(!bytes.contains("password"));
        }
        {
            FleetWindow restored(path, directory.path());
            QVERIFY(restored.initialized());
            QCOMPARE(restored.deviceCount(), 2);
            QCOMPARE(restored.device(1)->profile().connection.port, 8884);
            QVERIFY(!restored.device(0)->engine()->state()["closed"].toBool());
            QVERIFY(restored.device(1)->engine()->state()["closed"].toBool());
            QVERIFY(restored.removeDevice(1));
            QCOMPARE(restored.deviceCount(), 1);
            QVERIFY(QFile::exists(directory.filePath("power-meter-002.sqlite")));
        }
        FleetWindow again(path, directory.path());
        QVERIFY(again.initialized());
        QCOMPARE(again.deviceCount(), 1);
    }
    void corruptedProfilesNotOverwritten() {
        QTemporaryDir directory;
        const auto path = directory.filePath("devices.json");
        {
            QFile file(path);
            QVERIFY(file.open(QIODevice::WriteOnly));
            file.write("not JSON");
        }
        {
            FleetWindow fleet(path, directory.path());
            QVERIFY(!fleet.initialized());
            QVERIFY(!fleet.saveProfiles());
        }
        QFile file(path);
        QVERIFY(file.open(QIODevice::ReadOnly));
        QCOMPARE(file.readAll(), QByteArray("not JSON"));
    }
    void sourceIpAndProfileBounds() {
        DeviceProfile profile;
        QVERIFY(profile.validationError().isEmpty());
        profile.connection.sourceIp = "not-an-ip";
        QVERIFY(!profile.validationError().isEmpty());
        profile.connection.sourceIp = "192.0.2.99";
        QVERIFY(profile.validationError().isEmpty());
        QVERIFY(!profile.connection.validationError().isEmpty()); // Not assigned to this PC.
        profile.connection.sourceIp.clear();
        profile.rateHz = 0;
        QVERIFY(!profile.validationError().isEmpty());
        profile.rateHz = 1;
        profile.connection.sourceIp = "127.0.0.1";
        QVERIFY(profile.connection.validationError().isEmpty());
        auto json = profile.toJson();
        json["port"] = 1883.5;
        QVERIFY(!DeviceProfile::fromJson(json).validationError().isEmpty());
        json = profile.toJson();
        json["tls"] = "false";
        QVERIFY(!DeviceProfile::fromJson(json).validationError().isEmpty());
    }
    void saveFailureDoesNotChangeManagedDevices() {
        QTemporaryDir directory;
        const auto path = directory.filePath("devices.json");
        FleetWindow fleet(path, directory.path());
        QVERIFY(fleet.initialized());
        QVERIFY(QFile::rename(path, path + ".backup"));
        QVERIFY(QDir().mkdir(path));
        DeviceProfile second;
        second.connection.deviceId = "power-meter-002";
        second.equipmentId = "breaker-002";
        QVERIFY(!fleet.addDevice(second));
        QCOMPARE(fleet.deviceCount(), 1);
        auto edited = fleet.device(0)->profile();
        edited.connection.port = 19999;
        QVERIFY(!fleet.updateDevice(0, edited));
        QCOMPARE(fleet.device(0)->profile().connection.port, 18884);
        QVERIFY(!fleet.removeDevice(0));
        QCOMPARE(fleet.deviceCount(), 1);
    }
};
QTEST_MAIN(FleetTest)
#include "test_fleet.moc"
