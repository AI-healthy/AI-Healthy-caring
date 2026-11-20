#pragma once

// LAN-01/LAN-02 firmware configuration. Copy secrets.example.h to secrets.h.
#define HC_FW_VERSION "0.1.0"
#define HC_SCHEMA_VERSION "0.1-draft"

#ifndef HC_DEVICE_ID
#define HC_DEVICE_ID "sim"
#endif

// Local demo API. Production must use https:// and a pinned CA.
#ifndef HC_API_BASE
#define HC_API_BASE "http://192.168.1.10:8000"
#endif

#define HC_POLL_INTERVAL_MS 1500
#define HC_HTTP_TIMEOUT_MS 8000
#define HC_EVENT_RETRIES 3

#define HC_MAX_TEXT_BYTES 200
#define HC_MIN_GUIDE_SECONDS 30
#define HC_MAX_GUIDE_SECONDS 900

// Safe motion envelope for K151 (0.1 degree units).
#define HC_YAW_MIN -1200
#define HC_YAW_MAX 1200
#define HC_PITCH_MIN 50
#define HC_PITCH_MAX 850
#define HC_PITCH_HOME 450
