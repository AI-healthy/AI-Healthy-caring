package org.aihealthy.shiyi.integration.embedded

import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.time.ZoneId

class DailyHealthAggregatorTest {
    private val zone = ZoneId.of("Asia/Shanghai")
    private val now = Instant.parse("2026-11-24T04:00:00Z")
    private fun row(id: String, metric: HealthMetric, value: Int, end: String, start: String? = null) =
        HealthObservation(id, metric, value, Instant.parse(end), "test", start?.let { Instant.parse(it) }, "gadgetbridge")

    @Test fun missingIsNotZero() {
        val s = DailyHealthAggregator.summarize(emptyList(), now, zone)
        assertNull(s.steps); assertNull(s.heartRate); assertNull(s.sleepMinutes)
    }

    @Test fun stepsUseLocalDayAndDoNotDoubleCount() {
        val a = row("a", HealthMetric.STEPS, 10, "2026-11-23T16:01:00Z", "2026-11-23T16:00:00Z")
        val b = row("b", HealthMetric.STEPS, 20, "2026-11-23T16:02:00Z", "2026-11-23T16:01:00Z")
        val old = row("c", HealthMetric.STEPS, 100, "2026-11-23T16:00:00Z", "2026-11-23T15:59:00Z")
        val future = row("d", HealthMetric.STEPS, 100, "2026-11-24T04:01:00Z", "2026-11-24T04:00:00Z")
        assertEquals(30L, DailyHealthAggregator.summarize(listOf(a,a,a.copy(id="dup"),b,old,future),now,zone).steps)
        assertEquals(0L, DailyHealthAggregator.summarize(listOf(a.copy(value=0)),now,zone).steps)
    }

    @Test fun sleepUnionAndNightWindow() {
        val a = row("a", HealthMetric.SLEEP, 180, "2026-11-23T18:00:00Z", "2026-11-23T15:00:00Z")
        val b = row("b", HealthMetric.SLEEP, 240, "2026-11-23T21:00:00Z", "2026-11-23T17:00:00Z")
        val old = row("c", HealthMetric.SLEEP, 60, "2026-11-23T09:00:00Z", "2026-11-23T08:00:00Z")
        assertEquals(360L, DailyHealthAggregator.summarize(listOf(a,b,old),now,zone).sleepMinutes)
    }

    @Test fun heartRateUsesLatestValidObservation() {
        val a = row("a", HealthMetric.HEART_RATE, 70, "2026-11-24T01:00:00Z")
        val b = row("b", HealthMetric.HEART_RATE, 85, "2026-11-24T02:00:00Z")
        val invalid = row("c", HealthMetric.HEART_RATE, 255, "2026-11-24T03:00:00Z")
        val s = DailyHealthAggregator.summarize(listOf(a,b,invalid),now,zone)
        assertEquals(85,s.heartRate)
        assertEquals(b.observedAt,s.heartRateAt)
    }
}
