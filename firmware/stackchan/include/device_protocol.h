#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>

#include "board_config.h"

enum class CommandKind : uint8_t {
  Unknown = 0,
  SetExpression,
  SpeakText,
  PlayGuide,
  ShowTimer,
  MoveHeadPreset,
  CancelTask,
};

struct ParsedCommand {
  JsonDocument doc;
  char id[40] = {0};
  char type[24] = {0};
  char status[16] = {0};
  CommandKind kind = CommandKind::Unknown;

  JsonObjectConst payload() const { return doc["payload"].as<JsonObjectConst>(); }
};

// Parses the flat CommandView returned by GET /devices/{id}/pending.
bool parse_pending(const char* json, size_t length, ParsedCommand& out);

// Mirrors the server-side Pydantic rules before touching hardware.
bool validate_payload(const ParsedCommand& command, const char*& reason);

const char* kind_name(CommandKind kind);

// Builds a flat DeviceEvent body for POST /devices/{id}/events.
void build_event(JsonDocument& doc, const char* device_id, const char* command_id,
                 const char* event_type, const char* reason, int elapsed_seconds);

void iso8601_now(char* out, size_t capacity);
