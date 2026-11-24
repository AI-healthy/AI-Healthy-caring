package org.aihealthy.shiyi.core.network

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import javax.net.ssl.HttpsURLConnection

/** Explicit, foreground-only upload to a trusted team HTTPS endpoint. */
class HealthApiClient(baseUrl: String, private val token: String) {
    private val base = URI(baseUrl.trim()).also {
        require(it.scheme.equals("https", ignoreCase = true) && it.host != null &&
            it.userInfo == null && it.query == null && it.fragment == null &&
            (it.path.isNullOrEmpty() || it.path == "/")) { "Use an HTTPS server origin" }
        require(token.startsWith("shiyi_") && token.none { c -> c.isWhitespace() }) {
            "Use a registered account access token"
        }
    }

    private suspend fun request(method: String, path: String, payload: JSONObject) =
        withContext(Dispatchers.IO) {
            val conn = base.resolve(path).toURL().openConnection() as HttpsURLConnection
            try {
                conn.requestMethod = method
                conn.instanceFollowRedirects = false
                conn.connectTimeout = 15000
                conn.readTimeout = 15000
                conn.setRequestProperty("Authorization", "Bearer " + token)
                conn.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                conn.doOutput = true
                conn.outputStream.use { it.write(payload.toString().toByteArray(Charsets.UTF_8)) }
                val status = conn.responseCode
                check(status in 200..299) { "Server rejected request (HTTP " + status + ")" }
                conn.inputStream.use { /* Do not log health data or credentials. */ }
            } finally {
                conn.disconnect()
            }
        }

    suspend fun consent(metrics: Set<HealthMetric>, granted: Boolean) {
        for (metric in metrics) {
            request("PUT", "/api/v1/health/consents/health_connect/" + metric.wire,
                JSONObject().put("granted", granted).put("policy_version", "local-wearable-v1"))
        }
    }

    suspend fun upload(samples: List<HealthObservation>): Int {
        var sent = 0
        for (chunk in samples.chunked(100)) {
            val records = JSONArray()
            chunk.forEach { records.put(it.toJson()) }
            request("POST", "/api/v1/health/observations", JSONObject().put("observations", records))
            sent += chunk.size
        }
        return sent
    }
}
