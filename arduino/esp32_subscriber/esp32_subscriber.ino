/**
 * ═══════════════════════════════════════════════════════════════
 * ESP32 SUBSCRIBER - LCD + SERVO + LEDS
 * Affichage automatique + Barrière
 * ═══════════════════════════════════════════════════════════════
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <LiquidCrystal_I2C.h>
#include <ESP32Servo.h>

// ═══════════════════════════════════════════════════════════════
// WIFI
// ═══════════════════════════════════════════════════════════════

const char* WIFI_SSID = "OPPO A17";
const char* WIFI_PASSWORD = "12345678";
const char* MQTT_SERVER = "192.168.131.244";  // ← IP de votre PC
const int MQTT_PORT = 1883;

const char* TOPIC_STATUS = "parking/status";
const char* TOPIC_BARRIER = "parking/barrier/command";

// ═══════════════════════════════════════════════════════════════
// PINS
// ═══════════════════════════════════════════════════════════════

const int SERVO_PIN = 18;
const int LED_GREEN = 25;
const int LED_YELLOW = 26;
const int LED_RED = 27;

const int LCD_ADDRESS = 0x27;
const int LCD_COLS = 16;
const int LCD_ROWS = 2;

WiFiClient espClient;
PubSubClient mqtt(espClient);
LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLS, LCD_ROWS);
Servo barriere;

int placesDisponibles = 0;
int placesTotal = 8;
boolean barrierOuverte = false;

// ═══════════════════════════════════════════════════════════════
// WIFI
// ═══════════════════════════════════════════════════════════════

void setup_wifi() {
  Serial.println("\n╔════════════════════════════════════════╗");
  Serial.println("║  ESP32 SUBSCRIBER AUTO - 8 PLACES      ║");
  Serial.println("╚════════════════════════════════════════╝");
  Serial.print("WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  lcd.setCursor(0, 0);
  lcd.print("WiFi...");

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    digitalWrite(LED_YELLOW, !digitalRead(LED_YELLOW));
    attempts++;
  }

  digitalWrite(LED_YELLOW, LOW);
  
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✓ WiFi OK");
    Serial.print("  IP: ");
    Serial.println(WiFi.localIP());

    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("WiFi OK");
    lcd.setCursor(0, 1);
    lcd.print(WiFi.localIP());
    delay(2000);
  } else {
    Serial.println("\n✗ WiFi ECHEC");
    lcd.clear();
    lcd.print("WiFi ECHEC");
  }
}

// ═══════════════════════════════════════════════════════════════
// MQTT CALLBACK
// ═══════════════════════════════════════════════════════════════

void mqtt_callback(char* topic, byte* payload, unsigned int length) {
  Serial.print("\n📨 [");
  Serial.print(topic);
  Serial.println("]");

  char message[length + 1];
  memcpy(message, payload, length);
  message[length] = '\0';

  StaticJsonDocument<512> doc;
  DeserializationError error = deserializeJson(doc, message);
  
  if (error) {
    Serial.print("✗ JSON: ");
    Serial.println(error.c_str());
    return;
  }

  if (strcmp(topic, TOPIC_STATUS) == 0) {
    int available = doc["available"] | 0;
    int total = doc["total"] | 8;
    
    placesDisponibles = available;
    placesTotal = total;
    
    Serial.print("   Libres: ");
    Serial.print(available);
    Serial.print("/");
    Serial.println(total);
    
    updateDisplay();
    updateLEDs();
  }
  
  else if (strcmp(topic, TOPIC_BARRIER) == 0) {
    const char* action = doc["action"];
    const char* message_text = doc["message"] | "BARRIERE";
    
    Serial.print("   Barrière: ");
    Serial.println(action);
    
    if (strcmp(action, "open") == 0) {
      Serial.println("   🟢 OUVERTURE AUTO");
      ouvrirBarriere(message_text);
      
    } else if (strcmp(action, "stay_closed") == 0) {
      Serial.println("   🔴 RESTE FERMÉE");
      
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("PARKING COMPLET");
      lcd.setCursor(0, 1);
      lcd.print("0/");
      lcd.print(placesTotal);
      
      for(int i=0; i<3; i++) {
        digitalWrite(LED_RED, HIGH);
        delay(200);
        digitalWrite(LED_RED, LOW);
        delay(200);
      }
      digitalWrite(LED_RED, HIGH);
      
      delay(2000);
      updateDisplay();
    }
  }
}

void reconnect_mqtt() {
  while (!mqtt.connected()) {
    Serial.print("MQTT... ");
    lcd.clear();
    lcd.print("MQTT...");
    
    String clientId = "ESP32Sub-";
    clientId += String(random(0xffff), HEX);
    
    if (mqtt.connect(clientId.c_str())) {
      Serial.println("✓");
      mqtt.subscribe(TOPIC_STATUS);
      mqtt.subscribe(TOPIC_BARRIER);
      lcd.clear();
      lcd.print("MQTT OK");
      delay(1000);
    } else {
      Serial.print("✗ rc=");
      Serial.println(mqtt.state());
      delay(5000);
      if (WiFi.status() != WL_CONNECTED) {
        setup_wifi();
      }
    }
  }
}

void updateDisplay() {
  lcd.clear();
  if (placesDisponibles > 0) {
    lcd.setCursor(0, 0);
    lcd.print("PARKING 8 PL");
    lcd.setCursor(0, 1);
    lcd.print("Libres: ");
    lcd.print(placesDisponibles);
    lcd.print("/");
    lcd.print(placesTotal);
  } else {
    lcd.setCursor(0, 0);
    lcd.print("PARKING COMPLET");
    lcd.setCursor(0, 1);
    lcd.print("0/");
    lcd.print(placesTotal);
  }
}

void updateLEDs() {
  if (placesDisponibles > 0) {
    digitalWrite(LED_GREEN, HIGH);
    digitalWrite(LED_YELLOW, LOW);
    digitalWrite(LED_RED, LOW);
  } else {
    digitalWrite(LED_GREEN, LOW);
    digitalWrite(LED_YELLOW, LOW);
    digitalWrite(LED_RED, HIGH);
  }
}

void ouvrirBarriere(const char* message_text) {
  Serial.println("\n╔════════════════════════════════════╗");
  Serial.println("║   🟢 OUVERTURE BARRIÈRE            ║");
  Serial.println("╚════════════════════════════════════╝");
  
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_YELLOW, HIGH);
  digitalWrite(LED_RED, LOW);
  
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("BARRIERE");
  lcd.setCursor(0, 1);
  lcd.print("OUVERTE !");
  
  Serial.println("   Servo: 0° → 90°");
  for (int pos = 0; pos <= 90; pos += 3) {
    barriere.write(pos);
    delay(20);
  }
  
  barrierOuverte = true;
  Serial.println("✓ Ouverte");
  Serial.println("⏳ 5s...");
  
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("BIENVENUE !");
  lcd.setCursor(0, 1);
  lcd.print(placesDisponibles);
  lcd.print(" place");
  if (placesDisponibles > 1) lcd.print("s");
  
  delay(5000);
  fermerBarriere();
}

void fermerBarriere() {
  Serial.println("\n╔════════════════════════════════════╗");
  Serial.println("║   🔴 FERMETURE BARRIÈRE            ║");
  Serial.println("╚════════════════════════════════════╝");
  
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("FERMETURE...");
  
  Serial.println("   Servo: 90° → 0°");
  for (int pos = 90; pos >= 0; pos -= 3) {
    barriere.write(pos);
    delay(20);
  }
  
  barrierOuverte = false;
  Serial.println("✓ Fermée\n");
  
  digitalWrite(LED_YELLOW, LOW);
  delay(1000);
  updateDisplay();
  updateLEDs();
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_YELLOW, LOW);
  digitalWrite(LED_RED, HIGH);

  barriere.attach(SERVO_PIN);
  barriere.write(0);
  Serial.println("✓ Servo");

  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("SMART PARKING");
  lcd.setCursor(0, 1);
  lcd.print("AUTO 8 Places");
  Serial.println("✓ LCD");
  delay(2000);

  setup_wifi();
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  mqtt.setCallback(mqtt_callback);
  mqtt.setBufferSize(512);
  randomSeed(micros());
  
  Serial.println("\n✓ Init OK\n");
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("EN ATTENTE...");
  lcd.setCursor(0, 1);
  lcd.print("MQTT");
}

void loop() {
  if (!mqtt.connected()) {
    reconnect_mqtt();
  }
  mqtt.loop();
  delay(10);
}