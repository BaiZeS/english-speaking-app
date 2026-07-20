package com.app.english.ui.about

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.app.english.BuildConfig

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AboutScreen(onBack: () -> Unit, modifier: Modifier = Modifier) {
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("关于") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            AppInfoCard()
            FeatureHighlights()
            TechStackCard()
            DisclaimerCard()
        }
    }
}

@Composable
private fun AppInfoCard() {
    Card(
        modifier = Modifier.fillMaxSize(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        )
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                text = "English Assistant",
                style = MaterialTheme.typography.headlineMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )
            Text(
                text = "v${BuildConfig.VERSION_NAME}",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )
            Text(
                text = "情境化英语口语练习 · 跟读 + 对话 + AI 自由交流",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.padding(top = 6.dp)
            )
        }
    }
}

@Composable
private fun FeatureHighlights() {
    Card(modifier = Modifier.fillMaxSize()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                text = "核心功能",
                style = MaterialTheme.typography.titleMedium
            )
            BulletPoint("三模式练习：跟读 / 角色对话 / 自由对话")
            BulletPoint("真实讯飞 ISE 语音评测，逐词音素 + 总分")
            BulletPoint("AI 自由对话可选百炼 Qwen / DeepSeek 等模型")
            BulletPoint("Dashboard 统计：总练习量、平均分、连续天数、近 14 天趋势")
            BulletPoint("App 自动更新：tag 即发版，客户端无需手动下载")
        }
    }
}

@Composable
private fun TechStackCard() {
    Card(modifier = Modifier.fillMaxSize()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                text = "技术栈",
                style = MaterialTheme.typography.titleMedium
            )
            Text(
                text = "客户端：Kotlin · Jetpack Compose · Hilt · Retrofit · Room",
                style = MaterialTheme.typography.bodyMedium
            )
            Text(
                text = "后端：FastAPI · PostgreSQL · SQLAlchemy · Alembic",
                style = MaterialTheme.typography.bodyMedium
            )
            Text(
                text = "AI：讯飞 ISE / TTS · 阿里云百炼 OpenAI 兼容接口",
                style = MaterialTheme.typography.bodyMedium
            )
        }
    }
}

@Composable
private fun DisclaimerCard() {
    Card(
        modifier = Modifier.fillMaxSize(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                text = "免责声明",
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = "本应用仅供英语学习辅助，发音评分由讯飞 ISE 提供，最终评分以实际课堂或考试为准。" +
                    "对话内容由 AI 生成，请勿输入个人隐私信息。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun BulletPoint(text: String) {
    Text(
        text = "· $text",
        style = MaterialTheme.typography.bodyMedium,
        color = MaterialTheme.colorScheme.onSurface
    )
}
