/* CrossSafe Vision integrated ESP32-CAM + external LED controller.
   Camera webpage/stream use CameraWebServer ports 80/81; light API uses 82.
   GPIO13 is used for the LED signal; do not use the SD card simultaneously.
   Use a resistor for one small LED, or a suitable driver/supply for multiple LEDs.
   Never connect mains voltage to the ESP32. */
#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WebServer.h>
#include "board_config.h"

const char *ssid = "YOUR_WIFI_NAME";
const char *password = "YOUR_WIFI_PASSWORD";
constexpr int LED_PIN = 13;
WebServer controlServer(82);
bool ledOn = false;
void startCameraServer();
void setupLedFlash();

void setLight(bool on) { ledOn = on; digitalWrite(LED_PIN, on ? HIGH : LOW); }
void handleLight() {
  String state = controlServer.arg("state"); state.toLowerCase();
  if (state == "on") {
    setLight(true); Serial.println("External LED ON");
    controlServer.send(200, "application/json", "{\"status\":\"success\",\"connected\":true,\"light_on\":true}");
  } else if (state == "off") {
    setLight(false); Serial.println("External LED OFF");
    controlServer.send(200, "application/json", "{\"status\":\"success\",\"connected\":true,\"light_on\":false}");
  } else controlServer.send(400, "application/json", "{\"error\":\"Use /light?state=on or /light?state=off\"}");
}
void handleStatus() {
  String json = String("{\"status\":\"online\",\"connected\":true,\"light_on\":") + (ledOn ? "true" : "false") + "}";
  controlServer.send(200, "application/json", json);
}
void setup() {
  Serial.begin(115200); Serial.setDebugOutput(true); Serial.println();
  pinMode(LED_PIN, OUTPUT); setLight(false);
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0; config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM; config.pin_d1 = Y3_GPIO_NUM; config.pin_d2 = Y4_GPIO_NUM; config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM; config.pin_d5 = Y7_GPIO_NUM; config.pin_d6 = Y8_GPIO_NUM; config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM; config.pin_pclk = PCLK_GPIO_NUM; config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.sccb_sda = SIOD_GPIO_NUM; config.sccb_scl = SIOC_GPIO_NUM; config.pin_pwdn = PWDN_GPIO_NUM; config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000; config.pixel_format = PIXFORMAT_JPEG; config.frame_size = FRAMESIZE_QVGA;
  config.jpeg_quality = 15; config.fb_count = 2; config.grab_mode = CAMERA_GRAB_LATEST; config.fb_location = CAMERA_FB_IN_PSRAM;
  if (!psramFound()) { config.fb_count = 1; config.fb_location = CAMERA_FB_IN_DRAM; config.grab_mode = CAMERA_GRAB_WHEN_EMPTY; }
  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) { Serial.printf("Camera init failed: 0x%x\n", err); return; }
  sensor_t *sensor = esp_camera_sensor_get();
  if (sensor) { sensor->set_framesize(sensor, FRAMESIZE_QVGA); sensor->set_quality(sensor, 15); }
#if defined(LED_GPIO_NUM)
  setupLedFlash();
#endif
  WiFi.mode(WIFI_STA); WiFi.setSleep(false); WiFi.begin(ssid, password);
  Serial.print("Connecting to Wi-Fi"); while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nWi-Fi connected");
  startCameraServer();
  controlServer.on("/status", HTTP_GET, handleStatus);
  controlServer.on("/light", HTTP_GET, handleLight);
  controlServer.onNotFound([]() { controlServer.send(404, "application/json", "{\"error\":\"not found\"}"); });
  controlServer.begin();
  Serial.print("Camera page: http://"); Serial.println(WiFi.localIP());
  Serial.print("Camera stream: http://"); Serial.print(WiFi.localIP()); Serial.println(":81/stream");
  Serial.print("Light status: http://"); Serial.print(WiFi.localIP()); Serial.println(":82/status");
  Serial.print("Light ON test: http://"); Serial.print(WiFi.localIP()); Serial.println(":82/light?state=on");
}
void loop() { controlServer.handleClient(); delay(1); }
