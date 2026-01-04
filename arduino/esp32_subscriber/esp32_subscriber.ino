/**
 * ═══════════════════════════════════════════════════════════════
 * ESP32 SUBSCRIBER - LCD + SERVO + LEDS
 * Contrôle barrière via MQTT HiveMQ
 * ═══════════════════════════════════════════════════════════════
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <LiquidCrystal_I2C.h>
#include <ESP32Servo.h>

// ═══════════════════════════════════════════════════════════════
// WIFI ET MQTT
// ═══════════════════════════════════════════════════════════════

const char* WIFI_SSID = "A53";
const char* WIFI_PASSWORD = "14364585177147";

const char* MQTT_SERVER = "broker.hivemq.com";
const int MQTT_PORT = 1883;

// Topics avec préfixe unique
const String UNIQUE_ID = "hachem_smartparking_2026";
const String TOPIC_STATUS = UNIQUE_ID + "/parking/status";
const String TOPIC_BARRIER = UNIQUE_ID + "/parking/barrier/command";

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

// ═══════════════════════════════════════════════════════════════
// OBJETS
// ═══════════════════════════════════════════════════════════════

WiFiClient espClient;
PubSubClient mqtt(espClient);
LiquidCrystal_I2C lcd(LCD_ADDRESS, LCD_COLS, LCD_ROWS);
Servo barriere;

// ═══════════════════════════════════════════════════════════════
// VARIABLES
// ═══════════════════════════════════════════════════════════════

int placesDisponibles = 0;
int placesTotal = 8;
boolean barriereOuverte = false;

// ═══════════════════════════════════════════════════════════════
// SETUP WIFI
// ═══════════════════════════════════════════════════════════════

void setup_wifi() {
  Serial.println("\n╔════════════════════════════════════════╗");
  Serial.println("║  ESP32 SUBSCRIBER - HIVEMQ             ║");
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
    delay(1500);
  } else {
    Serial.println("\n✗ WiFi ECHEC");
    lcd.clear();
    lcd.print("WiFi ECHEC");
    digitalWrite(LED_RED, HIGH);
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

  // ============ STATUS PARKING ============
  if (String(topic) == TOPIC_STATUS) {
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
  
  // ============ COMMANDE BARRIÈRE ============
  else if (String(topic) == TOPIC_BARRIER) {
    const char* action = doc["action"];
    const char* method = doc["method"] | "AUTO";
    const char* user = doc["user"] | "Utilisateur";
    const char* reason = doc["reason"] | "";
    const char* message_text = doc["message"] | "BARRIERE";
    
    Serial.print("   Action: ");
    Serial.println(action);
    Serial.print("   Méthode: ");
    Serial.println(method);
    Serial.print("   Utilisateur: ");
    Serial.println(user);
    
    if (strcmp(action, "open") == 0) {
      Serial.println("   🟢 OUVERTURE BARRIÈRE");
      ouvrirBarriere(method, user);
      
    } else if (strcmp(action, "stay_closed") == 0) {
      Serial.print("   🔴 ACCÈS REFUSÉ: ");
      Serial.println(reason);
      
      afficherRefus(reason);
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// RECONNEXION MQTT
// ═══════════════════════════════════════════════════════════════

void reconnect_mqtt() {
  while (!mqtt.connected()) {
    Serial.print("MQTT HiveMQ... ");
    lcd.clear();
    lcd.print("MQTT...");
    
    String clientId = "ESP32Sub-" + UNIQUE_ID;
    
    if (mqtt.connect(clientId.c_str())) {
      Serial.println("✓");
      
      // S'abonner
      mqtt.subscribe(TOPIC_STATUS.c_str());
      mqtt.subscribe(TOPIC_BARRIER.c_str());
      
      Serial.println("  Abonné à:");
      Serial.print("    - ");
      Serial.println(TOPIC_STATUS);
      Serial.print("    - ");
      Serial.println(TOPIC_BARRIER);
      
      lcd.clear();
      lcd.print("MQTT OK");
      delay(1000);
      
      digitalWrite(LED_GREEN, HIGH);
    } else {
      Serial.print("✗ rc=");
      Serial.println(mqtt.state());
      digitalWrite(LED_RED, HIGH);
      delay(5000);
      digitalWrite(LED_RED, LOW);
      
      if (WiFi.status() != WL_CONNECTED) {
        setup_wifi();
      }
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// AFFICHAGE LCD
// ═══════════════════════════════════════════════════════════════

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
  } 
  else {
    // ════════════════════════════════════════════════════════
    // PARKING COMPLET - AFFICHAGE CLAIR
    // ════════════════════════════════════════════════════════
    lcd.setCursor(0, 0);
    lcd.print("*** COMPLET ***");
    lcd.setCursor(0, 1);
    lcd.print("0/");
    lcd.print(placesTotal);
    lcd.print(" places");
    
    // Faire clignoter LED rouge
    digitalWrite(LED_RED, HIGH);
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

// ═══════════════════════════════════════════════════════════════
// CONTRÔLE BARRIÈRE
// ═══════════════════════════════════════════════════════════════

void ouvrirBarriere(const char* method, const char* user) {
  Serial.println("\n╔════════════════════════════════════╗");
  Serial.println("║   🟢 OUVERTURE BARRIÈRE            ║");
  Serial.println("╚════════════════════════════════════╝");
  Serial.print("   Méthode: ");
  Serial.println(method);
  Serial.print("   Utilisateur: ");
  Serial.println(user);
  
  // LEDs
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_YELLOW, HIGH);
  digitalWrite(LED_RED, LOW);
  
  // LCD - Ligne 1
  lcd.clear();
  lcd.setCursor(0, 0);
  if (strcmp(method, "RFID") == 0) {
    lcd.print("RFID OK");
  } else if (strcmp(method, "QR") == 0) {
    lcd.print("QR OK - PAYE");
  } else {
    lcd.print("BIENVENUE");
  }
  
  // LCD - Ligne 2
  lcd.setCursor(0, 1);
  String userName = String(user);
  if (userName.length() > 16) {
    userName = userName.substring(0, 16);
  }
  lcd.print(userName);
  
  // Servo ouverture
  Serial.println("   Servo: 0° → 90°");
  for (int pos = 0; pos <= 90; pos += 3) {
    barriere.write(pos);
    delay(20);
  }
  
  barriereOuverte = true;
  Serial.println("✓ Barrière ouverte");
  Serial.println("⏳ Attente 5s...");
  
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
  
  // Servo fermeture
  Serial.println("   Servo: 90° → 0°");
  for (int pos = 90; pos >= 0; pos -= 3) {
    barriere.write(pos);
    delay(20);
  }
  
  barriereOuverte = false;
  Serial.println("✓ Barrière fermée\n");
  
  digitalWrite(LED_YELLOW, LOW);
  delay(1000);
  updateDisplay();
  updateLEDs();
}

void afficherRefus(const char* raison) {
  lcd.clear();
  lcd.setCursor(0, 0);
  
  if (strcmp(raison, "PARKING COMPLET") == 0) {
    lcd.print("PARKING COMPLET");
    lcd.setCursor(0, 1);
    lcd.print("0/");
    lcd.print(placesTotal);
    lcd.print(" places");
  } else if (strcmp(raison, "PAIEMENT REQUIS") == 0) {
    lcd.print("ACCES REFUSE");
    lcd.setCursor(0, 1);
    lcd.print("PAIEMENT REQUIS");
  } else {
    lcd.print("ACCES REFUSE");
    lcd.setCursor(0, 1);
    lcd.print(raison);
  }
  
  // LED rouge clignote
  for(int i=0; i<3; i++) {
    digitalWrite(LED_RED, HIGH);
    delay(200);
    digitalWrite(LED_RED, LOW);
    delay(200);
  }
  digitalWrite(LED_RED, HIGH);
  
  delay(3000);
  updateDisplay();
  updateLEDs();
}

// ═══════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_YELLOW, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_YELLOW, LOW);
  digitalWrite(LED_RED, HIGH);

  // Servo
  barriere.attach(SERVO_PIN);
  barriere.write(0);
  Serial.println("✓ Servo initialisé");

  // LCD
  lcd.init();
  lcd.backlight();
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("SMART PARKING");
  lcd.setCursor(0, 1);
  lcd.print("RFID + QR + CAM");
  Serial.println("✓ LCD initialisé");
  delay(2000);

  setup_wifi();
  
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  mqtt.setCallback(mqtt_callback);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(60);
  mqtt.setSocketTimeout(30);
  
  randomSeed(micros());
  
  Serial.println("\n✓ Init OK\n");
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("EN ATTENTE...");
  lcd.setCursor(0, 1);
  lcd.print("MQTT...");
}

// ═══════════════════════════════════════════════════════════════
// LOOP
// ═══════════════════════════════════════════════════════════════

void loop() {
  if (!mqtt.connected()) {
    reconnect_mqtt();
  }
  mqtt.loop();
  delay(10);
}