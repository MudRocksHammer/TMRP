#include "deviceengine.h"

#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QRegularExpression>
#include <QSet>
#include <QSqlQuery>
#include <QUuid>
#include <cmath>

namespace {
QByteArray compact(const QJsonObject &object) {
    return QJsonDocument(object).toJson(QJsonDocument::Compact);
}
QDateTime timestamp(const QJsonValue &value) {
    const QString text = value.toString();
    if (!QRegularExpression("(Z|[+-]\\d{2}:\\d{2})$").match(text).hasMatch())
        return {};
    return QDateTime::fromString(text, Qt::ISODateWithMs).toUTC();
}
// Commands are flat JSON objects. Detect duplicate keys before Qt's parser
// collapses them; quoted/escaped characters are handled as JSON strings.
bool uniqueKeys(const QByteArray &raw) {
    QSet<QString> keys;
    for (qsizetype i = 0; i < raw.size(); ++i) {
        if (raw[i] != '"') continue;
        const auto begin = i++;
        for (; i < raw.size(); ++i) {
            if (raw[i] == '\\') { ++i; continue; }
            if (raw[i] == '"') break;
        }
        auto after = i + 1;
        while (after < raw.size() && QByteArray(" \t\r\n").contains(raw[after])) ++after;
        if (after < raw.size() && raw[after] == ':') {
            const auto key = QJsonDocument::fromJson("[" + raw.mid(begin, i-begin+1) + "]")
                                 .array().at(0).toString();
            if (keys.contains(key)) return false;
            keys.insert(key);
        }
    }
    return true;
}
}

DeviceEngine::DeviceEngine(QString deviceId, QString equipmentId, QString databasePath,
                           QObject *parent)
    : QObject(parent), m_device(std::move(deviceId)), m_equipment(std::move(equipmentId)),
      m_path(std::move(databasePath)), m_boot(QUuid::createUuid().toString(QUuid::WithoutBraces)) {
    m_operation.setSingleShot(true);
    connect(&m_operation, &QTimer::timeout, this, &DeviceEngine::finishCommand);
}

DeviceEngine::~DeviceEngine() {
    m_operation.stop();
    if (m_db.isValid()) {
        const auto name = m_db.connectionName();
        m_db.close();
        m_db = QSqlDatabase();
        QSqlDatabase::removeDatabase(name);
    }
}

bool DeviceEngine::validId(const QString &value) {
    return QRegularExpression("^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$").match(value).hasMatch();
}

void DeviceEngine::fail(const QString &message) {
    m_error = message;
    emit problem(message);
}

bool DeviceEngine::executeSql(const QString &statement) {
    QSqlQuery query(m_db);
    if (query.exec(statement)) return true;
    fail("ローカルDBの操作に失敗しました。保存先と空き容量を確認してください。");
    return false;
}

bool DeviceEngine::initialize() {
    if (!validId(m_device) || !validId(m_equipment)) {
        fail("機器ID・設備IDには英数字、ハイフン、ピリオド、下線を使用してください（128文字以内）。");
        return false;
    }
    if (!QDir().mkpath(QFileInfo(m_path).absolutePath())) {
        fail("状態保存フォルダーを作成できません。"); return false;
    }
    m_lock = std::make_unique<QLockFile>(m_path + ".lock");
    if (!m_lock->tryLock(0)) {
        fail("この機器の状態ファイルは別のアプリが使用中です。"); return false;
    }
    m_db = QSqlDatabase::addDatabase("QSQLITE", QUuid::createUuid().toString());
    m_db.setDatabaseName(m_path);
    if (!m_db.open()) { fail("SQLiteを開けません。"); return false; }
    if (!executeSql("PRAGMA synchronous=FULL") ||
        !executeSql("PRAGMA busy_timeout=1000") ||
        !executeSql("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), data BLOB NOT NULL)") ||
        !executeSql("CREATE TABLE IF NOT EXISTS commands (id TEXT PRIMARY KEY, request BLOB NOT NULL, result BLOB NOT NULL, pending INTEGER NOT NULL)"))
        return false;
    QSqlQuery query(m_db);
    if (!query.exec("SELECT data FROM state WHERE id=1")) return false;
    if (query.next()) {
        m_state = QJsonDocument::fromJson(query.value(0).toByteArray()).object();
        if (m_state["device_id"].toString() != m_device ||
            m_state["equipment_id"].toString() != m_equipment) {
            fail("状態ファイルの機器IDが設定と一致しません。"); return false;
        }
    } else {
        m_state = {{"device_id", m_device}, {"equipment_id", m_equipment},
                   {"closed", true}, {"remote_enabled", true}, {"fault", false},
                   {"state_version", 0}, {"voltage", 10000.0}, {"current", 100.0},
                   {"power_factor", 0.9}, {"frequency", 50.0}, {"quality", "good"}};
        if (!persistState(m_state)) return false;
    }
    // Accepted operations never change state until their atomic final commit.
    // After a process restart they are failed explicitly instead of replayed.
    if (!query.exec("SELECT id, request, result FROM commands")) return false;
    QList<QPair<QString,QByteArray>> interrupted;
    while (query.next()) {
        if (QJsonDocument::fromJson(query.value(2).toByteArray()).object()["status"] == "accepted")
            interrupted.append({query.value(0).toString(), query.value(1).toByteArray()});
    }
    query.finish();
    for (const auto &entry : interrupted)
        if (!storeResult(entry.first, entry.second, result(entry.first, "failed", "device_restarted")))
            return false;
    return true;
}

