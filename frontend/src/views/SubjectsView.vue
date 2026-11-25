<script setup lang="ts">
/**
 * 主体风险（第③④步）：区域画像 → 主体排名（可切食品安全视图）→ 主体体检报告 → 导出 PDF。
 * 数据来自越秀区双公示的真实行政处罚，按统一社会信用代码归并到营业执照主体。
 * 评估日期默认固定在 SUBJECT_DEMO_AS_OF，保证演示数字可复现；URL 带 as_of / cat / key，刷新不丢。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { subjectsApi } from '@/api'
import type {
  DistrictProfile,
  HealthReport,
  SubjectLevel,
  SubjectRanking,
} from '@/api/modules/subjects'
import MarkdownView from '@/components/MarkdownView.vue'
import { saveBlob } from '@/utils/download'
import { SUBJECT_DEMO_AS_OF, SUBJECT_FOOD_CATEGORY } from '@/utils/constants'

const route = useRoute()
const router = useRouter()

const asOf = ref(String(route.query.as_of || SUBJECT_DEMO_AS_OF))
const category = ref(String(route.query.cat || ''))
const selected = ref(String(route.query.key || ''))

const profile = ref<DistrictProfile | null>(null)
const ranking = ref<SubjectRanking | null>(null)
const report = ref<HealthReport | null>(null)
const loadingProfile = ref(false)
const loadingRanking = ref(false)
const loadingReport = ref(false)
const exporting = ref(false)

const LEVEL_ORDER: SubjectLevel[] = ['高', '中', '低']

const money = (n: number | null | undefined) =>
  `¥${(n ?? 0).toLocaleString('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`

const categoryRows = computed(() => {
  const p = profile.value
  if (!p) return []
  const rows = Object.entries(p.by_category).map(([name, v]) => ({ name, ...v }))
  const max = Math.max(1, ...rows.map((r) => r.records))
  return rows
    .sort((a, b) => b.records - a.records)
    .map((r) => ({ ...r, pct: (r.records / max) * 100 }))
})

const yearRows = computed(() =>
  profile.value ? Object.entries(profile.value.by_year).sort(([a], [b]) => a.localeCompare(b)) : [],
)

function syncQuery() {
  const query: Record<string, string> = {}
  if (asOf.value !== SUBJECT_DEMO_AS_OF) query.as_of = asOf.value
  if (category.value) query.cat = category.value
  if (selected.value) query.key = selected.value
  void router.replace({ query })
}

/*
 * 快速切换主体 / 日期 / 视图时，先发的请求可能后回来。每类请求带一个递增序号，
 * 只有最新一次的结果（或失败）才写回页面；过期的直接丢弃。失败时清空旧数据并显示错误，
 * 不让上一次的报告冒充当前选择。
 */
let profileSeq = 0
let rankingSeq = 0
let reportSeq = 0
const profileError = ref('')
const rankingError = ref('')
const reportError = ref('')

const errText = (e: unknown) => (e instanceof Error && e.message ? e.message : '请求失败')

async function loadProfile() {
  const seq = ++profileSeq
  loadingProfile.value = true
  profileError.value = ''
  try {
    const data = await subjectsApi.profile(asOf.value)
    if (seq === profileSeq) profile.value = data
  } catch (e) {
    if (seq === profileSeq) {
      profile.value = null
      profileError.value = errText(e)
    }
  } finally {
    if (seq === profileSeq) loadingProfile.value = false
  }
}

async function loadRanking() {
  const seq = ++rankingSeq
  loadingRanking.value = true
  rankingError.value = ''
  try {
    const data = await subjectsApi.ranking(asOf.value, category.value)
    if (seq === rankingSeq) ranking.value = data
  } catch (e) {
    if (seq === rankingSeq) {
      ranking.value = null
      rankingError.value = errText(e)
    }
  } finally {
    if (seq === rankingSeq) loadingRanking.value = false
  }
}

async function loadReport() {
  const seq = ++reportSeq
  // 发请求前就清掉旧报告：加载中和失败时都不会显示、导出上一个主体
  report.value = null
  reportError.value = ''
  if (!selected.value) {
    loadingReport.value = false
    return
  }
  loadingReport.value = true
  try {
    const data = await subjectsApi.report(selected.value, asOf.value)
    if (seq === reportSeq) report.value = data
  } catch (e) {
    if (seq === reportSeq) reportError.value = errText(e)
  } finally {
    if (seq === reportSeq) loadingReport.value = false
  }
}

