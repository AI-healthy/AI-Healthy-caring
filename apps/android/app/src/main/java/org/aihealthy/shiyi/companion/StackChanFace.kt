package org.aihealthy.shiyi.companion

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.withTransform
import kotlinx.coroutines.delay

internal enum class PetMotion {
    Idle, Greeting, Shy, Inhale, Exhale, Thinking, Nod, Cheer, Calm
}

@Composable
internal fun StackChanFace(modifier: Modifier, motion: PetMotion, replay: Int = 0) {
    var animatedPose by remember { mutableStateOf(false) }
    LaunchedEffect(motion, replay) {
        animatedPose = false
        when (motion) {
            PetMotion.Idle, PetMotion.Thinking -> {
                val thinking = motion == PetMotion.Thinking
                while (true) {
                    delay(if (thinking) 500L else 3500L)
                    animatedPose = true
                    delay(if (thinking) 500L else 140L)
                    animatedPose = false
                }
            }
            PetMotion.Greeting, PetMotion.Shy, PetMotion.Nod, PetMotion.Cheer -> {
                animatedPose = true
                delay(260)
                animatedPose = false
                if (motion == PetMotion.Greeting || motion == PetMotion.Cheer) {
                    delay(160)
                    animatedPose = true
                    delay(240)
                    animatedPose = false
                }
            }
            else -> Unit
        }
    }
    val tilt by animateFloatAsState(
        targetValue = when (motion) {
            PetMotion.Greeting -> if (animatedPose) -10f else 0f
            PetMotion.Shy -> if (animatedPose) 9f else 0f
            PetMotion.Thinking -> if (animatedPose) 5f else -4f
            PetMotion.Nod -> if (animatedPose) 5f else 0f
            PetMotion.Calm -> -4f
            else -> 0f
        },
        animationSpec = tween(230), label = "tilt"
    )
    val headY by animateFloatAsState(
        targetValue = when {
            motion == PetMotion.Nod && animatedPose -> 7f
            motion == PetMotion.Cheer && animatedPose -> -12f
            else -> 0f
        },
        animationSpec = tween(230), label = "bounce"
    )
    val breath by animateFloatAsState(
        targetValue = if (motion == PetMotion.Inhale) 1f else 0f,
        animationSpec = tween(when (motion) {
            PetMotion.Inhale -> 4000
            PetMotion.Exhale -> 6000
            else -> 250
        }), label = "breath"
    )

    Canvas(modifier) {
        val unit = minOf(size.width / 240f, size.height / 200f)
        withTransform({
            translate((size.width - 240f * unit) / 2, (size.height - 200f * unit) / 2)
            scale(unit, unit, Offset.Zero)
        }) {
            val face = Color(0xFFFFFBF3)
            val pink = Color(0xFFF0A5B3)
            if (motion == PetMotion.Inhale || motion == PetMotion.Exhale) {
                drawCircle(pink.copy(alpha = 0.2f), 64f + breath * 32f, Offset(120f, 93f))
            }
            drawOval(Color(0x1F512B3B), Offset(53f, 171f), Size(134f, 16f))
            drawRoundRect(Color(0xFF60444D), Offset(69f, 151f), Size(102f, 28f), CornerRadius(10f))
            drawRoundRect(Color(0xFF885F6B), Offset(69f, 151f), Size(102f, 16f), CornerRadius(8f))
            drawRoundRect(Color(0xFF60444D), Offset(101f, 136f), Size(38f, 24f), CornerRadius(5f))

            withTransform({ translate(0f, headY); rotate(tilt, Offset(120f, 140f)) }) {
                drawRoundRect(Color(0xFFAD7083), Offset(164f, 36f), Size(33f, 107f),
                    CornerRadius(15f))
                drawCircle(Color(0xFF734F60), 3f, Offset(187f, 83f))
                drawCircle(Color(0xFF734F60), 3f, Offset(187f, 94f))
                drawRoundRect(Color(0xFFF0C4CE), Offset(47f, 32f), Size(136f, 114f),
                    CornerRadius(16f))
                drawRoundRect(Color(0xFF302933), Offset(54f, 39f), Size(122f, 83f),
                    CornerRadius(10f))
                for (x in listOf(84f, 115f, 146f)) {
                    drawRoundRect(Color(0xFFFFE7E9), Offset(x - 9f, 128f), Size(18f, 10f),
                        CornerRadius(3f))
                }

                val happy = motion in setOf(PetMotion.Greeting, PetMotion.Shy, PetMotion.Cheer)
                val eyesClosed = motion == PetMotion.Calm || (motion == PetMotion.Idle && animatedPose)
                for (x in listOf(87f, 143f)) {
                    if (eyesClosed || happy) {
                        val eye = Path().apply {
                            moveTo(x - 6f, 80f)
                            quadraticBezierTo(x, if (happy) 69f else 85f, x + 6f, 80f)
                        }
                        drawPath(eye, face, style = Stroke(3.5f, cap = StrokeCap.Round))
                    } else {
                        drawOval(face, Offset(x - 2.5f, 72f), Size(5f, 11f))
                    }
                    if (happy) drawOval(pink, Offset(x - 7f, 88f), Size(13f, 6f))
                }
                when {
                    motion == PetMotion.Thinking -> {
                        for (index in 0..2) {
                            val dim = index == if (animatedPose) 0 else 2
                            drawCircle(face.copy(alpha = if (dim) 0.35f else 1f),
                                2f, Offset(107f + index * 8f, 97f))
                        }
                    }
                    happy -> {
                        val smile = Path().apply {
                            moveTo(107f, 93f)
                            quadraticBezierTo(115f, 104f, 123f, 93f)
                        }
                        drawPath(smile, face, style = Stroke(3.3f, cap = StrokeCap.Round))
                    }
                    motion == PetMotion.Inhale || motion == PetMotion.Exhale ->
                        drawCircle(face, 2f + breath * 3f, Offset(115f, 96f),
                            style = Stroke(2f))
                    else -> drawLine(face, Offset(108f, 96f), Offset(122f, 96f),
                        strokeWidth = 3.5f, cap = StrokeCap.Round)
                }
            }
        }
    }
}
