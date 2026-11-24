package org.aihealthy.shiyi.integration.wearable

import java.time.Instant
import org.json.JSONObject

enum class HealthMetric(val wire: String, val label: String) {
    HEART_RATE("heart_rate_bpm", "心率"),
    RESTING_HEART_RATE("resting_heart_rate_bpm", "静息心率"),
    STEPS("steps", "步数"),
    SLEEP("sleep_minutes", "睡眠记录时段")
}

data class HealthObservation(
    val id: String,
    val metric: HealthMetric,
    val value: Int,
    val observedAt: Instant,
    val origin: String,
    val intervalStart: Instant? = null,
    val source: String = "health_connect"
) {
    fun toJson(): JSONObject = JSONObject()
        .put("client_sample_id", id)
        .put("source", source)
        .put("metric", metric.wire)
        .put("value", value)
        .put("observed_at", observedAt.toString())
        .put("interval_start", intervalStart?.toString() ?: JSONObject.NULL)
        .put("data_origin", origin)
        .put("is_demo", false)
}

/** Source-independent reader; a future embedded Gadgetbridge driver can implement this. */
interface WearableReader {
    suspend fun read(start: Instant, end: Instant): List<HealthObservation>
}
