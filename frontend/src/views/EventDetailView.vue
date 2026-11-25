<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

import { eventsApi } from '@/api'
import AlertItem from '@/components/AlertItem.vue'
import LevelBadge from '@/components/LevelBadge.vue'
import LineChart from '@/components/LineChart.vue'
import SentimentTag from '@/components/SentimentTag.vue'
import { useEventStream } from '@/composables/useEventStream'
import { useAuthStore } from '@/stores/auth'
import type { Disposal, EntityGraph, EventBrief, EventDetail, Timeline } from '@/types'
import {
  COLORS,
  ENTITY_COLOR,
  LEVELS,
  ROLE_NAME,
  STATUS_FLOW,
  TERMINAL_STATUSES,
} from '@/utils/constants'
import { formatNumber, timeOnly, truncate } from '@/utils/format'

const props = defineProps<{ id: string }>()
const router = useRouter()
const auth = useAuthStore()

const canAnalyze = computed(() => auth.hasRole('analyst', 'admin'))
const canDispose = computed(() => auth.hasRole('pr', 'admin'))

const events = ref<EventBrief[]>([])
const ev = ref<EventDetail | null>(null)
const timeline = ref<Timeline>({ nodes: [] })
const graph = ref<EntityGraph>({ nodes: [], edges: [] })
const disposals = ref<Disposal[]>([])
const loadError = ref('')
const loading = ref(false)

const levelForm = ref({ level: 'S', reason: '' })
const disposalNote = ref('')
const busy = ref<'' | 'level' | 'draft' | 'adopt' | 'report' | 'dispose'>('')

async function load() {
  loading.value = true
  try {
    const [d, tl, gr, log] = await Promise.all([
      eventsApi.detail(props.id),
      eventsApi.timeline(props.id),
      eventsApi.graph(props.id),
      eventsApi.disposals(props.id),
    ])
    ev.value = d
    timeline.value = tl
    graph.value = gr
    disposals.value = log
    loadError.value = ''
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

useEventStream({ batch_advanced: () => void load(), reset: () => void load() })

onMounted(async () => {
  void eventsApi.list().then((list) => (events.value = list))
  await load()
})

function switchEvent(id: string) {
  void router.push(`/events/${id}`)
}

/** 统一处理按钮动作：加锁、成功提示、刷新；失败提示由请求拦截器负责 */
async function run(kind: typeof busy.value, fn: () => Promise<unknown>, okMsg: string) {
  busy.value = kind
  try {
    await fn()
    ElMessage.success(okMsg)
    await load()
  } catch {
    /* 已提示 */
  } finally {
    busy.value = ''
  }
}

function submitLevel() {
  if (!levelForm.value.reason.trim()) {
    ElMessage.warning('请填写改级理由')
    return
  }
  void run(
    'level',
    () => eventsApi.changeLevel(props.id, levelForm.value.level, levelForm.value.reason.trim()),
    '等级已更新并留痕',
  ).then(() => (levelForm.value.reason = ''))
}

function dispose(to: string) {
  void run('dispose', () => eventsApi.dispose(props.id, to, disposalNote.value.trim()), `已流转到「${to}」`).then(
    () => (disposalNote.value = ''),
  )
}

async function createReport() {
  busy.value = 'report'
  try {
    const r = await eventsApi.createReport(props.id)
    ElMessage.success('报告已生成')
    await router.push({ name: 'reports', query: { id: String(r.id) } })
  } catch {
    /* 已提示 */
  } finally {
    busy.value = ''
  }
}

function openContent(cid: string | undefined) {
  if (cid) void router.push({ name: 'workbench', query: { cid } })
}

// ---------- 展示用计算属性 ----------
const scores = computed(() => {
  const e = ev.value
  if (!e) return []
  const b = e.score_basis || {}
  return [
    { name: '传播速度', v: e.score_speed, basis: b.speed },
    { name: '互动量', v: e.score_interaction, basis: b.interaction },
    { name: 'KOL 参与', v: e.score_kol, basis: b.kol },
    { name: '敏感词', v: e.score_sensitive, basis: b.sensitive },
  ]
})

const series = computed(() => {
  const s = ev.value?.series ?? []
  return {
    labels: s.map((x) => x.label),
    series: [
      { name: '新增', data: s.map((x) => x.total), color: COLORS.primary },
      { name: '负向', data: s.map((x) => x.negative), color: COLORS.neg },
    ],
  }
})

const isTerminal = computed(() => !!ev.value && TERMINAL_STATUSES.includes(ev.value.status))

const graphOption = computed<EChartsOption>(() => {
  const nodes = graph.value.nodes.slice(0, 16)
  const ids = new Set(nodes.map((n) => n.id))
  const maxC = Math.max(1, ...nodes.map((n) => n.count))
  const maxW = Math.max(1, ...graph.value.edges.map((e) => e.weight))
  const types = [...new Set(nodes.map((n) => n.type))]
  return {
    tooltip: {
      formatter: (p: unknown) => {
        const x = p as { dataType: string; data: Record<string, unknown> }
        if (x.dataType === 'edge') return `${x.data.source} — ${x.data.target}：共现 ${x.data.value} 次`
        return `${x.data.name}（${x.data.type}）出现 ${x.data.value} 次`
      },
    },
    legend: { bottom: 0, data: types },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        force: { repulsion: 260, edgeLength: [60, 160] },
        label: { show: true, position: 'bottom', fontSize: 12 },
        categories: types.map((t) => ({ name: t, itemStyle: { color: ENTITY_COLOR[t] ?? COLORS.neu } })),
        data: nodes.map((n) => ({
          name: n.id,
          value: n.count,
          type: n.type,
          category: types.indexOf(n.type),
          symbolSize: 20 + (n.count / maxC) * 32,
          contentId: n.content_ids[0],
        })),
        links: graph.value.edges
          .filter((e) => ids.has(e.source) && ids.has(e.target))
          .map((e) => ({
            source: e.source,
            target: e.target,
            value: e.weight,
            lineStyle: { width: 1 + (e.weight / maxW) * 5, color: '#b9c3d6' },
          })),
      },
    ],
  }
})

