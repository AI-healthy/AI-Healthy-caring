#include <Arduino.h>
#include <HTTPClient.h>
#include <M5StackChan.h>
#include <M5Unified.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

#include <ctime>
#include <cstdio>
#include <cstring>

#include "board_config.h"
#include "device_protocol.h"

#if __has_include("secrets.h")
#include "secrets.h"
#endif
#ifndef HC_WIFI_SSID
#define HC_WIFI_SSID "your-wifi"
#endif
#ifndef HC_WIFI_PASS
#define HC_WIFI_PASS "your-password"
#endif
#ifndef HC_DEVICE_TOKEN
#define HC_DEVICE_TOKEN "device-token"
#endif

namespace {

WiFiClientSecure g_tls;
Preferences g_prefs;
uint32_t g_last_poll = 0;

constexpr uint16_t kBackground = 0x0861;
constexpr uint16_t kAccent = 0xFE59;
constexpr uint16_t kText = 0xFFFF;
constexpr uint16_t kFace = 0xFFE0;

// ------------------------------ HTTP helpers ------------------------------

String api_url(const char* suffix) {
  return String(HC_API_BASE) + "/api/v1/devices/" + HC_DEVICE_ID + suffix;
}

bool http_get(const String& url, String& body) {
  HTTPClient http;
  http.setTimeout(HC_HTTP_TIMEOUT_MS);
  if (!http.begin(g_tls, url)) return false;
  http.addHeader("Authorization", String("Bearer ") + HC_DEVICE_TOKEN);
  const int status = http.GET();
  if (status == 200) body = http.getString();
  http.end();
  return status == 200;
}

bool http_post_json(const String& url, const String& payload) {
  HTTPClient http;
  http.setTimeout(HC_HTTP_TIMEOUT_MS);
  if (!http.begin(g_tls, url)) return false;
  http.addHeader("Authorization", String("Bearer ") + HC_DEVICE_TOKEN);
  http.addHeader("Content-Type", "application/json");
  const int status = http.POST(payload);
  http.end();
  return status >= 200 && status < 300;
}

bool post_event(const char* command_id, const char* event_type, const char* reason,
                int elapsed_seconds) {
  JsonDocument doc;
  build_event(doc, HC_DEVICE_ID, command_id, event_type, reason, elapsed_seconds);
  String body;
  serializeJson(doc, body);
  const String url = api_url("/events");
  for (int attempt = 0; attempt < HC_EVENT_RETRIES; ++attempt) {
    if (http_post_json(url, body)) return true;
    delay(300);
  }
  return false;
}

// ------------------------------ NVS recovery ------------------------------

bool load_terminal(const char* command_id, char* type, size_t type_cap, char* reason,
                   size_t reason_cap, int& elapsed) {
  if (g_prefs.getString("acked_id", "") != command_id) return false;
  const String stored_type = g_prefs.getString("term_type", "");
  if (stored_type.isEmpty()) return false;
  const String stored_reason = g_prefs.getString("term_reason", "");
  type[0] = '\0';
  reason[0] = '\0';
  strncat(type, stored_type.c_str(), type_cap - 1);
  strncat(reason, stored_reason.c_str(), reason_cap - 1);
  elapsed = g_prefs.getInt("term_elapsed", 0);
  return true;
}

void remember_ack(const char* command_id) {
  g_prefs.putString("acked_id", command_id);
  g_prefs.remove("term_type");
  g_prefs.remove("term_reason");
  g_prefs.remove("term_elapsed");
}

void remember_terminal(const char* command_id, const char* type, const char* reason,
                       int elapsed) {
  g_prefs.putString("acked_id", command_id);
  g_prefs.putString("term_type", type);
  g_prefs.putString("term_reason", reason);
  g_prefs.putInt("term_elapsed", elapsed);
}

void clear_terminal() {
  g_prefs.remove("term_type");
  g_prefs.remove("term_reason");
  g_prefs.remove("term_elapsed");
}

// ------------------------------ UI helpers --------------------------------

void draw_line(const char* text, int y, uint16_t color, uint8_t size = 2) {
  M5.Display.setTextColor(color, kBackground);
  M5.Display.setTextSize(size);
  M5.Display.setCursor(16, y);
  M5.Display.print(text);
}

void draw_centered(const char* text, int y, uint16_t color, uint8_t size = 2) {
  M5.Display.setTextColor(color, kBackground);
  M5.Display.setTextSize(size);
  M5.Display.setTextDatum(middle_center);
  M5.Display.drawString(text, 160, y);
  M5.Display.setTextDatum(top_left);
}

void draw_face(const char* preset) {
  M5.Display.fillScreen(kBackground);
  M5.Display.fillCircle(160, 112, 72, kFace);

  const bool sleepy = strcmp(preset, "sleepy") == 0;
  const bool happy = strcmp(preset, "happy") == 0;
  if (sleepy) {
    M5.Display.drawLine(88, 100, 126, 100, TFT_BLACK);
    M5.Display.drawLine(194, 100, 232, 100, TFT_BLACK);
  } else {
    M5.Display.fillCircle(104, 96, 9, TFT_BLACK);
    M5.Display.fillCircle(216, 96, 9, TFT_BLACK);
  }

  if (happy) {
    M5.Display.drawLine(124, 140, 160, 158, TFT_BLACK);
    M5.Display.drawLine(160, 158, 196, 140, TFT_BLACK);
  } else if (sleepy) {
    M5.Display.drawLine(140, 148, 180, 148, TFT_BLACK);
  } else {
    M5.Display.drawLine(136, 152, 184, 152, TFT_BLACK);
  }

  char label[32];
  snprintf(label, sizeof(label), "%s", preset);
  draw_centered(label, 208, kText, 1);
}

void draw_timer(const char* title, int remaining) {
  M5.Display.fillScreen(kBackground);
  draw_centered(title, 60, kText, 2);
  char clock[16];
  snprintf(clock, sizeof(clock), "%02d:%02d", remaining / 60, remaining % 60);
  draw_centered(clock, 120, kAccent, 4);
  draw_centered("tap = done / hold = stop", 196, 0xAD55, 1);
}

// ------------------------------ Motion presets ----------------------------

int clamp_yaw(int value) { return value < HC_YAW_MIN ? HC_YAW_MIN : (value > HC_YAW_MAX ? HC_YAW_MAX : value); }

int clamp_pitch(int value) {
  return value < HC_PITCH_MIN ? HC_PITCH_MIN : (value > HC_PITCH_MAX ? HC_PITCH_MAX : value);
}

void pose(int yaw, int pitch, int speed = 600) {
  M5StackChan.Motion.move(clamp_yaw(yaw), clamp_pitch(pitch), speed);
}

void move_preset(const char* preset) {
  if (strcmp(preset, "nod") == 0) {
    pose(0, 800);
    delay(500);
    pose(0, 300);
    delay(500);
    pose(0, 800);
    delay(500);
  } else if (strcmp(preset, "shake") == 0) {
    pose(-450, 620);
    delay(400);
    pose(450, 620);
    delay(400);
    pose(-450, 620);
    delay(400);
    pose(450, 620);
    delay(400);
  } else if (strcmp(preset, "tilt") == 0) {
    pose(-400, 650, 450);
    delay(1200);
  } else if (strcmp(preset, "look_around") == 0) {
    pose(-720, 540, 500);
    delay(900);
    pose(720, 540, 500);
    delay(900);
  } else if (strcmp(preset, "greet") == 0) {
    pose(0, 820, 600);
    delay(500);
    pose(-360, 820, 600);
    delay(500);
    pose(0, 820, 600);
    delay(500);
  }
  M5StackChan.Motion.goHome(500);
  delay(600);
}

// ------------------------------ Command execution -------------------------

bool run_countdown(const char* title, int seconds, int& elapsed, const char*& outcome) {
  const uint32_t started = millis();
  while (true) {
    const uint32_t passed = (millis() - started) / 1000;
    if (static_cast<int>(passed) >= seconds) break;
    const int remaining = seconds - static_cast<int>(passed);
    draw_timer(title, remaining);

    M5StackChan.update();
    if (M5StackChan.TouchSensor.pressedFor(1500)) {
      elapsed = static_cast<int>(passed);
      outcome = "user_declined";
      draw_centered("stopped", 176, kAccent, 2);
      return false;
    }
    if (M5StackChan.TouchSensor.wasClicked()) {
      elapsed = static_cast<int>(passed);
      outcome = "touch_confirmed";
      draw_centered("done", 176, 0x07E0, 2);
      return true;
    }
    delay(100);
  }
  elapsed = seconds;
  outcome = "timer_elapsed";
  return true;
}

bool execute(const ParsedCommand& command, int& elapsed, const char*& outcome) {
  JsonObjectConst payload = command.payload();
  elapsed = 0;
  outcome = "timer_elapsed";

  switch (command.kind) {
    case CommandKind::SetExpression: {
      const char* preset = payload["preset"] | "neutral";
      draw_face(preset);
      elapsed = 1;
      delay(600);
      return true;
    }
    case CommandKind::SpeakText: {
      const char* text = payload["text"] | "";
      M5.Display.fillScreen(kBackground);
      draw_centered("speaking (text only)", 40, 0xAD55, 1);
      draw_line(text, 80, kText, 2);
      M5.Speaker.tone(880, 120);
      elapsed = 3;
      delay(static_cast<uint32_t>(elapsed) * 1000);
      return true;
    }
    case CommandKind::PlayGuide: {
      const int seconds = payload["duration_seconds"] | 300;
      const char* title = payload["title"] | "guide";
      return run_countdown(title, seconds, elapsed, outcome);
    }
    case CommandKind::ShowTimer: {
      const int seconds = payload["duration_seconds"] | 60;
      const char* label = payload["label"] | "timer";
      return run_countdown(label, seconds, elapsed, outcome);
    }
    case CommandKind::MoveHeadPreset: {
      const char* preset = payload["preset"] | "";
      move_preset(preset);
      elapsed = 2;
      return true;
    }
    case CommandKind::CancelTask: {
      M5.Display.fillScreen(kBackground);
      draw_centered("cancelled", 120, kAccent, 3);
      M5StackChan.Motion.stop();
      elapsed = 0;
      return true;
    }
    default:
      outcome = "unsupported_command";
      return false;
  }
}

void handle_command(ParsedCommand& command) {
  if (strcmp(command.status, "QUEUED") == 0) {
    if (!post_event(command.id, "COMMAND_ACKNOWLEDGED", "accepted", 0)) {
      // Do not act without a durable ACK; the command stays QUEUED server-side.
      return;
    }
    remember_ack(command.id);
  } else if (strcmp(command.status, "ACKNOWLEDGED") == 0) {
    char type[24] = {0};
    char reason[24] = {0};
    int elapsed = 0;
    if (load_terminal(command.id, type, sizeof(type), reason, sizeof(reason), elapsed)) {
      // The previous terminal event may have been lost; replay the same event ID.
      if (post_event(command.id, type, reason, elapsed)) clear_terminal();
      return;
    }
    // ACK was sent but no outcome was persisted (e.g. power loss). Do not repeat
    // a physical action blindly.
    post_event(command.id, "COMMAND_FAILED", "resume_without_state", 0);
    return;
  } else {
    return;
  }

  const char* invalid_reason = nullptr;
  if (!validate_payload(command, invalid_reason)) {
    post_event(command.id, "COMMAND_FAILED", invalid_reason, 0);
    return;
  }

  int elapsed = 0;
  const char* outcome = nullptr;
  const bool ok = execute(command, elapsed, outcome);
  const char* event_type = ok ? "COMMAND_COMPLETED" : "COMMAND_FAILED";
  remember_terminal(command.id, event_type, outcome, elapsed);
  if (post_event(command.id, event_type, outcome, elapsed)) clear_terminal();
}

void poll_once() {
  String body;
  if (!http_get(api_url("/pending"), body)) return;
  if (body.isEmpty() || body == "null") return;

  ParsedCommand command;
  if (!parse_pending(body.c_str(), body.length(), command)) {
    Serial.println("[lan] invalid pending payload");
    return;
  }
  handle_command(command);
}

void connect_network() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(HC_WIFI_SSID, HC_WIFI_PASS);
  const uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 15000) {
    delay(250);
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("[lan] wifi ok ip=%s\n", WiFi.localIP().toString().c_str());
    configTime(0, 0, "pool.ntp.org");
  } else {
    Serial.println("[lan] wifi unavailable; local commands still work");
  }
}

}  // namespace

