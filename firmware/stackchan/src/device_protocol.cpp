#include "device_protocol.h"

#include <cstring>
#include <ctime>

namespace {

constexpr const char* kReasonInvalid = "invalid_payload";

bool is_one_of(JsonVariantConst value, const char* const* options, size_t count) {
  if (!value.is<const char*>()) return false;
  const char* text = value.as<const char*>();
  for (size_t i = 0; i < count; ++i) {
    if (std::strcmp(text, options[i]) == 0) return true;
  }
  return false;
}

void copy_text(char* dst, size_t capacity, const char* src) {
  if (capacity == 0) return;
  if (src == nullptr) {
    dst[0] = '\0';
    return;
  }
  const size_t length = strnlen(src, capacity - 1);
  memcpy(dst, src, length);
  dst[length] = '\0';
}

}  // namespace

const char* kind_name(CommandKind kind) {
  switch (kind) {
    case CommandKind::SetExpression:
      return "SET_EXPRESSION";
    case CommandKind::SpeakText:
      return "SPEAK_TEXT";
    case CommandKind::PlayGuide:
      return "PLAY_GUIDE";
    case CommandKind::ShowTimer:
      return "SHOW_TIMER";
    case CommandKind::MoveHeadPreset:
      return "MOVE_HEAD_PRESET";
    case CommandKind::CancelTask:
      return "CANCEL_TASK";
    default:
      return "UNKNOWN";
  }
}

namespace {

CommandKind kind_from_text(const char* type) {
  if (std::strcmp(type, "SET_EXPRESSION") == 0) return CommandKind::SetExpression;
  if (std::strcmp(type, "SPEAK_TEXT") == 0) return CommandKind::SpeakText;
  if (std::strcmp(type, "PLAY_GUIDE") == 0) return CommandKind::PlayGuide;
  if (std::strcmp(type, "SHOW_TIMER") == 0) return CommandKind::ShowTimer;
  if (std::strcmp(type, "MOVE_HEAD_PRESET") == 0) return CommandKind::MoveHeadPreset;
  if (std::strcmp(type, "CANCEL_TASK") == 0) return CommandKind::CancelTask;
  return CommandKind::Unknown;
}

}  // namespace

bool parse_pending(const char* json, size_t length, ParsedCommand& out) {
  out.doc.clear();
  const DeserializationError error = deserializeJson(out.doc, json, length);
  if (error) return false;

  JsonObjectConst root = out.doc.as<JsonObjectConst>();
  if (root.isNull()) return false;
  if (!root["payload"].is<JsonObjectConst>()) return false;

  const char* id = root["command_id"] | "";
  const char* type = root["type"] | "";
  const char* status = root["status"] | "";
  if (id[0] == '\0' || type[0] == '\0' || status[0] == '\0') return false;

  copy_text(out.id, sizeof(out.id), id);
  copy_text(out.type, sizeof(out.type), type);
  copy_text(out.status, sizeof(out.status), status);
  out.kind = kind_from_text(out.type);
  return true;
}

bool validate_payload(const ParsedCommand& command, const char*& reason) {
  reason = nullptr;
  JsonObjectConst payload = command.payload();

  switch (command.kind) {
    case CommandKind::SetExpression: {
      static const char* const kPresets[] = {"happy", "neutral", "sleepy"};
      if (!is_one_of(payload["preset"], kPresets, 3)) {
        reason = kReasonInvalid;
        return false;
      }
      return true;
    }
    case CommandKind::SpeakText: {
      JsonVariantConst text = payload["text"];
      if (!text.is<const char*>()) {
        reason = kReasonInvalid;
        return false;
      }
      const char* value = text.as<const char*>();
      const size_t length = strnlen(value, HC_MAX_TEXT_BYTES + 1);
      if (length == 0 || length > HC_MAX_TEXT_BYTES) {
        reason = kReasonInvalid;
        return false;
      }
      return true;
    }
    case CommandKind::PlayGuide: {
      const int duration = payload["duration_seconds"] | 0;
      if (!payload["guide_id"].is<const char*>() || !payload["title"].is<const char*>()) {
        reason = kReasonInvalid;
        return false;
      }
      if (duration < HC_MIN_GUIDE_SECONDS || duration > HC_MAX_GUIDE_SECONDS) {
        reason = kReasonInvalid;
        return false;
      }
      return true;
    }
    case CommandKind::ShowTimer: {
      const int duration = payload["duration_seconds"] | 0;
      if (duration < 10 || duration > 3600 || !payload["label"].is<const char*>()) {
        reason = kReasonInvalid;
        return false;
      }
      return true;
    }
    case CommandKind::MoveHeadPreset: {
      static const char* const kPresets[] = {"nod", "shake", "tilt", "look_around", "greet"};
      if (!is_one_of(payload["preset"], kPresets, 5)) {
        reason = kReasonInvalid;
        return false;
      }
      return true;
    }
    case CommandKind::CancelTask:
      return true;
    default:
      reason = "unsupported_command";
      return false;
  }
}

void iso8601_now(char* out, size_t capacity) {
  const time_t now = time(nullptr);
  struct tm utc {};
  gmtime_r(&now, &utc);
  strftime(out, capacity, "%Y-%m-%dT%H:%M:%SZ", &utc);
}

void build_event(JsonDocument& doc, const char* device_id, const char* command_id,
                 const char* event_type, const char* reason, int elapsed_seconds) {
  doc.clear();
  doc["schema_version"] = HC_SCHEMA_VERSION;

  // event_id is stable for the same command/outcome so retries are idempotent.
  char event_id[100];
  if (reason != nullptr && reason[0] != '\0') {
    snprintf(event_id, sizeof(event_id), "%s:%s:%s", command_id, event_type, reason);
  } else {
    snprintf(event_id, sizeof(event_id), "%s:%s", command_id, event_type);
  }

  char occurred[24];
  iso8601_now(occurred, sizeof(occurred));

  doc["event_id"] = event_id;
  doc["device_id"] = device_id;
  doc["type"] = event_type;
  doc["command_id"] = command_id;
  doc["occurred_at"] = occurred;
  doc["is_demo"] = true;
  if (reason != nullptr && reason[0] != '\0') doc["reason"] = reason;
  if (elapsed_seconds >= 0) doc["elapsed_seconds"] = elapsed_seconds;
}