/** 只有当前显示的报告正好对应左侧选中的主体和日期框里的日期，才允许导出 */
const canExport = computed(
  () =>
    !!report.value &&
    !loadingReport.value &&
    report.value.subject_key === selected.value &&
    report.value.as_of === asOf.value,
)

function pick(key: string) {
  selected.value = key
  syncQuery()
  void loadReport()
}

async function exportPdf() {
  const r = report.value
  if (!r || !canExport.value || exporting.value) return
  exporting.value = true
  try {
    // 用屏幕上这份报告自己的主体和日期导出，PDF 与页面一定是同一份
    const { blob, filename } = await subjectsApi.exportPdf(r.subject_key, r.as_of)
    saveBlob(blob, filename)
  } catch {
    // 错误提示已由 http 拦截器弹出
  } finally {
    exporting.value = false
  }
}

watch(asOf, () => {
  syncQuery()
  void Promise.all([loadProfile(), loadRanking(), loadReport()])
})
watch(category, () => {
  syncQuery()
  void loadRanking()
})

onMounted(async () => {
  await Promise.all([loadProfile(), loadRanking()])
  if (!selected.value && ranking.value?.subjects[0])
    selected.value = ranking.value.subjects[0].subject_key
  await loadReport()
})
</script>

<template>
  <div>
    <div class="row head">
      <h2>主体风险</h2>
      <span class="muted small"
        >越秀区双公示 · 真实行政处罚 · 按统一社会信用代码归并到营业执照主体</span
      >
      <span class="spacer" />
      <span class="small muted">数据截止</span>
      <b class="small">{{ profile?.data_until || '-' }}</b>
      <span class="small muted sep">评估日期</span>
      <el-date-picker
        v-model="asOf"
        type="date"
        value-format="YYYY-MM-DD"
        :clearable="false"
        size="small"
        style="width: 140px"
      />
      <el-button
        v-if="asOf !== SUBJECT_DEMO_AS_OF"
        size="small"
        link
        @click="asOf = SUBJECT_DEMO_AS_OF"
      >
        回到演示口径
      </el-button>
    </div>
    <p class="small muted note">
      分数按处罚距评估日期的时间衰减；演示固定评估日期 {{ SUBJECT_DEMO_AS_OF }}，数字可复现。
    </p>

    <!-- ① 区域画像 -->
    <div v-loading="loadingProfile" class="card">
      <h3>区域画像</h3>
      <div v-if="profileError" class="empty err">
        区域画像加载失败：{{ profileError }}
        <el-button size="small" link @click="loadProfile">重试</el-button>
      </div>
      <div v-if="profile" class="grid g4 stats">
        <div>
          <div class="muted small">处罚记录</div>
          <div class="num">{{ profile.record_count }}</div>
        </div>
        <div>
          <div class="muted small">涉及主体</div>
          <div class="num">{{ profile.subject_count }}</div>
        </div>
        <div>
          <div class="muted small">罚款合计（{{ profile.fined_count }} 条有罚款）</div>
          <div class="num">{{ money(profile.fine_total) }}</div>
        </div>
        <div>
          <div class="muted small">风险等级</div>
          <div class="levels">
            <span v-for="lv in LEVEL_ORDER" :key="lv" class="slv" :class="`slv-${lv}`">
              {{ lv }} {{ profile.levels[lv] ?? 0 }}
            </span>
          </div>
        </div>
      </div>
      <div v-if="profile" class="grid g2 split">
        <div>
          <div class="muted small sub">违法类别（条数 · 罚款）</div>
          <div v-for="c in categoryRows" :key="c.name" class="bar-row">
            <span class="bar-name">{{ c.name }}</span>
            <span class="bar"><i :style="{ width: c.pct + '%' }" /></span>
            <span class="small">{{ c.records }} · {{ money(c.fine_total) }}</span>
          </div>
        </div>
        <div>
          <div class="muted small sub">按年份</div>
          <table class="plain">
            <thead>
              <tr>
                <th>年份</th>
                <th>条数</th>
                <th>罚款</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="[y, v] in yearRows" :key="y">
                <td>{{ y }}</td>
                <td>{{ v.records }}</td>
                <td>{{ money(v.fine_total) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div class="grid g1-2 main">
      <!-- ② 主体排名 -->
      <div v-loading="loadingRanking" class="card">
        <div class="row">
          <h3 class="ttl">主体排名</h3>
          <span class="spacer" />
          <el-radio-group v-model="category" size="small">
            <el-radio-button value="">综合</el-radio-button>
            <el-radio-button :value="SUBJECT_FOOD_CATEGORY">只看食品安全</el-radio-button>
          </el-radio-group>
        </div>
        <p class="small muted">
          共 {{ ranking?.total ?? 0 }} 个主体，显示前 {{ ranking?.subjects.length ?? 0 }} 名
        </p>
        <div
          v-for="s in ranking?.subjects"
          :key="s.subject_key"
          class="item"
          :class="{ on: selected === s.subject_key }"
          @click="pick(s.subject_key)"
        >
          <div class="row">
            <b class="rk">{{ s.rank }}</b>
            <span class="slv" :class="`slv-${s.level}`">{{ s.level }}</span>
            <span class="name">{{ s.subject }}</span>
            <span class="spacer" />
            <b>{{ s.score }}</b
            ><span class="small muted">分</span>
          </div>
          <div class="small muted">
            {{ s.record_count }} 次处罚 · 罚款 {{ money(s.fine_total) }} · 最近 {{ s.last_at }} ·
            {{ Object.keys(s.categories).join('、') }}
          </div>
        </div>
        <div v-if="rankingError" class="empty err">
          排名加载失败：{{ rankingError }}
          <el-button size="small" link @click="loadRanking">重试</el-button>
        </div>
        <p v-else-if="!loadingRanking && !ranking?.subjects.length" class="empty">
          没有符合条件的主体
        </p>
      </div>

      <!-- ③ 主体体检报告 -->
      <div v-loading="loadingReport" class="card">
        <template v-if="report">
          <div class="row">
            <h3 class="ttl">{{ report.title }}</h3>
            <span class="spacer" />
            <el-button
              type="primary"
              :loading="exporting"
              :disabled="!canExport"
              @click="exportPdf"
              >导出 PDF 体检报告</el-button
            >
          </div>
          <p class="small muted">
            信用代码 {{ report.subject_key }} · 评估日期 {{ report.as_of }} ·
            <span class="slv" :class="`slv-${report.level}`">{{ report.level }}</span>
            {{ report.score }} 分
          </p>
          <div v-for="sec in report.sections" :key="sec.title" class="sec">
            <h4>{{ sec.title }}</h4>
            <MarkdownView :source="sec.body" />
          </div>
        </template>
        <div v-else-if="reportError" class="empty err">
          报告加载失败：{{ reportError }}
          <el-button size="small" link @click="loadReport">重试</el-button>
        </div>
        <p v-else-if="!loadingReport" class="empty">点左侧主体查看体检报告</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.head h2 {
  margin: 0;
}
.head {
  flex-wrap: wrap;
}
.sep {
  margin-left: 8px;
}
.note {
  margin: 4px 0 12px;
}
.stats .num {
  font-size: 22px;
  font-weight: bold;
  margin-top: 2px;
}
.levels {
  display: flex;
  gap: 6px;
  margin-top: 6px;
}
.split {
  margin-top: 16px;
}
.sub {
  margin-bottom: 6px;
}
.bar-row {
  display: grid;
  grid-template-columns: 110px 1fr 150px;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}
.bar-name {
  font-size: 13px;
}
.bar {
  height: 10px;
  background: #eef2f8;
  border-radius: 5px;
  overflow: hidden;
}
.bar i {
  display: block;
  height: 100%;
  background: var(--primary);
}
.main {
  margin-top: 16px;
}
.ttl {
  margin: 0;
}
.item {
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  border-bottom: 1px solid var(--line);
}
.item:hover {
  background: #f5f8fe;
}
.item.on {
  background: #eaf1ff;
}
.rk {
  width: 22px;
  text-align: right;
}
.name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.slv {
  display: inline-block;
  color: #fff;
  border-radius: 4px;
  padding: 0 6px;
  line-height: 20px;
  font-size: 12px;
  font-weight: bold;
}
.slv-高 {
  background: var(--lv-s);
}
.slv-中 {
  background: var(--lv-a);
}
.slv-低 {
  background: var(--lv-c);
}
.slv-无 {
  background: var(--neu);
}
.err {
  color: var(--lv-s);
}
.sec h4 {
  margin: 14px 0 4px;
}
</style>
