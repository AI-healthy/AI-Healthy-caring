package org.aihealthy.shiyi.companion

import android.os.Build
import android.view.HapticFeedbackConstants
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

internal class CompanionSession {
    val history = mutableStateListOf<ChatTurn>()
    var client by mutableStateOf<CompanionChatClient?>(null)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
internal fun StackChanCompanion(session: CompanionSession, modifier: Modifier = Modifier) {
    var chatOpen by remember { mutableStateOf(false) }
    var motion by remember { mutableStateOf(PetMotion.Idle) }
    var replay by remember { mutableIntStateOf(0) }
    var breathing by remember { mutableStateOf(false) }
    var phase by remember { mutableIntStateOf(0) }
    val view = LocalView.current
    var openChatAfterGreeting by remember { mutableStateOf(false) }

    LaunchedEffect(motion, replay) {
        if (motion == PetMotion.Greeting || motion == PetMotion.Shy || motion == PetMotion.Cheer) {
            delay(1000)
            motion = PetMotion.Idle
        }
    }
    LaunchedEffect(openChatAfterGreeting) {
        if (openChatAfterGreeting) {
            delay(460)
            openChatAfterGreeting = false
            motion = PetMotion.Idle
            chatOpen = true
        }
    }
    LaunchedEffect(breathing) {
        if (breathing) {
            repeat(3) {
                phase = it + 1
                motion = PetMotion.Inhale
                delay(4000)
                motion = PetMotion.Exhale
                delay(6000)
            }
            breathing = false
            motion = PetMotion.Cheer
            replay++
        }
    }

    if (chatOpen) {
        BackHandler { chatOpen = false }
        CompanionChat(
            modifier = modifier,
            history = session.history,
            client = session.client,
            onConnect = {
                session.history.clear()
                session.client = it
            },
            onClose = { chatOpen = false }
        )
    } else {
        Column(
            modifier = modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center
        ) {
            Text("StackChan", style = MaterialTheme.typography.headlineMedium)
            StackChanFace(
                modifier = Modifier.fillMaxWidth().height(200.dp).combinedClickable(
                    enabled = !breathing,
                    role = Role.Button,
                    onClickLabel = "摸摸 StackChan 并打开聊天",
                    onLongClickLabel = "摸摸 StackChan 的头",
                    onClick = {
                        if (!openChatAfterGreeting) {
                            view.performHapticFeedback(HapticFeedbackConstants.CLOCK_TICK)
                            motion = PetMotion.Greeting
                            replay++
                            openChatAfterGreeting = true
                        }
                    },
                    onLongClick = {
                        if (!openChatAfterGreeting) {
                            view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                            motion = PetMotion.Shy
                            replay++
                        }
                    }
                ),
                motion = motion,
                replay = replay
            )
            Text(when (motion) {
                PetMotion.Shy -> "嘿嘿，再摸一下。"
                PetMotion.Inhale -> "轻轻吸气 · $phase/3"
                PetMotion.Exhale -> "慢慢呼气 · $phase/3"
                PetMotion.Cheer -> "做得好，今天又照顾了自己一下。"
                else -> "点我聊聊，长按摸摸头"
            })
            Spacer(Modifier.height(16.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = {
                    openChatAfterGreeting = false
                    breathing = false
                    motion = PetMotion.Idle
                    chatOpen = true
                }) { Text("和我聊聊") }
                OutlinedButton(onClick = {
                    if (breathing) {
                        breathing = false
                        motion = PetMotion.Idle
                    } else {
                        openChatAfterGreeting = false
                        breathing = true
                        if (Build.VERSION.SDK_INT >= 30) {
                            view.performHapticFeedback(HapticFeedbackConstants.CONFIRM)
                        } else {
                            view.performHapticFeedback(HapticFeedbackConstants.CONTEXT_CLICK)
                        }
                    }
                }) { Text(if (breathing) "结束呼吸" else "一起慢呼吸") }
            }
        }
    }
}

@Composable
private fun CompanionChat(
    modifier: Modifier,
    history: MutableList<ChatTurn>,
    client: CompanionChatClient?,
    onConnect: (CompanionChatClient) -> Unit,
    onClose: () -> Unit
) {
    val scope = rememberCoroutineScope()
    val scroll = rememberLazyListState()
    var draft by remember { mutableStateOf("") }
    var pending by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var configuring by remember { mutableStateOf(false) }
    var reaction by remember { mutableStateOf(PetMotion.Idle) }
    var replay by remember { mutableIntStateOf(0) }

    fun send(message: String) {
        if (message.isBlank() || pending != null) return
        if (client == null) {
            configuring = true
            return
        }
        val context = history.takeLast(4)
        pending = message
        error = null
        scope.launch {
            try {
                val reply = client.send(context, message)
                history.add(ChatTurn(message, reply.text))
                if (history.size > 30) history.removeAt(0)
                draft = ""
                reaction = reply.reaction
                replay++
            } catch (cancellation: CancellationException) {
                throw cancellation
            } catch (failure: Exception) {
                error = when (failure) {
                    is java.net.SocketTimeoutException -> "等待回复超时，可以重试。"
                    is CompanionChatException -> failure.message ?: "发送失败，可以重试。"
                    is java.io.IOException -> "连接失败，请检查时宜服务地址。"
                    else -> "发送失败，可以重试。"
                }
            } finally {
                pending = null
            }
        }
    }

    LaunchedEffect(history.size, pending, replay) {
        val last = history.size + if (pending == null) -1 else 0
        if (last >= 0) scroll.animateScrollToItem(last)
    }
    LaunchedEffect(replay) {
        if (replay > 0) {
            delay(1700)
            reaction = PetMotion.Idle
        }
    }

    Column(modifier.fillMaxSize().imePadding().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onClose) { Text("返回") }
            Text("StackChan", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            TextButton(enabled = pending == null, onClick = { configuring = true }) {
                Text("对话设置")
            }
        }
        StackChanFace(
            modifier = Modifier.fillMaxWidth().height(80.dp),
            motion = if (pending != null) PetMotion.Thinking else reaction,
            replay = replay
        )
        LazyColumn(
            modifier = Modifier.fillMaxWidth().weight(1f),
            state = scroll,
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            if (history.isEmpty() && pending == null) {
                item {
                    ChatBubble("嗨，今天过得怎么样？", mine = false)
                    TextButton(onClick = { draft = "陪我聊聊今天吧。"; send(draft) }) {
                        Text("陪我聊聊今天")
                    }
                }
            }
            itemsIndexed(history) { _, turn ->
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    ChatBubble(turn.user, mine = true)
                    ChatBubble(turn.assistant, mine = false)
                }
            }
            pending?.let { message ->
                item {
                    ChatBubble(message, mine = true)
                    ChatBubble("StackChan 在想…", mine = false)
                }
            }
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        Row(
            Modifier.fillMaxWidth().padding(vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            OutlinedTextField(
                value = draft,
                onValueChange = { if (it.length <= 800) draft = it },
                enabled = pending == null,
                modifier = Modifier.weight(1f),
                label = { Text("和 StackChan 说点什么") },
                maxLines = 3
            )
            Button(onClick = { send(draft.trim()) }, enabled = pending == null && draft.isNotBlank()) {
                Text("发送")
            }
        }
    }
    if (configuring) {
        ChatSettings(
            onDismiss = { configuring = false },
            onConnect = {
                onConnect(it)
                configuring = false
                error = null
            }
        )
    }
}

@Composable
private fun ChatBubble(text: String, mine: Boolean) {
    Box(Modifier.fillMaxWidth(), contentAlignment = if (mine) Alignment.CenterEnd else Alignment.CenterStart) {
        Surface(
            modifier = Modifier.fillMaxWidth(0.86f),
            shape = MaterialTheme.shapes.medium,
            color = if (mine) MaterialTheme.colorScheme.primaryContainer
            else MaterialTheme.colorScheme.surfaceVariant
        ) {
            Text(text, Modifier.padding(12.dp))
        }
    }
}

@Composable
private fun ChatSettings(onDismiss: () -> Unit, onConnect: (CompanionChatClient) -> Unit) {
    var address by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var error by remember { mutableStateOf(false) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("连接时宜对话服务") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("发送时会把本轮文字和最近四轮对话交给时宜服务上的模型。")
                OutlinedTextField(address, { address = it }, label = { Text("时宜 HTTPS 地址") },
                    singleLine = true)
                OutlinedTextField(token, { token = it }, label = { Text("时宜登录令牌") },
                    visualTransformation = PasswordVisualTransformation(), singleLine = true)
                if (error) Text("请输入有效的 HTTPS 地址和登录令牌。",
                    color = MaterialTheme.colorScheme.error)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                val client = runCatching { CompanionChatClient(address, token.trim()) }.getOrNull()
                if (client == null) error = true else onConnect(client)
            }) { Text("保存") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("取消") } }
    )
}
