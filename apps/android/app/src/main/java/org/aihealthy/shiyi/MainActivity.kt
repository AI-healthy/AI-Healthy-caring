package org.aihealthy.shiyi

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val Ink = Color(0xFF26342E)
private val Moss = Color(0xFF577462)
private val Paper = Color(0xFFF7F8F4)

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { ShiYiApp() }
    }
}

@Composable
private fun ShiYiApp() {
    var tab by remember { mutableIntStateOf(0) }
    var message by remember { mutableStateOf("今天也可以从一件小事开始。") }
    val tabs = listOf("今日", "四时", "探索", "我的")
    MaterialTheme(colorScheme = lightColorScheme(primary = Moss, background = Paper)) {
        Scaffold(
            bottomBar = {
                NavigationBar(containerColor = Paper) {
                    tabs.forEachIndexed { index, title ->
                        NavigationBarItem(
                            selected = tab == index,
                            onClick = { tab = index },
                            label = { Text(title) },
                            icon = { Text(listOf("◉", "◌", "✦", "☼")[index]) },
                        )
                    }
                }
            }
        ) { padding ->
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(padding).padding(horizontal = 24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                item { Spacer(Modifier.height(24.dp)) }
                item { Text("时宜", fontSize = 34.sp, color = Ink, fontWeight = FontWeight.Bold) }
                item { Text(tabs[tab] + " · 生活在当下", color = Moss, fontSize = 14.sp) }
                when (tab) {
                    0 -> {
                        item { SeasonCard("立冬 · 演示主题", "让节气成为一次探索生活的邀请。") }
                        item { Text("一件刚刚好的小事", fontSize = 22.sp, color = Ink) }
                        item { Text(message, color = Ink) }
                        item {
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                Button(onClick = {
                                    message = "你选择了 5 分钟伸展（本地演示，未启动设备）。"
                                }) { Text("伸展 5 分钟") }
                                OutlinedButton(onClick = { message = "已跳过提醒，稍后再看看。" }) {
                                    Text("现在不用")
                                }
                            }
                        }
                        item { Text("模拟演示：穿戴与机器人尚未连接。", color = Moss, fontSize = 12.sp) }
                    }
                    1 -> item { SeasonCard("四时", "节气、地域与饮食文化小卡片，等待审核内容接入。") }
                    2 -> item { SeasonCard("探索", "散步、传统运动、食养与声音，找到自己的喜欢。") }
                    else -> item { SeasonCard("我的", "这里将展示授权、个人记录、反馈与设备配对。") }
                }
                item { Spacer(Modifier.height(20.dp)) }
            }
        }
    }
}

@Composable
private fun SeasonCard(title: String, detail: String) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Color(0xFFE5ECE4)),
        shape = RoundedCornerShape(24.dp)
    ) {
        Column(
            Modifier.fillMaxWidth().padding(24.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            Text(title, fontSize = 24.sp, fontWeight = FontWeight.Medium, color = Ink)
            Text(detail, color = Ink, fontSize = 15.sp)
            Text("时节有序 · 生活自在", color = Moss, fontSize = 12.sp)
        }
    }
}
