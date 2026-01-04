/**
 * ═══════════════════════════════════════════════════════════════
 * ESP32 PUBLISHER - RFID + QR CODE
 * Publication MQTT vers broker.hivemq.com
 * ═══════════════════════════════════════════════════════════════
 */

#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ═══════════════════════════════════════════════════════════════
// PINS RFID (VSPI)
// ═══════════════════════════════════════════════════════════════

#define SS_PIN   5
#define RST_PIN  22
#define SCK_PIN  18
#define MOSI_PIN 23
#define MISO_PIN 19

// ═══════════════════════════════════════════════════════════════
// PINS LEDS & BOUTON
// ═══════════════════════════════════════════════════════════════

#define LED_GREEN 27
#define LED_RED 26
#define BUTTON_PIN 4

// ═══════════════════════════════════════════════════════════════
// COMMUNICATION ARDUINO MEGA (UART2)
// ═══════════════════════════════════════════════════════════════

HardwareSerial MegaSerial(2); // RX=16, TX=17

// ═══════════════════════════════════════════════════════════════
// WIFI ET MQTT
// ═══════════════════════════════════════════════════════════════

const char* WIFI_SSID = "A53";
const char* WIFI_PASSWORD = "14364585177147";

const char* MQTT_SERVER = "broker.hivemq.com";
const int MQTT_PORT = 1883;

// Topics avec préfixe unique
const String UNIQUE_ID = "hachem_smartparking_2026";
const String TOPIC_QR = UNIQUE_ID + "/parking/access_code";
const String TOPIC_RFID = UNIQUE_ID + "/parking/rfid_card";
const String TOPIC_RFID_RESPONSE = UNIQUE_ID + "/parking/rfid_response";
const String TOPIC_QR_RESPONSE = UNIQUE_ID + "/parking/qr_response";

// ═══════════════════════════════════════════════════════════════
// OBJETS
// ═══════════════════════════════════════════════════════════════

MFRC522 rfid(SS_PIN, RST_PIN);
WiFiClient espClient;
PubSubClient mqtt(espClient);

// ═══════════════════════════════════════════════════════════════
// VARIABLES
// ═══════════════════════════════════════════════════════════════

volatile bool buttonPressed = false;
volatile unsigned long lastInterruptTime = 0;
const unsigned long debounceDelay = 300;

unsigned long lastRFIDScan = 0;
const unsigned long RFID_DEBOUNCE = 2000;

// ═══════════════════════════════════════════════════════════════
// ISR BOUTON
// ═══════════════════════════════════════════════════════════════

void IRAM_ATTR handleButtonPress() {
  unsigned long interruptTime = millis();
  
  if (interruptTime - lastInterruptTime > debounceDelay) {
    buttonPressed = true;
    lastInterruptTime = interruptTime;
  }
}

// ═══════════════════════════════════════════════════════════════
// SETUP WIFI
// ═══════════════════════════════════════════════════════════════

void setupWiFi() {
  Serial.println("\n╔════════════════════════════════════════╗");
  Serial.println("║  ESP32 RFID/QR PUBLISHER - HIVEMQ      ║");
  Serial.println("╚════════════════════════════════════════╝");
  Serial.print("WiFi: ");
  Serial.println(WIFI_SSID);
  
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    digitalWrite(LED_GREEN, !digitalRead(LED_GREEN));
    attempts++;
  }
  
  if (WiFi.status() == WL_CONNECTED) {
    digitalWrite(LED_GREEN, HIGH);
    Serial.println("\n✓ WiFi OK");
    Serial.print("  IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\n✗ WiFi ECHEC");
    digitalWrite(LED_RED, HIGH);
  }
}

