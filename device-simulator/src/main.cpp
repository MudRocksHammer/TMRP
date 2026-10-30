#include "fleetwindow.h"
#include "mainwindow.h"
#include <QApplication>
#include <QCommandLineParser>
#include <QDir>
#include <QFontDatabase>
#include <QStandardPaths>
#include <algorithm>

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    app.setOrganizationName("TMRP");
    app.setApplicationName("DeviceSimulator");
    app.setApplicationVersion("0.1.0");
    const auto fontFile = qEnvironmentVariable("TMRP_SIMULATOR_FONT");
    if (!fontFile.isEmpty()) {
        const int font = QFontDatabase::addApplicationFont(fontFile);
        const auto families = QFontDatabase::applicationFontFamilies(font);
        if (!families.isEmpty()) {
            const auto japanese =
                std::find_if(families.begin(), families.end(),
                             [](const QString &name) { return name.endsWith("JP"); });
            app.setFont(QFont(japanese == families.end() ? families.first() : *japanese, 10));
        }
    }
    QCommandLineParser parser;
    parser.setApplicationDescription("TMRP C++/Qt power device simulator");
    parser.addHelpOption();
    parser.addVersionOption();
    parser.addOption({"config", "Connection INI file", "file"});
    parser.addOption({"fleet", "Fleet JSON file (default: state-dir/devices.json)", "file"});
    parser.addOption({"device-id", "Override device ID (power-meter-001..012)", "id"});
    parser.addOption({"state-dir", "SQLite device state directory", "directory"});
    parser.addOption({"auto-connect", "Connect to the configured broker on launch"});
    parser.addOption({"auto-send", "Start telemetry after connecting (requires --auto-connect)"});
    parser.addOption({"headless", "Hide the window for automated integration tests"});
    parser.addOption(
        {"quit-after-ms", "Exit automatically after a positive duration", "milliseconds"});
    parser.addOption({"screenshot", "Save a window screenshot before automatic exit", "file"});
    parser.process(app);
    bool ok = true;
    const int quit = parser.isSet("quit-after-ms") ? parser.value("quit-after-ms").toInt(&ok) : 0;
    if (!ok || (parser.isSet("quit-after-ms") && quit <= 0) ||
        (parser.isSet("auto-send") && !parser.isSet("auto-connect")) ||
        (parser.isSet("fleet") && (parser.isSet("config") || parser.isSet("device-id"))))
        parser.showHelp(2);
    auto directory = parser.value("state-dir");
    if (directory.isEmpty())
        directory = QStandardPaths::writableLocation(QStandardPaths::AppLocalDataLocation);
    if (!parser.isSet("config") && !parser.isSet("device-id")) {
        const auto profiles = parser.isSet("fleet") ? parser.value("fleet")
                                                    : QDir(directory).filePath("devices.json");
        FleetWindow fleet(profiles, directory);
        if (!fleet.initialized()) {
            qCritical().noquote() << fleet.error();
            return 2;
        }
        if (!parser.isSet("headless"))
            fleet.show();
        if (parser.isSet("auto-connect"))
            QTimer::singleShot(0, &fleet, &FleetWindow::connectAll);
        if (parser.isSet("auto-send"))
            QTimer::singleShot(1, &fleet, &FleetWindow::startAll);
        if (quit)
            QTimer::singleShot(quit, &app, [&] {
                if (parser.isSet("screenshot"))
                    fleet.grab().save(parser.value("screenshot"));
                app.quit();
            });
        return app.exec();
    }
    MainWindow window(parser.value("config"), directory);
    if (parser.isSet("device-id"))
        window.setDeviceId(parser.value("device-id"));
    if (!window.engine())
        return 2;
    if (!parser.isSet("headless"))
        window.show();
    if (parser.isSet("auto-connect"))
        QTimer::singleShot(0, &window, &MainWindow::startConnection);
    QTimer autoSend;
    if (parser.isSet("auto-send")) {
        QObject::connect(&autoSend, &QTimer::timeout, &window, [&] {
            if (window.connectionReady()) {
                window.startSending();
                autoSend.stop();
            }
        });
        autoSend.start(50);
    }
    if (quit)
        QTimer::singleShot(quit, &app, [&] {
            if (parser.isSet("screenshot"))
                window.grab().save(parser.value("screenshot"));
            app.quit();
        });
    return app.exec();
}
