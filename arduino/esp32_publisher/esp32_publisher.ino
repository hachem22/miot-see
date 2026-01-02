/**
 * ═══════════════════════════════════════════════════════════════
 * ESP32 PUBLISHER - CAPTEUR ULTRASON HC-SR04
 * Détection véhicule et publication MQTT
 * ═══════════════════════════════════════════════════════════════
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ═══════════════════════════════════════════════════════════════
// WIFI ET MQTT
// ═══════════════════════════════════════════════════════════════

const char* WIFI_SSID = "OPPO A17";
const char* WIFI_PASSWORD = "12345678";
const char* MQTT_SERVER = "192.168.131.244";  // ← IP de votre PC
const int MQTT_PORT = 1883;

const char* TOPIC_VEHICLE = "parking/sensor/vehicle";

// ═══════════════════════════════════════════════════════════════
// PINS HARDWARE
// ═══════════════════════════════════════════════════════════════

const int TRIG_PIN = 12;
const int ECHO_PIN = 14;
const int LED_PIN = 2;

// ═══════════════════════════════════════════════════════════════
// PARAMÈTRES DÉTECTION
// ═══════════════════════════════════════════════════════════════

const int DETECTION_DISTANCE = 30;  // Distance détection (cm)
const int MEASURE_INTERVAL = 100;   // Intervalle mesures (ms)
const int DETECTION_COUNT = 5;      // Nombre détections consécutives

WiFiClient espClient;
PubSubClient mqtt(espClient);

unsigned long lastMeasure = 0;
boolean vehiclePresent = false;
int detectionCounter = 0;
int reconnectAttempts = 0;

// ═══════════════════════════════════════════════════════════════
// SETUP WIFI
// ═══════════════════════════════════════════════════════════════

void setup_wifi() {
  delay(10);
  Serial.println("\n╔════════════════════════════════════════╗");
  Serial.println("║  ESP32 PUBLISHER - 8 PLACES (STABLE)   ║");
  Serial.println("╚════════════════════════════════════════╝");
  Serial.print("WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_PIN, LOW);
    Serial.println("\n✓ WiFi OK");
    Serial.print("  IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n✗ WiFi ECHEC");
  }
}

// ═══════════════════════════════════════════════════════════════
// RECONNEXION MQTT
// ═══════════════════════════════════════════════════════════════

void reconnect_mqtt() {
  while (!mqtt.connected()) {
    Serial.print("MQTT... ");
    
    String clientId = "ESP32Publisher-";
    clientId += String(random(0xffff), HEX);
    
    if (mqtt.connect(clientId.c_str())) {
      Serial.println("✓");
      digitalWrite(LED_PIN, HIGH);
      reconnectAttempts = 0;
    } else {
      Serial.print("✗ rc=");
      Serial.println(mqtt.state());
      digitalWrite(LED_PIN, LOW);
      delay(5000);
      
      if (WiFi.status() != WL_CONNECTED) {
        setup_wifi();
      }
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// MESURE DISTANCE
// ═══════════════════════════════════════════════════════════════

float measure_distance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return 0;
  
  float distance = duration * 0.034 / 2;
  return distance;
}

// ═══════════════════════════════════════════════════════════════
// PUBLICATION MQTT
// ═══════════════════════════════════════════════════════════════

void publish_detection(boolean detected, float distance) {
  StaticJsonDocument<256> doc;
  doc["detected"] = detected;
  doc["distance_cm"] = (int)distance;
  doc["timestamp"] = millis();
  doc["sensor_id"] = "ultrason_01";

  char buffer[256];
  serializeJson(doc, buffer);

  if (mqtt.publish(TOPIC_VEHICLE, buffer, true)) {
    Serial.print("📤 MQTT: ");
    Serial.println(buffer);
  }
}

// ═══════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(LED_PIN, OUTPUT);
  
  digitalWrite(TRIG_PIN, LOW);
  digitalWrite(LED_PIN, LOW);

  setup_wifi();
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  randomSeed(micros());
  
  Serial.println("\n✓ Init OK");
  Serial.println("⏳ Detection ultrason...\n");
}

// ═══════════════════════════════════════════════════════════════
// LOOP PRINCIPAL
// ═══════════════════════════════════════════════════════════════

void loop() {
  if (!mqtt.connected()) {
    reconnect_mqtt();
  }
  mqtt.loop();

  unsigned long now = millis();
  if (now - lastMeasure >= MEASURE_INTERVAL) {
    lastMeasure = now;

    float distance = measure_distance();
    
    if (distance > 0 && distance < 400) {
      boolean detected = (distance < DETECTION_DISTANCE);
      
      // FILTRE ANTI-REBOND
      if (detected) {
        detectionCounter++;
        if (detectionCounter >= DETECTION_COUNT) {
          if (!vehiclePresent) {
            vehiclePresent = true;
            
            Serial.println("\n╔════════════════════════════════════╗");
            Serial.println("║   🚗 VÉHICULE CONFIRMÉ !           ║");
            Serial.println("╚════════════════════════════════════╝");
            Serial.print("   Distance: ");
            Serial.print(distance, 1);
            Serial.println(" cm");
            Serial.print("   Détections: ");
            Serial.println(detectionCounter);
            Serial.println();
            
            digitalWrite(LED_PIN, HIGH);
            publish_detection(true, distance);
          }
          detectionCounter = DETECTION_COUNT;
        }
      } else {
        if (detectionCounter > 0) {
          detectionCounter--;
        }
        
        if (detectionCounter == 0 && vehiclePresent) {
          vehiclePresent = false;
          Serial.println("\n✓ Véhicule parti\n");
          digitalWrite(LED_PIN, LOW);
          publish_detection(false, distance);
        }
      }
    }
  }

  delay(10);
}