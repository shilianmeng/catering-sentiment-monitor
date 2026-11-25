<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { reportsApi, type ExportFormat } from '@/api'
import ContentDrawer from '@/components/ContentDrawer.vue'
import LevelBadge from '@/components/LevelBadge.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import type { Report, ReportBrief } from '@/types'
import { saveBlob } from '@/utils/download'

const route = useRoute()
const router = useRouter()

const list = ref<ReportBrief[]>([])
const current = ref<Report | null>(null)
const loadingList = ref(false)
const loadingDetail = ref(false)
const exporting = ref<ExportFormat | ''>('')
const citeId = ref<string | null>(null)

async function open(id: number) {
  loadingDetail.value = true
  try {
    current.value = await reportsApi.detail(id)
    if (route.query.id !== String(id)) void router.replace({ query: { id: String(id) } })
  } finally {
    loadingDetail.value = false
  }
}

async function exportAs(format: ExportFormat) {
  if (!current.value) return
  exporting.value = format
  try {
    const { blob, filename } = await reportsApi.export(current.value, format)
    saveBlob(blob, filename)
  } finally {
    exporting.value = ''
  }
}

onMounted(async () => {
  loadingList.value = true
  try {
    list.value = await reportsApi.list()
  } finally {
    loadingList.value = false
  }
  const qid = Number(route.query.id)
  const first = list.value[0]
  if (Number.isInteger(qid) && qid > 0) await open(qid)
  else if (first) await open(first.id)
})
</script>

<template>
  <div>
    <h2>
      研判报告 <span class="muted small">在事件详情页点「生成研判报告」新增</span>
    </h2>

    <div class="grid g1-2">
      <div v-loading="loadingList" class="card">
        <h3>报告列表</h3>
        <div
          v-for="r in list"
          :key="r.id"
          class="item"
          :class="{ on: current?.id === r.id }"
          @click="open(r.id)"
        >
          <div class="row">
            <LevelBadge :level="r.level" />
            <b>#{{ r.id }}</b>
            <span>{{ r.title }}</span>
          </div>
          <div class="small muted">
            {{ r.created_by }} · {{ r.created_at }} ·
            <span class="tag" :class="{ pos: r.gen_mode === '模型生成' }">{{ r.gen_mode }}</span>
          </div>
        </div>
        <p v-if="!loadingList && !list.length" class="empty">还没有报告</p>
      </div>

      <div v-loading="loadingDetail" class="card">
        <template v-if="current">
          <div class="row">
            <h3 class="ttl">{{ current.title }}</h3>
            <span class="spacer" />
            <el-button :loading="exporting === 'md'" @click="exportAs('md')">导出 Markdown</el-button>
            <el-button type="primary" :loading="exporting === 'pdf'" @click="exportAs('pdf')">导出 PDF</el-button>
          </div>
          <p class="small muted">正文中的 [c001] 等编号可点击查看原文。</p>
          <MarkdownView :source="current.markdown" @cite="citeId = $event" />
        </template>
        <p v-else-if="!loadingDetail" class="empty">选择左侧报告查看</p>
      </div>
    </div>

    <ContentDrawer v-model="citeId" compact />
  </div>
</template>

<style scoped>
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
.ttl {
  margin: 0;
}
</style>
