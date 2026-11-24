package org.aihealthy.shiyi

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.time.LocalDate

private val Forest = Color(0xFF204D3D)
private val Ivory = Color(0xF0FAF9E9)
private enum class HomeIcon(val label: String) {
    Home("首页"), Health("健康"), Plan("计划"), Chat("陪伴"), Profile("我的")
}

@Composable
internal fun ShiYiHome(
    onSeasons: () -> Unit,
    onHealth: () -> Unit,
    onPlan: () -> Unit,
    onChat: () -> Unit,
    onProfile: () -> Unit
) {
    val today = LocalDate.now()
    Box(Modifier.fillMaxSize()) {
        Image(painterResource(R.drawable.shiyi_home_landscape), contentDescription = null,
            modifier = Modifier.matchParentSize(), contentScale = ContentScale.Crop)
        Box(Modifier.matchParentSize().background(Brush.verticalGradient(
            0f to Color(0x70FFFDF0), 0.43f to Color.Transparent
        )))
        BoxWithConstraints(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing)) {
            val scale = (maxWidth / 390.dp).coerceIn(0.78f, 1.33f)
            val top = (maxHeight * 0.066f).coerceIn(18.dp, 65.dp)
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 29.dp * scale).padding(top = top),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top
            ) {
                Column(Modifier.clickable(role = Role.Button, onClickLabel = "查看四时",
                    onClick = onSeasons)) {
                    Text("时宜", color = Forest, fontSize = (32 * scale).sp,
                        fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(6.dp))
                    Text("${today.monthValue}月${today.dayOfMonth}日  ·  四时", color = Forest,
                        fontSize = (13 * scale).sp)
                    Spacer(Modifier.height(14.dp))
                    Box(Modifier.width(28.dp * scale).height(2.dp).background(
                        Color(0xFF729B66), CircleShape))
                }
                Box(Modifier.size(48.dp).clip(CircleShape).background(Ivory)
                    .clickable(role = Role.Button, onClickLabel = "我的", onClick = onProfile),
                    contentAlignment = Alignment.Center) { HomeGlyph(HomeIcon.Profile) }
            }

            val ringSize = 148.dp * scale
            val ringTop = (maxHeight * 0.24f).coerceAtLeast(top + 115.dp * scale)
            Box(
                Modifier.align(Alignment.TopCenter).padding(top = ringTop)
                    .size(ringSize).clip(CircleShape).background(Ivory)
                    .clickable(role = Role.Button, onClickLabel = "活动环，查看健康",
                        onClick = onHealth),
                contentAlignment = Alignment.Center
            ) { ActivityRings(Modifier.size(124.dp * scale)) }

            Row(
                Modifier.align(Alignment.BottomCenter).fillMaxWidth()
                    .padding(horizontal = 19.dp * scale, vertical = 16.dp)
                    .height(66.dp * scale).clip(CircleShape).background(Ivory)
                    .padding(horizontal = 12.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                listOf(HomeIcon.Home to {}, HomeIcon.Health to onHealth,
                    HomeIcon.Plan to onPlan, HomeIcon.Chat to onChat).forEach { (icon, action) ->
                    Box(Modifier.weight(1f).fillMaxHeight()
                        .clickable(role = Role.Tab, onClickLabel = icon.label, onClick = action),
                        contentAlignment = Alignment.Center) { HomeGlyph(icon) }
                }
            }
        }
    }
}

@Composable
private fun ActivityRings(modifier: Modifier) {
    Canvas(modifier) {
        val unit = size.minDimension / 124f
        val colors = listOf(Color(0xFFE17968), Color(0xFFD6AB51), Color(0xFF539FBE))
        val sweeps = listOf(207f, 230f, 162f)
        val stroke = Stroke(width = 10.5f * unit, cap = StrokeCap.Butt)
        colors.forEachIndexed { index, color ->
            val inset = (8f + index * 14f) * unit
            val bounds = Size(size.width - 2 * inset, size.height - 2 * inset)
            val origin = Offset(inset, inset)
            drawArc(color.copy(alpha = 0.23f), 0f, 360f, false, origin, bounds, style = stroke)
            drawArc(color, 1f, sweeps[index], false, origin, bounds, style = stroke)
        }
    }
}

@Composable
private fun HomeGlyph(icon: HomeIcon) {
    Canvas(Modifier.size(24.dp)) {
        val unit = size.width / 24f
        fun point(x: Float, y: Float) = Offset(x * unit, y * unit)
        fun line(vararg points: Pair<Float, Float>) {
            val path = Path().apply {
                moveTo(points[0].first * unit, points[0].second * unit)
                points.drop(1).forEach { (x, y) -> lineTo(x * unit, y * unit) }
            }
            drawPath(path, Forest, style = Stroke(1.45f * unit, cap = StrokeCap.Round))
        }
        when (icon) {
            HomeIcon.Home -> line(3f to 11f, 12f to 3f, 21f to 11f, 21f to 21f,
                15f to 21f, 15f to 14f, 9f to 14f, 9f to 21f, 3f to 21f, 3f to 11f)
            HomeIcon.Health -> {
                val heart = Path().apply {
                    moveTo(12f * unit, 21f * unit)
                    cubicTo(-7f * unit, 8f * unit, 5f * unit, 0f, 12f * unit, 7f * unit)
                    cubicTo(19f * unit, 0f, 31f * unit, 8f * unit, 12f * unit, 21f * unit)
                }
                drawPath(heart, Forest, style = Stroke(1.45f * unit))
                line(4f to 12f, 8f to 12f, 10f to 9f, 13f to 15f, 15f to 12f, 20f to 12f)
            }
            HomeIcon.Plan -> {
                line(4f to 5f, 20f to 5f, 20f to 21f, 4f to 21f, 4f to 5f)
                line(8f to 3f, 8f to 7f)
                line(16f to 3f, 16f to 7f)
                line(4f to 9f, 20f to 9f)
                line(8f to 15f, 11f to 18f, 16f to 13f)
            }
            HomeIcon.Chat -> {
                line(4f to 5f, 20f to 5f, 21f to 7f, 21f to 17f, 19f to 19f,
                    8f to 19f, 4f to 22f, 4f to 19f, 3f to 17f, 3f to 7f, 4f to 5f)
                line(7f to 10f, 17f to 10f)
                line(7f to 14f, 15f to 14f)
            }
            HomeIcon.Profile -> {
                drawCircle(Forest, 3.2f * unit, point(12f, 8f), style = Stroke(1.45f * unit))
                drawArc(Forest, 188f, 164f, false, point(5f, 13f),
                    Size(14f * unit, 12f * unit), style = Stroke(1.45f * unit))
            }
        }
    }
}
