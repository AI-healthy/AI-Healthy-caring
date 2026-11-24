package org.aihealthy.shiyi.integration.embedded

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import nodomain.freeyourgadget.gadgetbridge.GBApplication
import nodomain.freeyourgadget.gadgetbridge.database.DBHelper
import nodomain.freeyourgadget.gadgetbridge.devices.huawei.honorband4.HonorBand4Coordinator
import nodomain.freeyourgadget.gadgetbridge.entities.HuaweiActivitySampleDao
import nodomain.freeyourgadget.gadgetbridge.impl.GBDevice
import nodomain.freeyourgadget.gadgetbridge.model.RecordedDataTypes
import org.aihealthy.shiyi.integration.wearable.HealthMetric
import org.aihealthy.shiyi.integration.wearable.HealthObservation
import org.aihealthy.shiyi.integration.wearable.WearableReader
import java.security.MessageDigest
import java.time.Duration
import java.time.Instant

/**
 * Adapter for the pinned Gadgetbridge source. Reads raw stored Huawei samples,
 * rather than minute-resolution samples synthesized for charts.
 */
class EmbeddedBandReader(private val band: GBDevice) : WearableReader {
    companion object {
        const val SOURCE = "gadgetbridge"
        const val ORIGIN = "org.aihealthy.shiyi.embedded"

        fun bands(): List<GBDevice> = GBApplication.app().deviceManager.devices
            .filter { supports(it) }

        fun supports(band: GBDevice): Boolean = band.deviceCoordinator is HonorBand4Coordinator ||
            HuamiBandReader.supports(band)

        fun sync(band: GBDevice) {
            check(band.deviceCoordinator.supportsActivityDataFetching()) { "Device does not support history sync" }
            check(band.isInitialized && !band.isBusy) { "Band must be ready and idle" }
            GBApplication.deviceService(band).onFetchRecordedData(RecordedDataTypes.TYPE_ACTIVITY)
        }
    }

    private val scope by lazy { WearableDeviceScope.get(band) }

    private fun id(metric: HealthMetric, start: Long, end: Long, rawSource: Int): String {
        val input = listOf(band.address, metric.wire, start, end, rawSource).joinToString("|")
        return "gb-" + MessageDigest.getInstance("SHA-256")
            .digest(input.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it.toInt() and 0xff) }
    }

    private fun observation(metric: HealthMetric, value: Int, start: Long,
                            end: Long, rawSource: Int, interval: Boolean) =
        HealthObservation(
            id(metric, start, end, rawSource), metric, value,
            Instant.ofEpochSecond(end), ORIGIN,
            if (interval) Instant.ofEpochSecond(start) else null, SOURCE, scope
        )

    override suspend fun read(start: Instant, end: Instant): List<HealthObservation> =
        withContext(Dispatchers.IO) {
            require(supports(band)) { "No raw health adapter for this model" }
            if (HuamiBandReader.supports(band)) return@withContext HuamiBandReader(band).read(start, end)
            require(start < end && Duration.between(start, end) <= Duration.ofDays(7))
            val from = Math.toIntExact(start.epochSecond)
            val until = Math.toIntExact(end.epochSecond)
            GBApplication.acquireDB().use { db ->
                val session = db.daoSession
                val device = DBHelper.findDevice(band, session) ?: return@use emptyList()
                val rows = session.huaweiActivitySampleDao.queryBuilder()
                    .where(
                        HuaweiActivitySampleDao.Properties.DeviceId.eq(device.id),
                        HuaweiActivitySampleDao.Properties.Timestamp.ge(from),
                        HuaweiActivitySampleDao.Properties.Timestamp.le(until)
                    )
                    .orderAsc(HuaweiActivitySampleDao.Properties.Timestamp)
                    .list()
                val result = mutableListOf<HealthObservation>()
                val sleep = mutableListOf<HealthObservation>()
                for (row in rows) {
                    val a = row.timestamp.toLong()
                    val b = row.otherTimestamp.toLong()
                    val rawSource = row.source.toInt() and 0xff
                    // End markers are mirror records, not new measurements.
                    if (b <= a || b > until.toLong()) continue
                    if (rawSource == 0x0b && b - a == 60L) {
                        if (row.steps in 0..200000) {
                            result += observation(HealthMetric.STEPS, row.steps, a, b, rawSource, true)
                        }
                        // Huawei encodes BPM as an unsigned byte; -1/255 means unavailable.
                        val hr = row.heartRate
                        val bpm = if (hr in -128..-2) hr and 0xff else hr
                        if (bpm in 1..254) {
                            result += observation(HealthMetric.HEART_RATE, bpm, a, a, rawSource, false)
                        }
                    }
                    // 0x0d is ordinary sleep; 0x0a is old TruSleep session data.
                    // TruSleep uses raw kind 0x06 as a placeholder, not proof of light sleep.
                    if ((rawSource == 0x0d || rawSource == 0x0a) &&
                        row.rawKind in listOf(0x06, 0x07) && b - a in 60L..86400L) {
                        sleep += observation(HealthMetric.SLEEP, ((b - a) / 60).toInt(),
                            a, b, rawSource, true)
                    }
                }
                // Prefer TruSleep intervals when ordinary sleep records overlap them.
                // Do not double-count two firmware representations of the same time.
                // Raw-source priority is retained separately; no sleep-stage inference.
                val preferred = sleep.filter { candidate ->
                    val a = candidate.intervalStart ?: return@filter false
                    val b = candidate.observedAt
                    val ordinaryId = id(HealthMetric.SLEEP, a.epochSecond, b.epochSecond, 0x0d)
                    candidate.id != ordinaryId || sleep.none { other ->
                        val x = other.intervalStart ?: return@none false
                        val y = other.observedAt
                        other.id == id(HealthMetric.SLEEP, x.epochSecond, y.epochSecond, 0x0a) &&
                            a < y && x < b
                    }
                }
                (result + preferred).distinctBy { it.id }.sortedBy { it.observedAt }
            }
        }
}
