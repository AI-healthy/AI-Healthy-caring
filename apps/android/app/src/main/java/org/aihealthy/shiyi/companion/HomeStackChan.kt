package org.aihealthy.shiyi.companion

import android.os.SystemClock
import android.view.HapticFeedbackConstants
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun HomeStackChan(modifier: Modifier, onChat: () -> Unit) {
    var motion by remember { mutableStateOf(PetMotion.Idle) }
    var replay by remember { mutableIntStateOf(0) }
    var lastTap by remember { mutableLongStateOf(-1L) }
    var idleAction by remember { mutableIntStateOf(0) }
    val view = LocalView.current
    val touches = remember { MutableInteractionSource() }
    val pressed by touches.collectIsPressedAsState()
    val scale by animateFloatAsState(if (pressed) 0.92f else 1f, label = "pet touch")

    LaunchedEffect(motion, replay, pressed) {
        if (!pressed) {
            if (motion == PetMotion.Idle) {
                delay(if (idleAction == 0) 6200 else 9200)
                motion = if (idleAction % 3 == 2) PetMotion.Calm else PetMotion.Nod
                idleAction++
            } else {
                delay(if (motion == PetMotion.Calm) 1700 else 1150)
                motion = PetMotion.Idle
            }
        }
    }

    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        StackChanFace(
            Modifier.weight(1f).fillMaxWidth().scale(scale).combinedClickable(
                interactionSource = touches,
                indication = null,
                role = Role.Button,
                onClickLabel = "逗逗 StackChan",
                onLongClickLabel = "给 StackChan 摸摸头",
                onClick = {
                    val now = SystemClock.uptimeMillis()
                    val rapidTap = lastTap >= 0 && now - lastTap <= 360
                    view.performHapticFeedback(
                        if (rapidTap) HapticFeedbackConstants.CONTEXT_CLICK
                        else HapticFeedbackConstants.CLOCK_TICK
                    )
                    motion = if (rapidTap) PetMotion.Cheer else PetMotion.Greeting
                    replay++
                    lastTap = if (rapidTap) -1L else now
                },
                onLongClick = {
                    view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                    motion = PetMotion.Shy
                    replay++
                    lastTap = -1L
                }
            ),
            motion = motion,
            replay = replay
        )
        Surface(
            onClick = {
                view.performHapticFeedback(HapticFeedbackConstants.CONTEXT_CLICK)
                onChat()
            },
            shape = CircleShape,
            color = Color(0xF7FAF9E9),
            contentColor = Color(0xFF204D3D)
        ) {
            androidx.compose.foundation.layout.Box(
                Modifier.heightIn(min = 48.dp),
                contentAlignment = Alignment.Center
            ) {
                Text("  聊一聊  ", fontSize = 13.sp)
            }
        }
    }
}
