package com.app.english.ui.score

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/**
 * 一局练习的成绩聚合，**离开进程也能活**的那一份(E5)。
 *
 * 形状刻意小: 一个 JSON 文件放在 `filesDir`, 编解码在纯 Kotlin 的 [ScoreSessionCodec]
 * (JVM 单测锁往返)。三条明确不选的路:
 *
 * 1. **不建 Room 实体/DAO** —— `5556851` 刚把 `HistoryCacheDao`/`latestRecording` 当死代码
 *    删掉, 不该复活; 何况 Room 2.6.1 里移除 `@Entity` 不升 version 会让存量安装在
 *    `checkIdentity` 直接崩, 为一份缓存背这个风险不值。
 * 2. **不用 SharedPreferences** —— 一整课的 [ScoreSession] 带逐词分数, 几万字节很正常,
 *    塞进 prefs 就是让那份每次启动全量读写的 XML 跟着膨胀。
 * 3. **不从后端重建**(计划里的首选) —— 已核实不可行: 成绩页要逐词分与 LLM 建议, 而后端
 *    `history` 表每行只有 total/pronunciation/fluency/completeness 四个数, 连 roleName
 *    都没有(`backend/app/models/db.py` 的 History)。
 *
 * 内存里那一份才是权威: 读盘只在**内存还没东西**时发生一次(= 进程被杀后的首帧), 由
 * [loaded] 旗标钉住。写盘丢进 IO 作用域并用 [writeMutex] 串起来 —— 评分结束的那一刻是在
 * 主线程翻状态, 不能顺手做文件 IO; 全量覆盖写也必须互斥, 否则两个写者能把文件写成交织的
 * 半份(解码会退回 null, 而那就是"缓存静默失效")。
 */
@Singleton
class ScoreSessionStore @Inject constructor(@ApplicationContext private val context: Context) {
    private val file = File(context.filesDir, FILE_NAME)
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val writeMutex = Mutex()
    private val loaded = AtomicBoolean(false)

    @Volatile
    private var cached: ScoreSession? = null

    var session: ScoreSession?
        get() {
            if (!loaded.get()) readOnce()
            return cached
        }
        set(value) {
            cached = value
            loaded.set(true)
            scope.launch { persist(value) }
        }

    /** 开局即清: 上一局的残档不能在这一局结束后冒充"这一局的成绩"。 */
    fun clear() {
        session = null
    }

    private fun readOnce() {
        synchronized(this) {
            if (loaded.get()) return
            loaded.set(true)
            cached = runCatching {
                if (file.exists()) ScoreSessionCodec.decode(file.readText()) else null
            }.getOrNull()
        }
    }

    private suspend fun persist(value: ScoreSession?) {
        writeMutex.withLock {
            runCatching {
                if (value == null) {
                    file.delete()
                } else {
                    file.writeText(ScoreSessionCodec.encode(value))
                }
            }
        }
    }

    private companion object {
        const val FILE_NAME = "score_session.json"
    }
}
