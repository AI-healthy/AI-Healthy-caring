package org.aihealthy.shiyi.integration.healthconnect

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class HealthPermissionActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    Text("时宜 · 健康数据使用说明", style = MaterialTheme.typography.headlineSmall)
                    Text("仅在你主动授权后读取指定来源的心率、静息心率、步数与睡眠时段，用于健康记录展示。")
                    Text("读取内容默认只在当前页面内存中保留。只有你主动授权服务器并点击上传，才发送给你指定的可信 HTTPS 服务。")
                    Text("可在「我的」撤回读取和服务器采集权限。撤回不等于删除历史，已上传数据可通过本人健康记录删除接口删除。")
                    Text("本版本用于受控测试，不提供诊断。")
                    Button(onClick = { finish() }) { Text("返回") }
                }
            }
        }
    }
}
