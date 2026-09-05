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
                text = "情境化英语口语练习 · 课本跟读 + 情景实战 + AI 测评画像",
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
            BulletPoint("课本四模式：跟读 / 角色对话 / 影子跟读 / 自由对话，多本书隔离")
            BulletPoint("情景实战课：打基础四题型 → 任务制实战对话 → 通关复盘报告（总分 + 4 维 + 能力增量）")
            BulletPoint("AI 定制课生成：一句话需求（如「下周英文项目汇报」）生成可玩情景课")
            BulletPoint("CEFR 能力测评：约 5 分钟出 A1-C2 定级 + 四维雷达")
            BulletPoint("能力画像与轨迹：四维雷达 + 近 7/30/90 天曲线（未配置的占位分数不掺进画像）")
            BulletPoint("表达库 + 句子润色：润色金句收藏复习，任意句子「原句 vs 更地道说法」对照")
            BulletPoint("真实讯飞 ISE 逐词音素评分 + 弱词专项训练（<70 分自动入本，≥85 分毕业）")
            BulletPoint("练习统计：总练习量、平均分、连续天数、近 14 天趋势、弱课复习建议")
            BulletPoint("OTA 自动更新：GitHub Releases 发布，旧版本正常提示、可稍后再说，不强制")
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
                text = "AI：讯飞 ISE · MiMo TTS · 阿里云百炼 OpenAI 兼容接口",
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
