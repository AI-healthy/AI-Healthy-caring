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
import androidx.compose.ui.graphics.Brush
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
            drawOval(Color(0x24512B3B), Offset(53f, 174f), Size(136f, 14f))
            drawRoundRect(Color(0xFF84546A), Offset(66f, 153f), Size(110f, 23f),
                CornerRadius(11f))
            drawRoundRect(Brush.verticalGradient(
                listOf(Color(0xFFFFDCE4), Color(0xFFD997AD)), 149f, 166f
            ), Offset(66f, 149f), Size(110f, 18f), CornerRadius(9f))
            drawRoundRect(Color(0xFF9C6179), Offset(102f, 132f), Size(37f, 25f),
                CornerRadius(8f))

            withTransform({ translate(0f, headY); rotate(tilt, Offset(120f, 140f)) }) {
                drawRoundRect(Brush.verticalGradient(
                    listOf(Color(0xFFDA9BB2), Color(0xFF92546D)), 29f, 144f
                ), Offset(54f, 29f), Size(146f, 116f), CornerRadius(24f))
                drawRoundRect(Brush.linearGradient(
                    listOf(Color(0xFFFFF1F0), Color(0xFFE5A2B8)), Offset(49f, 32f),
                    Offset(178f, 147f)
                ), Offset(43f, 30f), Size(144f, 116f), CornerRadius(23f))
                drawRoundRect(Color(0x90FFF8F7), Offset(45f, 32f), Size(140f, 112f),
                    CornerRadius(21f), style = Stroke(1.5f))
                for (y in listOf(73f, 81f, 89f)) {
                    drawLine(Color(0xFF834C63), Offset(191f, y), Offset(195f, y),
                        strokeWidth = 2f, cap = StrokeCap.Round)
                }
                drawRoundRect(Brush.verticalGradient(
                    listOf(Color(0xFF473D51), Color(0xFF25212D)), 40f, 121f
                ), Offset(52f, 39f), Size(126f, 82f), CornerRadius(15f))
                drawLine(Color(0x30FFFFFF), Offset(67f, 46f), Offset(156f, 46f),
                    strokeWidth = 1.6f, cap = StrokeCap.Round)
                for (x in listOf(84f, 115f, 146f)) {
                    drawRoundRect(Color(0xFFBD7D95), Offset(x - 8f, 129f), Size(16f, 9f),
                        CornerRadius(4f))
                    drawRoundRect(Color(0xFFFFEBEE), Offset(x - 8f, 127f), Size(16f, 8f),
                        CornerRadius(4f))
                }

                val happy = motion == PetMotion.Cheer
                val shy = motion == PetMotion.Shy
                val greeting = motion == PetMotion.Greeting
                val eyesClosed = motion == PetMotion.Calm || (motion == PetMotion.Idle && animatedPose)
                for (x in listOf(88f, 142f)) {
                    if (eyesClosed || happy || shy) {
                        val eye = Path().apply {
                            moveTo(x - 7f, 80f)
                            quadraticBezierTo(x, if (happy || shy) 67f else 86f, x + 7f, 80f)
                        }
                        drawPath(eye, face, style = Stroke(3.5f, cap = StrokeCap.Round))
                    } else {
                        val eyeHeight = if (greeting) 20f else 15f
                        drawRoundRect(face, Offset(x - 5f, 80f - eyeHeight), Size(10f, eyeHeight),
                            CornerRadius(5f))
                    }
                    if (shy || happy) drawOval(pink, Offset(x - 8f, 88f), Size(15f, 6f))
                }
                when {
                    motion == PetMotion.Thinking -> {
                        for (index in 0..2) {
                            val dim = index == if (animatedPose) 0 else 2
                            drawCircle(face.copy(alpha = if (dim) 0.35f else 1f),
                                2f, Offset(107f + index * 8f, 97f))
                        }
                    }
                    happy || shy || greeting -> {
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
