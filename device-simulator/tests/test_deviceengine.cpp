#include "deviceengine.h"
#include "mqtttransport.h"
#include <QJsonDocument>
#include <QSignalSpy>
#include <QTemporaryDir>
#include <QtTest>

class EngineTest : public QObject {
    Q_OBJECT
    QJsonObject command(QString id="cmd-1",QString op="open_breaker") {
        const auto now=QDateTime::currentDateTimeUtc();
        return {{"schema_version","1.0"},{"message_type","command"},{"command_id",id},
            {"device_id","power-meter-001"},{"equipment_id","breaker-001"},{"operation",op},
            {"issued_at",now.toString(Qt::ISODateWithMs)},{"expires_at",now.addSecs(60).toString(Qt::ISODateWithMs)}};
    }
    QByteArray bytes(const QJsonObject &value) { return QJsonDocument(value).toJson(QJsonDocument::Compact); }
private slots:
    void telemetryContract() {
        QTemporaryDir dir; DeviceEngine engine("power-meter-001","breaker-001",dir.filePath("state.sqlite"));
        QVERIFY(engine.initialize());
        auto a=engine.telemetry(),b=engine.telemetry();
        QCOMPARE(a.size(),16); QCOMPARE(a["message_type"].toString(),"power_telemetry");
        QCOMPARE(a["sequence_no"].toInteger(),0); QCOMPARE(b["sequence_no"].toInteger(),1);
        QCOMPARE(a["boot_id"],b["boot_id"]); QVERIFY(a["active_power_kw"].toDouble()>0);
        QVERIFY(engine.updateLocalState({{"closed",false}}));
        auto opened=engine.telemetry(); QCOMPARE(opened["active_power_kw"].toDouble(),0.0);
        QCOMPARE(opened["current_a_a"].toDouble(),0.0); QCOMPARE(opened["voltage_ab_v"].toDouble(),10000.0);
        QVERIFY(engine.updateLocalState({{"quality","partial"}}));
        QVERIFY(engine.telemetry()["current_b_a"].isNull());
        QVERIFY(engine.updateLocalState({{"quality","unavailable"}}));
        auto missing=engine.telemetry(); int nulls=0;
        for(auto it=missing.begin();it!=missing.end();++it) nulls+=it.value().isNull();
        QCOMPARE(nulls,8);
    }
    void completedDuplicateConflictAndRestart() {
        QTemporaryDir dir; auto request=command(); QString boot;
        {
            DeviceEngine engine("power-meter-001","breaker-001",dir.filePath("state.sqlite"));
            QVERIFY(engine.initialize()); boot=engine.bootId(); engine.setOperationDelay(10);
            QSignalSpy results(&engine,&DeviceEngine::commandResult);
            engine.receiveCommand(bytes(request)); QVERIFY(engine.busy());
            QCOMPARE(results.count(),1);
            QTRY_COMPARE_WITH_TIMEOUT(results.count(),2,1000);
            QVERIFY(!engine.state()["closed"].toBool());
            const auto revision=engine.state()["state_version"];
            engine.receiveCommand(bytes(request)); QCOMPARE(results.count(),3);
            QCOMPARE(engine.state()["state_version"],revision);
            auto changed=request; changed["operation"]="close_breaker";
            engine.receiveCommand(bytes(changed));
            QCOMPARE(results.last().at(0).toJsonObject()["reason"].toString(),"command_id_conflict");
            QVERIFY(!engine.state()["closed"].toBool());
        }
        DeviceEngine restored("power-meter-001","breaker-001",dir.filePath("state.sqlite"));
        QVERIFY(restored.initialize()); QVERIFY(restored.bootId()!=boot);
        QVERIFY(!restored.state()["closed"].toBool());
        QSignalSpy results(&restored,&DeviceEngine::commandResult);
        restored.receiveCommand(bytes(request));
        QCOMPARE(results.last().at(0).toJsonObject()["status"].toString(),"completed");
        QCOMPARE(restored.telemetry()["sequence_no"].toInteger(),0);
    }
    void rejections_data() {
        QTest::addColumn<QString>("variant"); QTest::addColumn<QString>("reason");
        QTest::newRow("expired")<<"expired"<<"expired";
        QTest::newRow("target")<<"target"<<"wrong_target";
        QTest::newRow("operation")<<"operation"<<"unsupported_operation";
        QTest::newRow("local-mode")<<"local"<<"local_mode";
        QTest::newRow("interlock")<<"fault"<<"interlock";
        QTest::newRow("stale")<<"stale"<<"stale_state";
        QTest::newRow("timezone")<<"timezone"<<"invalid_time_range";
        QTest::newRow("unknown-field")<<"unknown"<<"invalid_schema";
        QTest::newRow("boolean-version")<<"boolean"<<"invalid_state_version";
    }
    void rejections() {
        QFETCH(QString,variant); QFETCH(QString,reason);
        QTemporaryDir dir; DeviceEngine engine("power-meter-001","breaker-001",dir.filePath("state.sqlite"));
        QVERIFY(engine.initialize()); auto request=command();
        if(variant=="expired") { request["issued_at"]=QDateTime::currentDateTimeUtc().addSecs(-60).toString(Qt::ISODateWithMs); request["expires_at"]=QDateTime::currentDateTimeUtc().addSecs(-1).toString(Qt::ISODateWithMs); }
        if(variant=="target") request["equipment_id"]="breaker-002";
        if(variant=="operation") request["operation"]="toggle";
        if(variant=="local") QVERIFY(engine.updateLocalState({{"remote_enabled",false}}));
        if(variant=="fault") QVERIFY(engine.updateLocalState({{"fault",true}}));
        if(variant=="stale") request["expected_state_version"]=99;
        if(variant=="timezone") request["expires_at"]="2026-10-29T12:00:00";
        if(variant=="unknown") request["unexpected"]=1;
        if(variant=="boolean") request["expected_state_version"]=true;
        QSignalSpy spy(&engine,&DeviceEngine::commandResult);
        engine.receiveCommand(bytes(request));
        QCOMPARE(spy.count(),1); QCOMPARE(spy.at(0).at(0).toJsonObject()["reason"].toString(),reason);
        QVERIFY(!engine.busy()); QVERIFY(engine.state()["closed"].toBool());
    }
    void transportValidation() {
        ConnectionOptions options; QVERIFY(options.validationError().isEmpty());
        options.host="broker.example"; QVERIFY(!options.validationError().isEmpty());
        options.tls=true; QVERIFY(!options.validationError().isEmpty());
        options.deviceId="invalid/#"; QVERIFY(!options.validationError().isEmpty());
    }
    void invalidPayloadsNeverAct() {
        QTemporaryDir dir; DeviceEngine engine("power-meter-001","breaker-001",dir.filePath("state.sqlite"));
        QVERIFY(engine.initialize()); QSignalSpy errors(&engine,&DeviceEngine::problem);
        auto request=bytes(command());
        engine.receiveCommand(request,1,true); engine.receiveCommand(request,0,false);
        engine.receiveCommand("{"); engine.receiveCommand(QByteArray(16385,'x'));
        request.insert(1,"\"operation\":\"close_breaker\","); engine.receiveCommand(request);
        QCOMPARE(errors.count(),5); QVERIFY(engine.state()["closed"].toBool()); QVERIFY(!engine.busy());
    }
    void busyExpiryAndPendingResultAcknowledgment() {
        QTemporaryDir dir; DeviceEngine engine("power-meter-001","breaker-001",dir.filePath("state.sqlite"));
        QVERIFY(engine.initialize()); engine.setOperationDelay(200);
        auto request=command(); request["expires_at"]=QDateTime::currentDateTimeUtc().addMSecs(100).toString(Qt::ISODateWithMs);
        engine.receiveCommand(bytes(request));
        const auto accepted=engine.pendingResults().first();
        QSignalSpy results(&engine,&DeviceEngine::commandResult);
        engine.receiveCommand(bytes(command("cmd-2")));
        QCOMPARE(results.last().at(0).toJsonObject()["reason"].toString(),"busy");
        QTRY_VERIFY_WITH_TIMEOUT(!engine.busy(),1000);
        QVERIFY(engine.state()["closed"].toBool());
        QVERIFY(engine.acknowledgeResult("cmd-1",bytes(accepted)));
        auto pending=engine.pendingResults(); QCOMPARE(pending.size(),2);
        for(const auto &value:pending) QVERIFY(engine.acknowledgeResult(value["command_id"].toString(),bytes(value)));
        QVERIFY(engine.pendingResults().isEmpty());
    }
    void interruptedCommandAndExclusiveStateFile() {
        QTemporaryDir dir;
        {
            DeviceEngine first("power-meter-001","breaker-001",dir.filePath("state.sqlite")); QVERIFY(first.initialize());
            DeviceEngine second("power-meter-001","breaker-001",dir.filePath("state.sqlite")); QVERIFY(!second.initialize());
            first.setOperationDelay(30000); first.receiveCommand(bytes(command())); QVERIFY(first.busy());
        }
        DeviceEngine restarted("power-meter-001","breaker-001",dir.filePath("state.sqlite")); QVERIFY(restarted.initialize());
        QCOMPARE(restarted.pendingResults().first()["reason"].toString(),"device_restarted");
        QVERIFY(restarted.state()["closed"].toBool());
    }
};
QTEST_GUILESS_MAIN(EngineTest)
#include "test_deviceengine.moc"

