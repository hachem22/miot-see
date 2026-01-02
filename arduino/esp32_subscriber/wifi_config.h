#ifndef WIFI_CONFIG_H
#define WIFI_CONFIG_H

const char* WIFI_SSID = "TOPNET_77D0";
const char* WIFI_PASSWORD = "14364585@@";

const char* MQTT_SERVER = "192.168.1.18";
const int MQTT_PORT = 1883;

#define TOPIC_VEHICLE "parking/sensor/vehicle"
#define TOPIC_STATUS "parking/status"
#define TOPIC_BARRIER "parking/barrier/command"

#endif