void setup() {
  M5StackChan.begin();
  Serial.begin(115200);
  delay(100);

  M5.Display.setRotation(1);
  M5.Display.setBrightness(180);
  M5.Display.setFont(&fonts::efontCN_16);
  M5.Display.setTextDatum(top_left);
  M5.Display.fillScreen(kBackground);
  draw_centered("ShiYi Stack-chan", 80, kText, 2);
  draw_centered("LAN-01 firmware skeleton", 115, 0xAD55, 1);

  M5StackChan.Motion.setAutoTorqueReleaseEnabled(false);
  M5StackChan.Motion.goHome(400);
  M5.Speaker.setVolume(120);

  g_prefs.begin("shiyi-lan", false);
  g_tls.setInsecure();  // local demo only; pin a CA in production
  connect_network();

  Serial.printf("[lan] fw=%s device=%s api=%s\n", HC_FW_VERSION, HC_DEVICE_ID, HC_API_BASE);
  g_last_poll = 0;
}

void loop() {
  M5StackChan.update();

  if (WiFi.status() != WL_CONNECTED) {
    static uint32_t last_retry = 0;
    if (millis() - last_retry > 10000) {
      last_retry = millis();
      WiFi.reconnect();
    }
    delay(100);
    return;
  }

  const uint32_t now = millis();
  if (now - g_last_poll >= HC_POLL_INTERVAL_MS) {
    g_last_poll = now;
    poll_once();
  }
  delay(20);
}
