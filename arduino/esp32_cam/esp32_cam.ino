/**
 * ═══════════════════════════════════════════════════════════════
 * ESP32-CAM - SMART PARKING AUTOMATIQUE
 * Capture images pour analyse Python
 * FLASH LED TOUJOURS ALLUMÉ
 * ═══════════════════════════════════════════════════════════════
 */

#include "esp_camera.h"
#include "esp_http_server.h"
#include <WiFi.h>

// ═══════════════════════════════════════════════════════════════
// CONFIGURATION WIFI
// ═══════════════════════════════════════════════════════════════
const char* WIFI_SSID = "OPPO A17";
const char* WIFI_PASSWORD = "12345678";

// ═══════════════════════════════════════════════════════════════
// PINS CAMERA AI-THINKER
// ═══════════════════════════════════════════════════════════════

#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#define LED_GPIO_NUM       4  // Pin du FLASH LED

httpd_handle_t camera_httpd = NULL;

// ═══════════════════════════════════════════════════════════════
// CONFIGURATION CAMERA
// ═══════════════════════════════════════════════════════════════

void config_camera() {
  camera_config_t config;
  
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  
  if(psramFound()){
    Serial.println("PSRAM OK");
    config.frame_size = FRAMESIZE_SVGA;
    config.jpeg_quality = 12;
    config.fb_count = 1;
  } else {
    Serial.println("Sans PSRAM");
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Erreur: 0x%x\n", err);
    delay(2000);
    ESP.restart();
  }
  
  Serial.println("Camera OK");
}

// ═══════════════════════════════════════════════════════════════
// ALLUMER FLASH LED
// ═══════════════════════════════════════════════════════════════

void allumer_flash() {
  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, HIGH);  // Allumer le flash
  Serial.println("💡 Flash LED ALLUMÉ");
}

void eteindre_flash() {
  digitalWrite(LED_GPIO_NUM, LOW);  // Éteindre le flash
  Serial.println("💡 Flash LED ÉTEINT");
}

// ═══════════════════════════════════════════════════════════════
// HANDLERS HTTP
// ═══════════════════════════════════════════════════════════════

static esp_err_t capture_handler(httpd_req_t *req) {
  camera_fb_t * fb = esp_camera_fb_get();
  if (!fb) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }

  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(req, "Cache-Control", "no-cache");
  
  esp_err_t res = httpd_resp_send(req, (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  
  return res;
}

static esp_err_t index_handler(httpd_req_t *req) {
  const char* html = 
    "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
    "<title>ESP32-CAM</title></head>"
    "<body style='font-family:Arial;text-align:center;padding:20px;background:#1a1a1a;color:white'>"
    "<h1>ESP32-CAM - Parking Auto 💡</h1>"
    "<p style='color:#4ade80;font-weight:bold'>FLASH LED ACTIF</p><hr>"
    "<img id='img' style='width:90%;max-width:800px;border:3px solid #4ade80;border-radius:10px'><br><br>"
    "<button onclick='capture()' style='font-size:18px;padding:12px 25px;background:#4ade80;color:#000;border:none;border-radius:10px;cursor:pointer;font-weight:bold'>Actualiser</button>"
    "<p style='margin-top:20px;opacity:0.7'>Capture auto 2s</p>"
    "<script>"
    "function capture(){document.getElementById('img').src='/capture?'+Date.now();}"
    "setInterval(capture,2000);capture();"
    "</script></body></html>";
  
  httpd_resp_set_type(req, "text/html");
  return httpd_resp_send(req, html, strlen(html));
}

void startCameraServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 81;
  config.ctrl_port = 32768;

  httpd_uri_t index_uri = {.uri = "/", .method = HTTP_GET, .handler = index_handler, .user_ctx = NULL};
  httpd_uri_t capture_uri = {.uri = "/capture", .method = HTTP_GET, .handler = capture_handler, .user_ctx = NULL};

  if (httpd_start(&camera_httpd, &config) == ESP_OK) {
    httpd_register_uri_handler(camera_httpd, &index_uri);
    httpd_register_uri_handler(camera_httpd, &capture_uri);
    Serial.println("Serveur OK :81");
  }
}

// ═══════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  Serial.println("\n================================");
  Serial.println("ESP32-CAM PARKING AUTO");
  Serial.println("FLASH LED TOUJOURS ALLUMÉ");
  Serial.println("================================");

  // Configuration du pin LED AVANT la caméra
  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, LOW);  // Éteint au début

  config_camera();

  Serial.print("WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi OK");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("\nWiFi ECHEC");
    delay(3000);
    ESP.restart();
  }

  startCameraServer();
  
  // ALLUMER LE FLASH MAINTENANT
  delay(1000);  // Attendre que tout soit stabilisé
  allumer_flash();
  
  Serial.println("\n================================");
  Serial.println("PRET");
  Serial.println("================================");
  Serial.print("URL: http://");
  Serial.print(WiFi.localIP());
  Serial.println(":81/");
  Serial.println("================================\n");
}

void loop() {
  delay(10000);
  
  // Vérifier WiFi
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi perdu");
    delay(1000);
    ESP.restart();
  }
  
  // S'assurer que le flash reste allumé
  if (digitalRead(LED_GPIO_NUM) == LOW) {
    digitalWrite(LED_GPIO_NUM, HIGH);
    Serial.println("💡 Flash rallumé");
  }
  
  Serial.print(".");
}