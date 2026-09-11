package com.app.english.ui.scenes

import com.app.english.domain.model.ContinueSession
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「这场练完了, 报告在哪儿」的入口锁(§P6 客户端 9)。
 *
 * 修之前的事实不是"入口难找", 是**没有入口**:`SceneDetailViewModel.startLearning()` 与
 * `HomeViewModel` 都只查 `status = "active"`, 所以一场已收工的会话在客户端根本不存在 →
 * `resuming == null` → 唯一的按钮 `create()` 开一局全新的课。想看刚才那份总评, 点下去
 * 得到的恰好是把那份报告丢掉的动作。
 */
class ReviewEntryPolicyTest {
    private fun session(
        id: String,
        scene: String = "scene_ordering_coffee",
        status: String = "completed",
        stage: String = "review"
    ) = ContinueSession(
        sessionId = id,
        sceneId = scene,
        title = "咖啡店点单",
        level = "A2",
        stage = stage,
        doneSteps = 6,
        totalSteps = 6,
        unlockedMission = true,
        status = status
    )

    @Test
    fun aFinishedSessionIsWhatMakesTheEntryAppear() {
        assertFalse(ReviewEntryPolicy.showReviewEntry(hasCompletedSession = false))
        assertTrue(ReviewEntryPolicy.showReviewEntry(hasCompletedSession = true))
    }

    /**
     * 还没打完就出现"看上次复盘"是另一副空壳: 复盘页要么没有 `review`, 要么是一个还没
     * 落定的旧场。只有 `status == "completed"` 才算"有报告可看"。
     */
    @Test
    fun onlyACompletedSessionHasAReportToLookAt() {
        for (status in listOf("active", "abandoned", "", "Completed", "COMPLETED")) {
            assertNull(
                "status=$status",
                ReviewEntryPolicy.latestCompletedSession(listOf(session("s1", status = status)))
            )
        }
        assertEquals(
            "s1",
            ReviewEntryPolicy.latestCompletedSession(listOf(session("s1")))?.sessionId
        )
    }

    /**
     * 详情页必须按**这一课**收窄。`GET /sessions?status=completed` 是设备级的最近若干场,
     * 不带 sceneId 过滤就会把"另一课的复盘"挂在这门课下面 —— 那条入口写的是"上次复盘",
     * 学员只会以为这门课自己练过而且练完了。
     */
    @Test
    fun theSceneScopedLookupSkipsOtherScenes() {
        val rows = listOf(session("other", scene = "scene_project_report"), session("mine"))
        val mine = ReviewEntryPolicy.latestCompletedSession(rows, sceneId = "scene_ordering_coffee")
        assertEquals("mine", mine?.sessionId)
        assertNull(ReviewEntryPolicy.latestCompletedSession(rows, sceneId = "scene_nope"))
    }

    /** 首页那张卡不分场景: 服务端按 `last_active_at` 倒序, 所以第一条命中就是最近一场。 */
    @Test
    fun theHomeEntryIsSceneAgnosticAndPicksTheMostRecent() {
        val rows = listOf(session("older", scene = "a"), session("newest", scene = "b"))
        assertEquals("older", ReviewEntryPolicy.latestCompletedSession(rows)?.sessionId)
        // 前面的条目还没打完时, 往后找第一个真正打完的: 回看入口不能被一条 active 会话挡住。
        val mixed = listOf(session("a1", status = "active"), session("b2"), session("c3"))
        assertEquals("b2", ReviewEntryPolicy.latestCompletedSession(mixed)?.sessionId)
        assertNull(ReviewEntryPolicy.latestCompletedSession(emptyList()))
    }

    /** 空白 sessionId(脏摘要)直接跳过, 否则点出一个 `scene_review/` 的空路由。 */
    @Test
    fun anUnusableRowIsSkipped() {
        assertNull(ReviewEntryPolicy.latestCompletedSession(listOf(session("  "))))
        assertNull(ReviewEntryPolicy.latestCompletedSession(listOf(session(""))))
    }

    @Test
    fun viewingTheLastReportIsNeverTheSameWordsAsStartingANewOne() {
        // 三档主按钮标签都在说"进去练"; 回看入口用的是另一个词根, 永不混进那颗键。
        assertEquals(
            "继续学习",
            ReviewEntryPolicy.startLabelOf(hasActiveSession = true, hasCompletedSession = true)
        )
        assertEquals(
            "再练一次（新开一局）",
            ReviewEntryPolicy.startLabelOf(hasActiveSession = false, hasCompletedSession = true)
        )
        assertEquals(
            "开始学习",
            ReviewEntryPolicy.startLabelOf(hasActiveSession = false, hasCompletedSession = false)
        )
        // 「新开一局」那半句是刻意的: 有旧报告可看时, 主按钮**仍然**会 create 一条全新会话,
        // 学员必须能从标签就看出这一点, 否则他会以为点它是去收尾工(即本项要修的那个误解)。
        assertTrue(ReviewEntryPolicy.startLabelOf(false, true).contains("新开一局"))
        assertFalse(ReviewEntryPolicy.LABEL_VIEW_LAST_REVIEW.contains("练"))
        assertFalse(ReviewEntryPolicy.LABEL_RECENT_REVIEW.contains("练"))
    }

    /**
     * 有 active 会话时**也**保留回看入口: 那条入口指向的是更早一场的报告。为了"两个按钮
     * 看起来都在说上次"而把它藏起来, 只会让人以为旧报告随新开一局丢了。
     */
    @Test
    fun anActiveSessionDoesNotHideTheOldReport() {
        val rows = listOf(session("running", status = "active"), session("done"))
        val completed = ReviewEntryPolicy.latestCompletedSession(rows)
        assertEquals("done", completed?.sessionId)
        assertTrue(ReviewEntryPolicy.showReviewEntry(completed != null))
    }
}