bool DeviceEngine::persistState(const QJsonObject &state) {
    QSqlQuery query(m_db);
    query.prepare("INSERT INTO state VALUES(1,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data");
    query.addBindValue(compact(state));
    if (query.exec()) return true;
    fail("設備状態の保存に失敗しました。操作は反映していません。"); return false;
}

void DeviceEngine::setOperationDelay(int milliseconds) { m_delay = qBound(0, milliseconds, 30000); }

bool DeviceEngine::updateLocalState(const QJsonObject &changes) {
    if (busy()) { fail("指令を実行中です。完了後に変更してください。"); return false; }
    QJsonObject candidate = m_state;
    const QSet<QString> allowed = {"closed", "remote_enabled", "fault", "voltage", "current", "power_factor", "frequency", "quality"};
    for (auto it = changes.begin(); it != changes.end(); ++it) {
        if (!allowed.contains(it.key())) return false;
        if (it.key() == "closed" || it.key() == "remote_enabled" || it.key() == "fault") {
            if (!it.value().isBool()) return false;
        } else if (it.key() == "quality") {
            if (!QStringList({"good","partial","unavailable"}).contains(it.value().toString())) return false;
        } else {
            const double number = it.value().toDouble(-1);
            if (!it.value().isDouble() || !std::isfinite(number) || number < 0 ||
                (it.key() == "power_factor" && number > 1) || number > 1000000)
                return false;
        }
        candidate[it.key()] = it.value();
    }
    if (candidate == m_state) return true;
    candidate["state_version"] = m_state["state_version"].toInteger() + 1;
    if (!persistState(candidate)) return false;
    m_state = candidate;
    emit stateChanged();
    return true;
}

QJsonObject DeviceEngine::telemetry() {
    const bool closed = m_state["closed"].toBool();
    const double voltage = m_state["voltage"].toDouble();
    const double current = closed ? m_state["current"].toDouble() : 0;
    QJsonObject data = {{"schema_version", "1.0"}, {"message_type", "power_telemetry"},
        {"device_id", m_device}, {"boot_id", m_boot}, {"sequence_no", m_sequence++},
        {"event_time", QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs)},
        {"breaker_state", closed ? "closed" : "open"}, {"quality", m_state["quality"]},
        {"voltage_ab_v", voltage}, {"voltage_bc_v", voltage}, {"voltage_ca_v", voltage},
        {"current_a_a", current}, {"current_b_a", current}, {"current_c_a", current},
        {"active_power_kw", std::sqrt(3.0)*voltage*current*m_state["power_factor"].toDouble()/1000},
        {"frequency_hz", m_state["frequency"]}};
    if (m_state["quality"] == "partial") data["current_b_a"] = QJsonValue::Null;
    if (m_state["quality"] == "unavailable")
        for (const auto &field : {"voltage_ab_v","voltage_bc_v","voltage_ca_v","current_a_a",
                                 "current_b_a","current_c_a","active_power_kw","frequency_hz"})
            data[field] = QJsonValue::Null;
    return data;
}

QJsonObject DeviceEngine::result(const QString &id, const QString &status, const QString &reason) const {
    return {{"schema_version", "1.0"}, {"message_type", "command_result"},
        {"device_id", m_device}, {"equipment_id", m_equipment}, {"command_id", id},
        {"status", status}, {"reason", reason}, {"state_version", m_state["state_version"]},
        {"breaker_state", m_state["closed"].toBool() ? "closed" : "open"},
        {"event_time", QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs)}};
}

bool DeviceEngine::storeResult(const QString &id, const QByteArray &request, const QJsonObject &value) {
    QSqlQuery query(m_db);
    query.prepare("INSERT INTO commands VALUES(?,?,?,1) ON CONFLICT(id) DO UPDATE SET result=excluded.result,pending=1");
    query.addBindValue(id); query.addBindValue(request); query.addBindValue(compact(value));
    if (query.exec()) return true;
    fail("指令結果を保存できません。操作は実行しません。"); return false;
}