function onGraphClick(p: unknown) {
  const x = p as { dataType?: string; data?: { contentId?: string } }
  if (x.dataType === 'node') openContent(x.data?.contentId)
}
</script>

<template>
  <div v-loading="loading && !ev">
    <div class="row switch">
      <el-select :model-value="id" class="ev-select" @update:model-value="switchEvent">
        <el-option v-for="e in events" :key="e.id" :label="`${e.id} [${e.level}] ${e.title}`" :value="e.id" />
      </el-select>
      <span class="muted small">切换事件</span>
    </div>

    <el-result v-if="loadError && !ev" icon="error" :title="loadError">
      <template #extra>
        <RouterLink to="/"><el-button>返回态势大盘</el-button></RouterLink>
      </template>
    </el-result>

    <template v-if="ev">
      <div class="card">
        <div class="row">
          <LevelBadge :level="ev.level" class="big" />
          <h2 class="title">{{ ev.title }}</h2>
          <span v-if="ev.manual_override" class="tag manual">
            人工调整（自动评级 {{ ev.auto_level }} / {{ ev.auto_score }} 分）
          </span>
          <span v-if="ev.category" class="tag">{{ ev.category }}</span>
          <span class="tag">处置状态：{{ ev.status }}</span>
        </div>
        <div class="small muted head-meta">
          {{ ev.id }}｜烈度 {{ ev.intensity_score }} 分｜相关内容 {{ ev.content_count }} 条（负向
          {{ ev.negative_count }}，另合并水军近似帖 {{ ev.merged_count }} 条）｜峰值小时 {{ ev.peak_volume }} 条｜首发
          {{ ev.first_content_id || '-' }}｜关键词：{{ (ev.keywords || []).join('、') }}
        </div>
      </div>

      <div class="grid g2">
        <div class="card">
          <h3>烈度评分（四项各 0–25 分）</h3>
          <div v-for="s in scores" :key="s.name" class="score">
            <div class="row">
              <b>{{ s.name }}</b><span>{{ s.v }} / 25</span><span class="small muted">{{ s.basis }}</span>
            </div>
            <el-progress :percentage="s.v * 4" :show-text="false" :stroke-width="8" />
          </div>
          <div>
            <b>合计 {{ ev.intensity_score }} 分</b>
            <span class="small muted"> 分级线可在「监测配置」调整</span>
          </div>

          <div v-if="canAnalyze" class="block">
            <h3>人工改级</h3>
            <div class="row">
              <el-select v-model="levelForm.level" style="width: 140px">
                <el-option v-for="l in LEVELS" :key="l" :label="l" :value="l" />
                <el-option label="恢复自动评级" value="auto" />
              </el-select>
              <el-input v-model="levelForm.reason" placeholder="改级理由（必填）" class="grow" />
              <el-button type="primary" :loading="busy === 'level'" @click="submitLevel">提交</el-button>
            </div>
          </div>

          <div v-if="ev.level_adjustments.length" class="block">
            <h3>改级留痕</h3>
            <table class="plain">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>操作人</th>
                  <th>自动评级</th>
                  <th>改为</th>
                  <th>理由</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(a, i) in ev.level_adjustments" :key="i">
                  <td class="small">{{ a.created_at }}</td>
                  <td>{{ a.operator }}</td>
                  <td>{{ a.auto_level }}（{{ a.auto_score }}）</td>
                  <td>{{ a.new_level }}</td>
                  <td>{{ a.reason }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div class="card">
          <h3>声量走势（本事件各批次新增）</h3>
          <LineChart :labels="series.labels" :series="series.series" />
        </div>
      </div>

      <div class="grid g2">
        <div class="card">
          <h3>
            传播时间线 <span class="small muted">紫标＝首发，红框＝关键引爆节点，缩进＝转发层级</span>
          </h3>
          <div class="tl">
            <div
              v-for="n in timeline.nodes"
              :key="n.id"
              class="tl-node"
              :class="{
                key: n.marks.includes('KOL引爆') || n.marks.includes('互动拐点'),
                first: n.marks.includes('首发'),
              }"
              :style="{ marginLeft: `${Math.min(n.depth, 4) * 22}px` }"
              @click="openContent(n.id)"
            >
              <div class="row small">
                <b>{{ timeOnly(n.published_at) }}</b>
                <span v-for="m in n.marks" :key="m" class="tag" :class="m === '首发' ? 'manual' : 'neg'">{{ m }}</span>
                <span class="tag src">{{ n.platform }}</span>
                {{ n.author }}<template v-if="n.kol_weight >= 9">（权重 {{ n.kol_weight }}）</template>
                <span v-if="n.depth" class="muted">第 {{ n.depth }} 层转发</span>
                <span v-if="n.dup_count" class="tag sim">+{{ n.dup_count }} 近似帖</span>
                <span class="spacer" />
                <span class="muted">互动 {{ formatNumber(n.interaction) }}</span>
              </div>
              <div class="small">{{ truncate(n.text, 70) }}</div>
            </div>
            <p v-if="!timeline.nodes.length" class="empty">暂无内容</p>
          </div>
        </div>

        <div class="card">
          <h3>
            实体关系图谱 <span class="small muted">连线＝同一条内容中共现，越粗共现越多；点击节点看代表原文</span>
          </h3>
          <VChart v-if="graph.nodes.length" :option="graphOption" style="height: 440px" autoresize @click="onGraphClick" />
          <p v-else class="empty">暂无实体</p>
        </div>
      </div>

      <div class="card">
        <h3>观点聚类</h3>
        <div v-for="c in ev.clusters" :key="c.id" class="mm">
          <div class="row">
            <SentimentTag :sentiment="c.sentiment" />
            <span v-if="c.emotion" class="tag">{{ c.emotion }}</span>
            <b>{{ c.summary }}</b>
            <span class="muted small">{{ c.count }} 条</span>
          </div>
          <div v-for="q in c.quotes" :key="q.id" class="small">
            「{{ q.text }}」—— {{ q.author }}
            <RouterLink :to="{ name: 'workbench', query: { cid: q.id } }">[{{ q.id }}]</RouterLink>
          </div>
        </div>
        <p v-if="!ev.clusters.length" class="empty">暂无聚类</p>
      </div>

      <div class="grid g2">
        <div class="card">
          <h3>处置流程</h3>
          <div class="flow">
            <template v-for="(s, i) in STATUS_FLOW" :key="s">
              <span v-if="i" class="arrow">→</span>
              <span :class="{ on: s.includes(ev.status) }">{{ s }}</span>
            </template>
            <span v-if="ev.status === '忽略'" class="on">忽略</span>
            <span v-if="isTerminal" class="small muted">（流程已结束）</span>
          </div>
          <div v-if="canDispose && ev.next_statuses.length" class="row block">
            <el-input v-model="disposalNote" placeholder="处置备注（可选）" class="grow" />
            <el-button
              v-for="s in ev.next_statuses"
              :key="s"
              :type="s === '忽略' ? 'danger' : 'primary'"
              :loading="busy === 'dispose'"
              @click="dispose(s)"
            >
              流转到「{{ s }}」
            </el-button>
          </div>
          <table v-if="disposals.length" class="plain block">
            <thead>
              <tr>
                <th>时间</th>
                <th>流转</th>
                <th>操作人</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(d, i) in disposals" :key="i">
                <td class="small">{{ d.created_at }}</td>
                <td>
                  {{ d.from_status }} → <b>{{ d.to_status }}</b>
                </td>
                <td>{{ d.operator }}（{{ ROLE_NAME[d.role as keyof typeof ROLE_NAME] ?? d.role }}）</td>
                <td>{{ d.note }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="empty small">暂无处置记录</p>
        </div>

        <div class="card">
          <h3>
            回应话术草案
            <span class="small muted">
              {{ ev.llm_available ? '（已配置大模型，失败时自动降级为模板）' : '（未配置大模型，使用模板生成）' }}
            </span>
          </h3>
          <div class="row">
            <el-button
              type="primary"
              :loading="busy === 'draft'"
              @click="run('draft', () => eventsApi.generateDraft(id), '草案已生成')"
            >
              生成草案
            </el-button>
            <el-button
              v-if="canDispose"
              :loading="busy === 'adopt'"
              @click="run('adopt', () => eventsApi.adoptDraft(id), '已采纳最新草案')"
            >
              采纳最新草案
            </el-button>
            <el-button v-if="canAnalyze" :loading="busy === 'report'" @click="createReport">生成研判报告</el-button>
          </div>
          <div v-for="d in ev.drafts" :key="d.id" class="mm">
            <div class="row small">
              <span class="tag" :class="{ pos: d.gen_mode === '模型生成' }">{{ d.gen_mode }}</span>
              <span v-if="d.model_name">{{ d.model_name }}</span>
              <span class="muted">{{ d.created_by }} · {{ d.created_at }}</span>
              <span v-if="d.adopted" class="tag manual">已采纳（{{ d.adopted_by }}）</span>
              <span class="spacer" />
              <el-button
                v-if="canDispose"
                size="small"
                @click="run('adopt', () => eventsApi.adoptDraft(id, d.id), '已采纳')"
              >
                采纳此稿
              </el-button>
            </div>
            <div class="pre">{{ d.content }}</div>
          </div>
          <p v-if="!ev.drafts.length" class="empty">还没有草案</p>
        </div>
      </div>

      <div class="card">
        <h3>本事件预警记录</h3>
        <AlertItem v-for="a in ev.alerts" :key="a.id" :alert="a" />
        <p v-if="!ev.alerts.length" class="empty">本事件暂无预警</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.switch {
  margin-bottom: 10px;
}
.ev-select {
  width: 420px;
}
.title {
  margin: 0;
}
.big {
  font-size: 20px;
  line-height: 28px;
}
.head-meta {
  margin-top: 6px;
}
.score {
  margin-bottom: 8px;
}
.block {
  margin-top: 12px;
}
.grow {
  flex: 1;
  min-width: 180px;
}
.tl {
  max-height: 520px;
  overflow: auto;
}
.tl-node {
  border-left: 3px solid #c9d3e6;
  padding: 4px 8px;
  margin-bottom: 6px;
  cursor: pointer;
  border-radius: 4px;
}
.tl-node:hover {
  background: #f5f8fe;
}
.tl-node.first {
  border-left-color: #6c3fc5;
}
.tl-node.key {
  outline: 1.5px solid var(--neg);
  background: #fff8f7;
}
.flow span.on {
  background: var(--primary);
  color: #fff;
  border-radius: 10px;
  padding: 1px 8px;
}
.flow .arrow {
  margin: 0 4px;
  color: var(--muted);
}
.pre {
  white-space: pre-wrap;
}
</style>