// ═══════════════════════════════════════════════════════════════
// MQTT CALLBACK
// ═══════════════════════════════════════════════════════════════

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  Serial.print("\n📨 [");
  Serial.print(topic);
  Serial.print("]: ");
  
  char message[length + 1];
  memcpy(message, payload, length);
  message[length] = '\0';
  Serial.println(message);
  
  StaticJsonDocument<512> doc;
  DeserializationError error = deserializeJson(doc, message);
  
  if (!error) {
    const char* status = doc["status"];
    bool valid = doc["valid"] | false;
    
    // ════════════════════════════════════════════════════════
    // RÉPONSE RFID
    // ════════════════════════════════════════════════════════
    if (String(topic) == TOPIC_RFID_RESPONSE) {
      if (valid) {
        Serial.println("✅ RFID VALIDE");
        // LED verte clignote 2x
        for(int i=0; i<2; i++) {
          digitalWrite(LED_GREEN, HIGH);
          delay(200);
          digitalWrite(LED_GREEN, LOW);
          delay(200);
        }
        digitalWrite(LED_GREEN, HIGH);
      } else {
        Serial.println("❌ RFID REFUSÉ");
        // LED rouge 1 seconde
        digitalWrite(LED_RED, HIGH);
        delay(1000);
        digitalWrite(LED_RED, LOW);
      }
    }
    
    // ════════════════════════════════════════════════════════
    // RÉPONSE QR CODE
    // ════════════════════════════════════════════════════════
    else if (String(topic) == TOPIC_QR_RESPONSE) {
      
      // ─────────────────────────────────────────────────────
      // CAS 1 : GÉNÉRATION QR (status = "received" ou "rejected")
      // ─────────────────────────────────────────────────────
      if (strcmp(status, "received") == 0) {
        // QR GÉNÉRÉ AVEC SUCCÈS
        const char* code = doc["code"];
        int available = doc["available"] | 0;
        int total = doc["total"] | 8;
        
        Serial.println("✅ QR CODE GÉNÉRÉ");
        Serial.print("   Code: ");
        Serial.println(code);
        Serial.print("   Places: ");
        Serial.print(available);
        Serial.print("/");
        Serial.println(total);
        Serial.println("📱 Scannez et payez pour valider");
        
        // LED verte clignote 3x
        for(int i=0; i<3; i++) {
          digitalWrite(LED_GREEN, HIGH);
          delay(150);
          digitalWrite(LED_GREEN, LOW);
          delay(150);
        }
        digitalWrite(LED_GREEN, HIGH);
      }
      
      else if (strcmp(status, "rejected") == 0) {
        // QR REFUSÉ - PARKING COMPLET
        const char* reason = doc["reason"];
        const char* msg = doc["message"];
        
        Serial.println("\n╔════════════════════════════════════════╗");
        Serial.println("║  🔴 GÉNÉRATION QR REFUSÉE              ║");
        Serial.println("╚════════════════════════════════════════╝");
        Serial.print("   Raison: ");
        Serial.println(reason);
        Serial.print("   Message: ");
        Serial.println(msg);
        Serial.println();
        
        // Envoyer message "PARKING_FULL" à Arduino Mega
        MegaSerial.println("PARKING_FULL");
        
        // LED rouge clignote 5x rapidement
        for(int i=0; i<5; i++) {
          digitalWrite(LED_RED, HIGH);
          delay(100);
          digitalWrite(LED_RED, LOW);
          delay(100);
        }
        
        // LED rouge reste allumée 2 secondes
        digitalWrite(LED_RED, HIGH);
        delay(2000);
        digitalWrite(LED_RED, LOW);
      }
      
      // ─────────────────────────────────────────────────────
      // CAS 2 : SCAN QR POUR ACCÈS (valid = true/false)
      // ─────────────────────────────────────────────────────
      else if (valid) {
        // QR VALIDE (PAYÉ)
        Serial.println("✅ QR VALIDE (PAYÉ)");
        
        // LED verte clignote 2x
        for(int i=0; i<2; i++) {
          digitalWrite(LED_GREEN, HIGH);
          delay(200);
          digitalWrite(LED_GREEN, LOW);
          delay(200);
        }
        digitalWrite(LED_GREEN, HIGH);
      }
      else {
        // QR REFUSÉ (NON PAYÉ, EXPIRÉ, etc.)
        const char* reason = doc["reason"];
        Serial.print("❌ QR REFUSÉ: ");
        Serial.println(reason);
        
        // LED rouge 1 seconde
        digitalWrite(LED_RED, HIGH);
        delay(1000);
        digitalWrite(LED_RED, LOW);
      }
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// RECONNEXION MQTT
// ═══════════════════════════════════════════════════════════════

void reconnectMQTT() {
  while (!mqtt.connected()) {
    Serial.print("MQTT HiveMQ... ");
    
    String clientId = "ESP32RFID-" + UNIQUE_ID;
    
    if (mqtt.connect(clientId.c_str())) {
      Serial.println("✓");
      Serial.println("  Topics:");
      Serial.print("    Pub RFID: ");
      Serial.println(TOPIC_RFID);
      Serial.print("    Pub QR:   ");
      Serial.println(TOPIC_QR);
      
      // S'abonner aux réponses
      mqtt.subscribe(TOPIC_RFID_RESPONSE.c_str());
      mqtt.subscribe(TOPIC_QR_RESPONSE.c_str());
      
      digitalWrite(LED_GREEN, HIGH);
    } else {
      Serial.print("✗ rc=");
      Serial.println(mqtt.state());
      digitalWrite(LED_RED, HIGH);
      delay(5000);
      digitalWrite(LED_RED, LOW);
      
      if (WiFi.status() != WL_CONNECTED) {
        setupWiFi();
      }
    }
  }
}

// ═══════════════════════════════════════════════════════════════
// RÉCUPÉRER UID CARTE
// ═══════════════════════════════════════════════════════════════

String getCardUID() {
  String uid = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    if (rfid.uid.uidByte[i] < 0x10) {
      uid += "0";
    }
    uid += String(rfid.uid.uidByte[i], HEX);
    if (i < rfid.uid.size - 1) {
      uid += ":";
    }
  }
  uid.toUpperCase();
  return uid;
}

// ═══════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  MegaSerial.begin(9600, SERIAL_8N1, 16, 17);
  delay(1000);
  
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_RED, OUTPUT);
  
  digitalWrite(LED_GREEN, LOW);
  digitalWrite(LED_RED, LOW);
  
  // Interrupt bouton
  attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), handleButtonPress, FALLING);
  
  randomSeed(esp_random());
  
  // WiFi
  setupWiFi();
  
  // MQTT
  mqtt.setServer(MQTT_SERVER, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  mqtt.setKeepAlive(60);
  mqtt.setSocketTimeout(30);
  
  // SPI pour RFID
  Serial.println("\nInitialisation SPI...");
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);
  SPI.setFrequency(1000000);
  delay(100);
  
  // MFRC522
  Serial.println("Initialisation MFRC522...");
  rfid.PCD_Init();
  delay(100);
  
  // Vérifier firmware
  byte version = rfid.PCD_ReadRegister(rfid.VersionReg);
  Serial.print("Firmware Version: 0x");
  Serial.print(version, HEX);
  
  if (version == 0x00 || version == 0xFF) {
    Serial.println(" = (FAILED - Vérifiez câblage!)");
    digitalWrite(LED_RED, HIGH);
  } else {
    Serial.println(" = (OK)");
    Serial.println("\n✓ Système prêt!");
    Serial.println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    Serial.println("📇 Tapez carte RFID pour accès");
    Serial.println("🔘 Appuyez bouton pour QR code");
    Serial.println("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n");
  }
}

