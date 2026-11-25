<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { contentsApi, eventsApi, topicsApi } from '@/api'
import ContentDrawer from '@/components/ContentDrawer.vue'
import LevelBadge from '@/components/LevelBadge.vue'
import SentimentTag from '@/components/SentimentTag.vue'
import { useEventStream } from '@/composables/useEventStream'
import type { ContentItem, ContentQuery, EventBrief, Topic } from '@/types'
import { EMOTIONS, LEVELS, MEDIA_NAME, SENTIMENTS, SOURCE_TYPES } from '@/utils/constants'
import { shortTime, splitHighlight } from '@/utils/format'

const PAGE_SIZE = 12
const route = useRoute()

const emptyFilters = (): ContentQuery => ({
  topic_id: '',
  source_type: '',
  sentiment: '',
  emotion: '',
  level: '',
  event_id: '',
  media_type: '',
  start: '',
  end: '',
  keyword: '',
  include_dup: false,
})

const filters = reactive<ContentQuery>(emptyFilters())
const page = ref(1)
const total = ref(0)
const items = ref<ContentItem[]>([])
/** 高亮用的关键词：以最后一次查询为准，避免边输入边高亮 */
const searchedKeyword = ref('')
const loading = ref(false)
const topics = ref<Topic[]>([])
const events = ref<EventBrief[]>([])
const detailId = ref<string | null>(null)

async function load() {
  loading.value = true
  try {
    const d = await contentsApi.search({ ...filters, page: page.value, page_size: PAGE_SIZE })
    items.value = d.items
    total.value = d.total
    searchedKeyword.value = (filters.keyword ?? '').trim()
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  void load()
}

function clear() {
  Object.assign(filters, emptyFilters())
  search()
}

useEventStream({
  batch_advanced: () => void load(),
  reset: () => search(),
})

onMounted(async () => {
  const q = route.query
  if (typeof q.event_id === 'string') filters.event_id = q.event_id
  if (typeof q.keyword === 'string') filters.keyword = q.keyword
  if (typeof q.cid === 'string') detailId.value = q.cid
  const [t, e] = await Promise.all([topicsApi.list(), eventsApi.list()])
  topics.value = t
  events.value = e
  await load()
})
</script>

<template>
  <div>
    <h2>
      研判工作台 <span class="muted small">共 {{ total }} 条</span>
    </h2>

    <div class="card filters">
      <el-select v-model="filters.topic_id" placeholder="全部主题" clearable>
        <el-option v-for="t in topics" :key="t.id" :label="t.name" :value="t.id" />
      </el-select>
      <el-select v-model="filters.source_type" placeholder="全部信源" clearable>
        <el-option v-for="s in SOURCE_TYPES" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="filters.sentiment" placeholder="全部情感" clearable>
        <el-option v-for="s in SENTIMENTS" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="filters.emotion" placeholder="全部情绪" clearable>
        <el-option v-for="s in EMOTIONS" :key="s" :label="s" :value="s" />
      </el-select>
      <el-select v-model="filters.level" placeholder="全部事件等级" clearable>
        <el-option v-for="l in LEVELS" :key="l" :label="l" :value="l" />
      </el-select>
      <el-select v-model="filters.event_id" placeholder="全部事件" clearable class="wide">
        <el-option v-for="e in events" :key="e.id" :label="`${e.id} ${e.title}`" :value="e.id" />
      </el-select>
      <el-select v-model="filters.media_type" placeholder="全部形态" clearable>
        <el-option v-for="(name, key) in MEDIA_NAME" :key="key" :label="name" :value="key" />
      </el-select>
      <el-date-picker
        v-model="filters.start"
        type="datetime"
        placeholder="开始时间"
        format="YYYY-MM-DD HH:mm"
        value-format="YYYY-MM-DD HH:mm"
      />
      <el-date-picker
        v-model="filters.end"
        type="datetime"
        placeholder="结束时间"
        format="YYYY-MM-DD HH:mm"
        value-format="YYYY-MM-DD HH:mm"
      />
      <el-input
        v-model="filters.keyword"
        placeholder="关键词（正文/OCR/ASR/作者）"
        clearable
        class="wide"
        @keyup.enter="search"
      />
      <el-checkbox v-model="filters.include_dup">显示被合并的水军近似帖</el-checkbox>
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="clear">清空</el-button>
    </div>

    <div v-loading="loading" class="cards">
      <div v-for="c in items" :key="c.id" class="ccard" @click="detailId = c.id">
        <div class="row meta">
          <span class="tag src">{{ c.source_type }}</span>
          {{ c.platform }} · {{ c.author }}
          <span v-if="c.kol_weight >= 9" class="tag sens">KOL 权重 {{ c.kol_weight }}</span>
          <span class="spacer" />
          {{ shortTime(c.published_at) }}
        </div>
        <div class="txt">
          <template v-for="(seg, i) in splitHighlight(c.text, searchedKeyword)" :key="i">
            <mark v-if="seg.hit">{{ seg.text }}</mark>
            <template v-else>{{ seg.text }}</template>
          </template>
        </div>
        <div class="row">
          <SentimentTag :sentiment="c.sentiment" />
          <span v-if="c.sentiment === '负向' && c.emotion" class="tag neg">{{ c.emotion }}</span>
          <span v-if="c.media_type !== 'text'" class="tag">{{ MEDIA_NAME[c.media_type] }}</span>
          <span v-for="w in c.sensitive_hits" :key="w" class="tag sens">{{ w }}</span>
          <span v-if="c.dup_count" class="tag sim">合并近似帖 {{ c.dup_count }} 条</span>
          <span v-if="c.dup_of" class="tag sim">已并入 {{ c.dup_of }}</span>
          <template v-if="c.event_id">
            <span class="spacer" />
            <LevelBadge :level="c.event_level" />
            <span class="small">{{ c.event_id }}</span>
          </template>
        </div>
        <div class="meta">{{ c.id }}｜转 {{ c.reposts }} · 评 {{ c.comments }} · 赞 {{ c.likes }}</div>
      </div>
      <p v-if="!loading && !items.length" class="empty">没有符合条件的内容</p>
    </div>

    <el-pagination
      v-if="total > PAGE_SIZE"
      v-model:current-page="page"
      class="pager"
      :page-size="PAGE_SIZE"
      :total="total"
      layout="prev, pager, next, total"
      background
      @current-change="load"
    />

    <ContentDrawer v-model="detailId" />
  </div>
</template>

<style scoped>
.filters {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.filters .el-select {
  width: 130px;
}
.filters .el-date-editor {
  width: 180px;
}
.filters .wide {
  width: 220px;
}
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 12px;
  min-height: 120px;
}
.ccard {
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  transition: box-shadow 0.15s;
}
.ccard:hover {
  box-shadow: 0 2px 10px rgb(0 0 0 / 8%);
}
.ccard .meta {
  font-size: 12px;
  color: var(--muted);
}
.ccard .txt {
  margin: 6px 0;
}
.pager {
  margin-top: 14px;
  justify-content: center;
}
</style>