void DeviceEngine::receiveCommand(const QByteArray &payload, int qos, bool retained) {
    if (payload.size() > 16384 || qos != 1 || retained) {
        fail("指令を拒否しました（サイズ上限、QoS、retainを確認してください）。"); return;
    }
    QJsonParseError parseError;
    const auto document = QJsonDocument::fromJson(payload, &parseError);
    if (parseError.error != QJsonParseError::NoError || !document.isObject() || !uniqueKeys(payload)) {
        fail("指令は重複キーのないJSONオブジェクトで送信してください。"); return;
    }
    const auto command = document.object();
    const auto id = command["command_id"].toString();
    if (!validId(id)) { fail("指令IDが不正です。"); return; }
    const auto request = compact(command);
    QSqlQuery query(m_db);
    query.prepare("SELECT request,result FROM commands WHERE id=?"); query.addBindValue(id);
    if (!query.exec()) { fail("指令履歴を読み込めません。"); return; }
    if (query.next()) {
        if (query.value(0).toByteArray() != request) {
            emit commandResult(result(id,"rejected","command_id_conflict"));
        } else {
            auto saved = QJsonDocument::fromJson(query.value(1).toByteArray()).object();
            query.finish();
            if (storeResult(id,request,saved)) emit commandResult(saved);
        }
        return;
    }
    query.finish();
    if (!query.exec("SELECT count(*) FROM commands") || !query.next() || query.value(0).toInt() >= 10000) {
        fail("指令履歴の上限（10,000件）に達したか、DBを読み込めません。"); return;
    }
    const QSet<QString> required = {"schema_version","message_type","command_id","device_id",
        "equipment_id","operation","issued_at","expires_at"};
    QSet<QString> actual;
    for (auto it=command.begin(); it!=command.end(); ++it) actual.insert(it.key());
    auto allowed = required; allowed.insert("expected_state_version");
    QString reason;
    const auto issued = timestamp(command["issued_at"]), expires = timestamp(command["expires_at"]);
    const auto now = QDateTime::currentDateTimeUtc();
    if (!(required-actual).isEmpty() || !(actual-allowed).isEmpty() ||
        command["schema_version"] != "1.0" || command["message_type"] != "command") reason="invalid_schema";
    else if (command["device_id"] != m_device || command["equipment_id"] != m_equipment) reason="wrong_target";
    else if (command["operation"] != "open_breaker" && command["operation"] != "close_breaker") reason="unsupported_operation";
    else if (!issued.isValid() || !expires.isValid() || issued >= expires ||
             issued.secsTo(expires)>300 || issued>now.addSecs(30)) reason="invalid_time_range";
    else if (expires <= now) reason="expired";
    else if (command.contains("expected_state_version") &&
             (!command["expected_state_version"].isDouble() ||
              command["expected_state_version"].toDouble() < 0 ||
              command["expected_state_version"].toDouble() > 9007199254740991.0 ||
              std::floor(command["expected_state_version"].toDouble()) != command["expected_state_version"].toDouble())) reason="invalid_state_version";
    else if (command.contains("expected_state_version") && command["expected_state_version"] != m_state["state_version"]) reason="stale_state";
    else if (!m_state["remote_enabled"].toBool()) reason="local_mode";
    else if (m_state["fault"].toBool()) reason="interlock";
    else if (busy()) reason="busy";
    const auto value=result(id,reason.isEmpty()?"accepted":"rejected",reason);
    if (!storeResult(id,request,value)) return;
    emit commandResult(value);
    if (!reason.isEmpty()) return;
    m_active=command; m_activeRequest=request;
    emit busyChanged(true);
    m_operation.start(m_delay);
}

void DeviceEngine::finishCommand() {
    const auto id=m_active["command_id"].toString();
    auto old=m_state;
    QString reason;
    if (timestamp(m_active["expires_at"]) <= QDateTime::currentDateTimeUtc()) reason="expired";
    else if (!m_state["remote_enabled"].toBool() || m_state["fault"].toBool()) reason="interlock";
    const bool desired=m_active["operation"]=="close_breaker";
    if (reason.isEmpty() && m_state["closed"].toBool()!=desired) {
        m_state["closed"]=desired;
        m_state["state_version"]=m_state["state_version"].toInteger()+1;
    }
    const auto value=result(id,reason.isEmpty()?"completed":"failed",reason);
    const bool begun=m_db.transaction();
    const bool ok=begun && persistState(m_state) && storeResult(id,m_activeRequest,value) && m_db.commit();
    if (!ok) {
        if (begun) m_db.rollback();
        m_state=old;
        fail("指令の確定に失敗しました。設備状態は変更していません。再起動して履歴を確認してください。");
    }
    m_active={}; m_activeRequest.clear();
    emit busyChanged(false);
    if (ok) { emit commandResult(value); emit stateChanged(); }
}

QList<QJsonObject> DeviceEngine::pendingResults() const {
    QList<QJsonObject> values;
    QSqlQuery query(m_db);
    if (query.exec("SELECT result FROM commands WHERE pending=1 ORDER BY rowid LIMIT 50"))
        while(query.next()) values.append(QJsonDocument::fromJson(query.value(0).toByteArray()).object());
    return values;
}

bool DeviceEngine::acknowledgeResult(const QString &id, const QByteArray &payload) {
    QSqlQuery query(m_db);
    query.prepare("UPDATE commands SET pending=0 WHERE id=? AND result=?");
    query.addBindValue(id); query.addBindValue(payload);
    return query.exec();
}