// ═══════════════════════════════════════════════════════════════
// LOOP
// ═══════════════════════════════════════════════════════════════

void loop() {
  // Maintenir MQTT
  if (!mqtt.connected()) {
    reconnectMQTT();
  }
  mqtt.loop();

  // ============ DÉTECTION CARTE RFID ============
  if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
    unsigned long now = millis();
    
    if (now - lastRFIDScan > RFID_DEBOUNCE) {
      lastRFIDScan = now;
      
      String cardUID = getCardUID();
      
      Serial.println("\n╔════════════════════════════════════════╗");
      Serial.print("║  📇 RFID: ");
      Serial.print(cardUID);
      for(int i = cardUID.length(); i < 24; i++) Serial.print(" ");
      Serial.println("║");
      Serial.println("╚════════════════════════════════════════╝");
      
      // Publier vers serveur Python
      if (mqtt.publish(TOPIC_RFID.c_str(), cardUID.c_str(), true)) {
        Serial.println("✓ Envoyé au serveur MQTT");
        
        // LED feedback
        digitalWrite(LED_GREEN, LOW);
        delay(100);
        digitalWrite(LED_GREEN, HIGH);
      }
      
      Serial.println();
      
      rfid.PICC_HaltA();
      rfid.PCD_StopCrypto1();
    }
  }

  // ============ BOUTON QR CODE ============
  if (buttonPressed) {
    buttonPressed = false;
    
    // Générer code 6 chiffres
    int code = random(100000, 999999);
    String codeStr = String(code);
    
    Serial.println("\n╔════════════════════════════════════════╗");
    Serial.print("║  🔢 QR CODE: ");
    Serial.print(code);
    for(int i = String(code).length(); i < 22; i++) Serial.print(" ");
    Serial.println("║");
    Serial.println("╚════════════════════════════════════════╝");
    
    // Envoyer à Arduino Mega pour affichage QR
    MegaSerial.println(code);
    Serial.println("✓ Envoyé à Arduino Mega (écran QR)");
    
    // Publier vers serveur Python
    if (mqtt.publish(TOPIC_QR.c_str(), codeStr.c_str(), true)) {
      Serial.println("✓ Envoyé au serveur MQTT");
      Serial.println("📱 Scannez le QR et payez pour valider");
      
      // LED feedback
      digitalWrite(LED_GREEN, LOW);
      delay(100);
      digitalWrite(LED_GREEN, HIGH);
      delay(100);
      digitalWrite(LED_GREEN, LOW);
      delay(100);
      digitalWrite(LED_GREEN, HIGH);
    }
    
    Serial.println();
  }

  delay(50);
}