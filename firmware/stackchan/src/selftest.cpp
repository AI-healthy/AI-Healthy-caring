#include "selftest.h"

#include <M5StackChan.h>
#include <M5Unified.h>

#include <cstdio>

namespace {

void status(const char* check, bool ok, const char* detail = "") {
  Serial.printf("[selftest] %-18s %s %s\n", check, ok ? "PASS" : "FAIL", detail);
}

void banner(const char* text, uint16_t color) {
  M5.Display.fillScreen(0x0861);
  M5.Display.setTextColor(color, 0x0861);
  M5.Display.setTextSize(2);
  M5.Display.setTextDatum(middle_center);
  M5.Display.drawString(text, 160, 120);
  M5.Display.setTextDatum(top_left);
}

void test_display() {
  const uint16_t colors[] = {TFT_RED, TFT_GREEN, TFT_BLUE, TFT_WHITE, TFT_BLACK};
  for (uint16_t color : colors) {
    M5.Display.fillScreen(color);
    delay(250);
  }
  banner("DISPLAY OK", TFT_GREEN);
  status("display", true);
}

void test_servos() {
  M5StackChan.Motion.setTorqueEnabled(true);
  M5StackChan.Motion.goHome(400);
  delay(1200);
  M5StackChan.Motion.moveX(-600, 400);
  delay(1200);
  M5StackChan.Motion.moveX(600, 400);
  delay(1200);
  M5StackChan.Motion.moveY(300, 400);
  delay(1000);
  M5StackChan.Motion.moveY(700, 400);
  delay(1000);
  M5StackChan.Motion.goHome(400);
  delay(1200);
  status("servo yaw/pitch", true, "check for binding/noise");
}

void test_rgb() {
  const uint8_t colors[][3] = {{255, 0, 0}, {0, 255, 0}, {0, 0, 255}, {255, 255, 255}};
  for (const auto& color : colors) {
    M5StackChan.showRgbColor(color[0], color[1], color[2]);
    delay(350);
  }
  M5StackChan.showRgbColor(0, 0, 0);
  status("rgb 12-led", true);
}

void test_speaker() {
  M5.Speaker.setVolume(140);
  M5.Speaker.tone(880, 200);
  delay(300);
  M5.Speaker.tone(1320, 200);
  delay(300);
  status("speaker", true);
}

void test_touch() {
  static const char* const zones[] = {"FRONT", "MIDDLE", "BACK"};
  for (int zone = 0; zone < 3; ++zone) {
    char prompt[32];
    snprintf(prompt, sizeof(prompt), "TOUCH %s", zones[zone]);
    banner(prompt, TFT_YELLOW);

    bool hit = false;
    const uint32_t started = millis();
    while (millis() - started < 8000) {
      M5StackChan.update();
      if (M5StackChan.TouchSensor.getIntensities()[zone] > 0) {
        hit = true;
        break;
      }
      delay(30);
    }
    status(prompt, hit, hit ? "" : "timeout");
    delay(250);
  }
}

void test_imu() {
  float ax = 0;
  float ay = 0;
  float az = 0;
  const bool ok = M5.Imu.getAccel(&ax, &ay, &az);
  char detail[64];
  snprintf(detail, sizeof(detail), "x=%.2f y=%.2f z=%.2f", ax, ay, az);
  status("imu accel", ok, detail);
}

}  // namespace

void run_selftest() {
  Serial.println("[selftest] K151 LAN-01 begin (not a remote verification)");
  test_display();
  test_servos();
  test_rgb();
  test_speaker();
  test_touch();
  test_imu();
  banner("SELFTEST DONE", TFT_GREEN);
  Serial.println("[selftest] K151 LAN-01 end");
}
