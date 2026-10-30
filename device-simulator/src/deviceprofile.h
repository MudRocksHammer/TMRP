#pragma once
#include "mqtttransport.h"
#include <QJsonObject>

struct DeviceProfile {
    QString name = "回線 001";
    QString equipmentId = "breaker-001";
    ConnectionOptions connection;
    double rateHz = 1.0;
    int operationDelayMs = 300;
    QJsonObject toJson() const;
    static DeviceProfile fromJson(const QJsonObject &json);
    QString validationError() const;
};
