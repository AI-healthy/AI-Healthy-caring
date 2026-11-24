package org.aihealthy.shiyi.integration.embedded

import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

data class DailyHealthSummary(
    val date: LocalDate,
    val heartRate: Int?,
    val heartRateAt: Instant?,
    val steps: Long?,
    val sleepMinutes: Long?,
    val count: Int
)

/** Inputs belong to one selected device. Null means not measured; zero is an actual measurement. */
object DailyHealthAggregator {
    fun summarize(rows: List<HealthObservation>, now: Instant, zone: ZoneId): DailyHealthSummary {
        val date = now.atZone(zone).toLocalDate()
        val midnight = date.atStartOfDay(zone).toInstant()
        // Explicit overnight window: yesterday 18:00 to today 12:00 (or now if earlier).
        val sleepStart = date.minusDays(1).atTime(18, 0).atZone(zone).toInstant()
        val sleepEnd = minOf(now, date.atTime(12, 0).atZone(zone).toInstant())
        val valid = rows.filter { it.observedAt <= now }.distinctBy { it.id }
        val heart = valid.filter { it.metric == HealthMetric.HEART_RATE && it.value in 1..254 }
            .maxByOrNull { it.observedAt }
        // Only complete intervals in today's local calendar day. Do not invent fractions of steps.
        val stepRows = valid.filter {
            val start = it.intervalStart
            it.metric == HealthMetric.STEPS && it.value >= 0 &&
                start != null && start >= midnight && start < it.observedAt
        }.sortedWith(compareBy({ it.intervalStart }, { it.observedAt }, { it.id }))
        var stepTotal: Long? = null
        var coveredUntil: Instant? = null
        for (row in stepRows) {
            val start = row.intervalStart ?: continue
            val previous = coveredUntil
            // Conservatively skip overlaps, including duplicated intervals with different IDs.
            if (previous != null && start < previous) continue
            stepTotal = (stepTotal ?: 0L) + row.value
            coveredUntil = row.observedAt
        }
        val intervals = valid.mapNotNull {
            val start = it.intervalStart ?: return@mapNotNull null
            if (it.metric != HealthMetric.SLEEP || it.value <= 0 || start >= it.observedAt)
                return@mapNotNull null
            val a = maxOf(start, sleepStart)
            val b = minOf(it.observedAt, sleepEnd)
            if (a < b) a to b else null
        }.sortedBy { it.first }
        var seconds = 0L
        var a: Instant? = null
        var b: Instant? = null
        for ((start, end) in intervals) {
            val oldA = a
            val oldB = b
            if (oldA == null || oldB == null) {
                a = start; b = end
            } else if (start <= oldB) {
                b = maxOf(oldB, end)
            } else {
                seconds += Duration.between(oldA, oldB).seconds
                a = start; b = end
            }
        }
        val finalA = a
        val finalB = b
        if (finalA != null && finalB != null) seconds += Duration.between(finalA, finalB).seconds
        return DailyHealthSummary(date, heart?.value, heart?.observedAt, stepTotal,
            if (intervals.isEmpty()) null else seconds / 60L, valid.size)
    }
}
