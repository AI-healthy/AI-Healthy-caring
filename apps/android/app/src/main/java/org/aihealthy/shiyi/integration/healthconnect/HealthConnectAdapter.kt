package org.aihealthy.shiyi.integration.healthconnect

import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.Record
import androidx.health.connect.client.records.metadata.DataOrigin
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import org.aihealthy.shiyi.integration.wearable.WearableReader
import java.security.MessageDigest
import java.time.Duration
import java.time.Instant
import kotlin.reflect.KClass

class HealthConnectAdapter(
    private val client: HealthConnectClient,
    private val packageName: String = GADGETBRIDGE_PACKAGE
) : WearableReader {
    companion object {
        const val GADGETBRIDGE_PACKAGE = "nodomain.freeyourgadget.gadgetbridge"
        val permissions = setOf(
            HealthPermission.getReadPermission(HeartRateRecord::class),
            HealthPermission.getReadPermission(RestingHeartRateRecord::class),
            HealthPermission.getReadPermission(StepsRecord::class),
            HealthPermission.getReadPermission(SleepSessionRecord::class)
        )
    }

    suspend fun authorized(): Boolean =
        client.permissionController.getGrantedPermissions().containsAll(permissions)

    private suspend fun <T : Record> records(
        type: KClass<T>, start: Instant, end: Instant
    ): List<T> {
        val result = mutableListOf<T>()
        var token: String? = null
        do {
            val page = client.readRecords(
                ReadRecordsRequest(
                    recordType = type,
                    timeRangeFilter = TimeRangeFilter.between(start, end),
                    dataOriginFilter = setOf(DataOrigin(packageName)),
                    pageSize = 500,
                    pageToken = token
                )
            )
            result.addAll(page.records)
            token = page.pageToken
        } while (token != null)
        return result
    }

    private fun stableId(metric: HealthMetric, record: Record, time: Instant): String {
        val key = listOf(packageName, metric.wire, record.metadata.id, time.toString()).joinToString("|")
        return "hc-" + MessageDigest.getInstance("SHA-256")
            .digest(key.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    private fun sample(
        metric: HealthMetric, record: Record, value: Long,
        time: Instant, start: Instant? = null
    ): HealthObservation = HealthObservation(
        stableId(metric, record, time), metric, value.toInt(), time,
        record.metadata.dataOrigin.packageName, start
    )

    override suspend fun read(start: Instant, end: Instant): List<HealthObservation> {
        require(start < end && Duration.between(start, end) <= Duration.ofDays(7))
        check(authorized()) { "Health Connect permissions are required" }
        val out = mutableListOf<HealthObservation>()
        for (record in records(HeartRateRecord::class, start, end)) {
            for (point in record.samples) {
                if (point.time >= start && point.time <= end && point.beatsPerMinute in 1L..300L) {
                    out += sample(HealthMetric.HEART_RATE, record, point.beatsPerMinute, point.time)
                }
            }
        }
        for (record in records(RestingHeartRateRecord::class, start, end)) {
            if (record.time >= start && record.time <= end && record.beatsPerMinute in 1L..300L) {
                out += sample(HealthMetric.RESTING_HEART_RATE, record, record.beatsPerMinute, record.time)
            }
        }
        for (record in records(StepsRecord::class, start, end)) {
            val duration = Duration.between(record.startTime, record.endTime)
            if (record.endTime <= end && !duration.isZero && !duration.isNegative &&
                duration <= Duration.ofDays(1) && record.count in 0L..200000L
            ) {
                out += sample(HealthMetric.STEPS, record, record.count, record.endTime, record.startTime)
            }
        }
        for (record in records(SleepSessionRecord::class, start, end)) {
            // Session elapsed minutes, not inferred physiological sleep or HRV.
            val duration = Duration.between(record.startTime, record.endTime)
            if (record.endTime <= end && !duration.isNegative && !duration.isZero &&
                duration <= Duration.ofDays(1)
            ) {
                out += sample(HealthMetric.SLEEP, record, duration.toMinutes(), record.endTime, record.startTime)
            }
        }
        check(authorized()) { "Health Connect permission was revoked" }
        return out.distinctBy { it.id }.sortedBy { it.observedAt }
    }
}
