<script setup lang="ts">
/**
 * 内容详情抽屉：研判工作台、报告原文引用共用。
 * v-model 绑定内容 id，为 null 时关闭。
 */
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

import { contentsApi } from '@/api'
import type { ContentDetail } from '@/types'
import { shortTime } from '@/utils/format'
import LevelBadge from './LevelBadge.vue'
import SentimentTag from './SentimentTag.vue'

const cid = defineModel<string | null>({ default: null })
const props = withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })

const detail = ref<ContentDetail | null>(null)
const loading = ref(false)

const visible = computed({
  get: () => !!cid.value,
  set: (v: boolean) => {
    if (!v) cid.value = null
  },
})

watch(
  cid,
  async (id, _oldId, onCleanup) => {
    let stale = false
    onCleanup(() => { stale = true })
    detail.value = null
    if (!id) return
    loading.value = true
    try {
      const result = await contentsApi.detail(id)
      if (!stale) detail.value = result
    } catch {
      if (!stale) cid.value = null
    } finally {
      if (!stale) loading.value = false
    }
  },
  { immediate: true },
)
</script>

<template>
  <el-drawer v-model="visible" :title="detail ? `${detail.id} ${props.compact ? '原文引用' : '内容详情'}` : '内容详情'" size="480px">
    <div v-loading="loading">
      <template v-if="detail">
        <div class="row">
          <span class="tag src">{{ detail.source_type }}</span>
          {{ detail.platform }}｜{{ detail.author }}
          <template v-if="!props.compact">（{{ detail.author_type || '普通用户' }}，权重 {{ detail.kol_weight }}）</template>
        </div>
        <div class="small muted">发布时间 {{ detail.published_at }}（虚拟时间）</div>
        <p>{{ detail.text }}</p>
        <div v-if="detail.ocr_text" class="mm">
          <b>图片 OCR 识别文本</b> <span class="tag sim">模拟</span>
          <div>{{ detail.ocr_text }}</div>
        </div>
        <div v-if="detail.asr_text" class="mm">
          <b>视频 ASR 转写文本</b> <span class="tag sim">模拟</span>
          <div>{{ detail.asr_text }}</div>
        </div>

        <p v-if="props.compact">
          <RouterLink :to="{ name: 'workbench', query: { cid: detail.id } }">在研判工作台打开 →</RouterLink>
        </p>

        <template v-else>
          <table class="plain">
            <tbody>
              <tr>
                <th>情感</th>
                <td>
                  <SentimentTag :sentiment="detail.sentiment" />
                  <template v-if="detail.sentiment === '负向'">{{ detail.emotion }}</template>
                </td>
              </tr>
              <tr>
                <th>敏感词</th>
                <td>
                  <span v-for="w in detail.sensitive_hits" :key="w" class="tag sens">{{ w }}</span>
                  <template v-if="!detail.sensitive_hits.length">无</template>
                </td>
              </tr>
              <tr>
                <th>实体</th>
                <td>
                  <span v-for="e in detail.entities ?? []" :key="e.name" class="tag">{{ e.name }}·{{ e.type }}</span>
                  <template v-if="!detail.entities?.length">无</template>
                </td>
              </tr>
              <tr>
                <th>互动</th>
                <td>转 {{ detail.reposts }} · 评 {{ detail.comments }} · 赞 {{ detail.likes }}（合计 {{ detail.interaction }}）</td>
              </tr>
              <tr>
                <th>所属事件</th>
                <td>
                  <template v-if="detail.event_id">
                    <LevelBadge :level="detail.event_level" />
                    <RouterLink :to="`/events/${detail.event_id}`">{{ detail.event_title }}</RouterLink>
                  </template>
                  <template v-else>未归入事件</template>
                </td>
              </tr>
            </tbody>
          </table>

          <template v-if="detail.parent_chain.length">
            <h3 class="sub">转发链（向上追溯）</h3>
            <div v-for="(p, i) in detail.parent_chain" :key="p.id" class="mm small">
              <b>{{ '↑ '.repeat(i + 1) }}{{ p.id }}</b> {{ p.author }} · {{ p.platform }} · {{ shortTime(p.published_at) }}
              <div>{{ p.text }}</div>
            </div>
          </template>

          <p v-if="detail.dup_of" class="small">
            本帖是水军近似帖，已并入 <a @click="cid = detail.dup_of ?? null">{{ detail.dup_of }}</a>，不计入统计。
          </p>

          <template v-if="detail.merged_items.length">
            <h3 class="sub">已合并的近似帖（{{ detail.merged_items.length }} 条）</h3>
            <div v-for="m in detail.merged_items" :key="m.id" class="mm small">
              <b>{{ m.id }}</b> {{ m.author }} · {{ shortTime(m.published_at) }}
              <div>{{ m.text }}</div>
            </div>
          </template>
        </template>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.sub {
  margin-top: 14px;
}
table.plain th {
  width: 80px;
}
</style>
