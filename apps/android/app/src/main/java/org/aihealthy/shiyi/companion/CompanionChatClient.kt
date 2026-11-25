package org.aihealthy.shiyi.companion

import android.content.Context
import android.content.pm.PackageManager
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.URI
import javax.net.ssl.HttpsURLConnection

internal class CompanionChatException(message: String) : Exception(message)

internal data class ChatTurn(val user: String, val assistant: String)
internal data class CompanionReply(val text: String, val reaction: PetMotion)

internal class CompanionChatClient(origin: String) {
    private val endpoint = URI(origin.trim()).also {
        require(it.scheme == "https" && it.host != null && it.userInfo == null &&
            it.query == null && it.fragment == null && (it.path.isEmpty() || it.path == "/"))
    }.resolve("/api/v1/companion/guest-chat").toURL()

    companion object {
        fun fromApp(context: Context): CompanionChatClient? {
            val info = context.packageManager.getApplicationInfo(
                context.packageName, PackageManager.GET_META_DATA
            )
            val origin = info.metaData?.getString("org.aihealthy.shiyi.CHAT_ORIGIN").orEmpty()
            return runCatching { CompanionChatClient(origin) }.getOrNull()
        }
    }

    suspend fun send(history: List<ChatTurn>, message: String): CompanionReply =
        withContext(Dispatchers.IO) {
            val messages = JSONArray()
            for (turn in history.takeLast(4)) {
                messages.put(JSONObject().put("role", "user").put("content", turn.user))
                messages.put(JSONObject().put("role", "assistant").put("content", turn.assistant))
            }
            messages.put(JSONObject().put("role", "user").put("content", message))
            val connection = endpoint.openConnection() as HttpsURLConnection
            try {
                connection.requestMethod = "POST"
                connection.instanceFollowRedirects = false
                connection.connectTimeout = 10_000
                connection.readTimeout = 40_000
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8")
                connection.doOutput = true
                val body = JSONObject().put("messages", messages).toString()
                connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                when (connection.responseCode) {
                    200 -> Unit
                    401 -> throw CompanionChatException("聊天服务暂未开放。")
                    429 -> throw CompanionChatException("StackChan 正在忙，稍等一下再发送。")
                    502, 503, 504 -> throw CompanionChatException("暂时连不上对话模型，可以稍后重试。")
                    else -> throw CompanionChatException("对话服务暂时不可用。")
                }
                val chars = CharArray(8193)
                val reply = connection.inputStream.bufferedReader(Charsets.UTF_8).use { reader ->
                    var size = 0
                    while (size < chars.size) {
                        val read = reader.read(chars, size, chars.size - size)
                        if (read < 0) break
                        size += read
                    }
                    if (size == chars.size) throw CompanionChatException("对话响应过长。")
                    JSONObject(String(chars, 0, size))
                }
                val text = reply.getString("reply")
                if (text.isBlank() || text.length > 1600) throw CompanionChatException("对话响应格式有误。")
                val motion = when (reply.getString("reaction")) {
                    "cheer" -> PetMotion.Cheer
                    "calm" -> PetMotion.Calm
                    else -> PetMotion.Nod
                }
                CompanionReply(text, motion)
            } finally {
                connection.disconnect()
            }
        }
}
