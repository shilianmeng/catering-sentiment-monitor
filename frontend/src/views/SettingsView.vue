<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

import { configApi, topicsApi, type ConfigPayload } from '@/api'
import { useAuthStore } from '@/stores/auth'
import type { MonitorConfig, Topic, TopicPayload } from '@/types'
import { SOURCE_TYPES } from '@/utils/constants'

const auth = useAuthStore()
const canEditTopics = computed(() => auth.hasRole('analyst', 'admin'))
const isAdmin = computed(() => auth.hasRole('admin'))

// ---------- 主题词包 ----------
const topics = ref<Topic[]>([])
const topicsLoading = ref(false)
const dialogOpen = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const formRef = ref<FormInstance>()

const allChannels = () => Object.fromEntries(SOURCE_TYPES.map((s) => [s, true])) as Record<string, boolean>
const topicForm = reactive<TopicPayload>({ name: '', keywords: '', channels: allChannels(), enabled: true })
const topicRules: FormRules = {
  name: [{ required: true, message: '请输入主题名称', trigger: 'blur' }],
  keywords: [{ required: true, message: '请至少填写一个关键词', trigger: 'blur' }],
}

async function loadTopics() {
  topicsLoading.value = true
  try {
    topics.value = await topicsApi.list()
  } finally {
    topicsLoading.value = false
  }
}

function openTopic(t?: Topic) {
  editingId.value = t?.id ?? null
  Object.assign(topicForm, {
    name: t?.name ?? '',
    keywords: t ? t.keywords.join('，') : '',
    channels: t ? { ...allChannels(), ...t.channels } : allChannels(),
    enabled: t ? !!t.enabled : true,
  })
  dialogOpen.value = true
  formRef.value?.clearValidate()
}

async function saveTopic() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  saving.value = true
  try {
    const body = { ...topicForm, name: topicForm.name.trim() }
    if (editingId.value === null) await topicsApi.create(body)
    else await topicsApi.update(editingId.value, body)
    ElMessage.success('已保存')
    dialogOpen.value = false
    await loadTopics()
  } catch {
    /* 已提示 */
  } finally {
    saving.value = false
  }
}

async function removeTopic(t: Topic) {
  try {
    await ElMessageBox.confirm(`确定删除主题「${t.name}」？`, '删除主题', { type: 'warning' })
  } catch {
    return
  }
  try {
    await topicsApi.remove(t.id)
    ElMessage.success('已删除')
    await loadTopics()
  } catch {
    /* 已提示（主题下仍有内容时后端返回 409） */
  }
}

function channelText(t: Topic) {
  return SOURCE_TYPES.filter((s) => t.channels[s] !== false).join('、') || '无'
}

// ---------- 预警阈值与通知 ----------
const config = ref<MonitorConfig | null>(null)
const cfgForm = reactive<Required<ConfigPayload>>({
  surge_threshold: 0,
  surge_min_count: 0,
  kol_alert_weight: 0,
  silence_minutes: 0,
  level_s: 0,
  level_a: 0,
  level_b: 0,
  notify_site: true,
  notify_email: false,
  notify_sms: false,
})
const cfgSaving = ref(false)

type NumberKey = 'surge_threshold' | 'surge_min_count' | 'kol_alert_weight' | 'silence_minutes' | 'level_s' | 'level_a' | 'level_b'
const NUMBER_FIELDS: { key: NumberKey; label: string; min: number; max: number }[] = [
  { key: 'surge_threshold', label: '声量激增阈值（单小时负向声量环比增幅 %）', min: 1, max: 10000 },
  { key: 'surge_min_count', label: '激增最小条数（本小时负向条数不少于）', min: 1, max: 1000 },
  { key: 'kol_alert_weight', label: 'KOL 发声预警的账号权重下限（≥）', min: 1, max: 10 },
  { key: 'silence_minutes', label: '同事件静默期（虚拟分钟；等级升级不受静默限制）', min: 0, max: 1440 },
  { key: 'level_s', label: 'S 级分数线（≥）', min: 1, max: 100 },
  { key: 'level_a', label: 'A 级分数线（≥）', min: 1, max: 100 },
  { key: 'level_b', label: 'B 级分数线（≥）', min: 1, max: 100 },
]
const SWITCH_FIELDS: { key: 'notify_site' | 'notify_email' | 'notify_sms'; label: string }[] = [
  { key: 'notify_site', label: '站内通知' },
  { key: 'notify_email', label: '邮件通知（模拟）' },
  { key: 'notify_sms', label: '短信通知（模拟）' },
]

function fillConfig(c: MonitorConfig) {
  config.value = c
  for (const k of Object.keys(cfgForm) as (keyof typeof cfgForm)[]) {
    ;(cfgForm as Record<string, unknown>)[k] = c[k]
  }
}

async function saveConfig() {
  if (!(cfgForm.level_s > cfgForm.level_a && cfgForm.level_a > cfgForm.level_b)) {
    ElMessage.warning('分数线需满足 S > A > B')
    return
  }
  cfgSaving.value = true
  try {
    fillConfig(await configApi.update({ ...cfgForm }))
    ElMessage.success('配置已保存，事件等级已按新分数线重算')
  } catch {
    /* 已提示 */
  } finally {
    cfgSaving.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadTopics(), configApi.get().then(fillConfig)])
})
</script>

<template>
  <div>
    <h2>监测配置</h2>

    <div class="card">
      <div class="row">
        <h3 class="ttl">主题词包</h3>
        <span class="spacer" />
        <el-button v-if="canEditTopics" type="primary" @click="openTopic()">新增主题</el-button>
      </div>
      <p v-if="!canEditTopics" class="small muted">当前角色只读；主题词包由分析师或管理员维护。</p>
      <el-table v-loading="topicsLoading" :data="topics" class="block">
        <el-table-column prop="name" label="主题" width="160" />
        <el-table-column label="关键词">
          <template #default="{ row }">{{ (row as Topic).keywords.join('、') }}</template>
        </el-table-column>
        <el-table-column label="监测渠道" width="260">
          <template #default="{ row }">{{ channelText(row as Topic) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <span class="tag" :class="(row as Topic).enabled ? 'pos' : ''">
              {{ (row as Topic).enabled ? '启用' : '停用' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="content_count" label="内容数" width="90" />
        <el-table-column v-if="canEditTopics" label="操作" width="150">
          <template #default="{ row }">
            <el-button link type="primary" @click="openTopic(row as Topic)">编辑</el-button>
            <el-button link type="danger" @click="removeTopic(row as Topic)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div v-if="config" class="card">
      <h3>预警阈值与通知渠道</h3>
      <p class="small muted">
        {{ isAdmin ? '' : '仅管理员可修改。' }}大模型：{{
          config.llm_available ? `已配置（${config.llm_model}）` : '未配置，草案与报告使用模板生成'
        }}
      </p>
      <el-form label-width="380px" :disabled="!isAdmin" class="cfg">
        <el-form-item v-for="f in NUMBER_FIELDS" :key="f.key" :label="f.label">
          <el-input-number v-model="cfgForm[f.key]" :min="f.min" :max="f.max" />
        </el-form-item>
        <el-form-item v-for="f in SWITCH_FIELDS" :key="f.key" :label="f.label">
          <el-switch v-model="cfgForm[f.key]" />
        </el-form-item>
        <el-form-item v-if="isAdmin">
          <el-button type="primary" :loading="cfgSaving" @click="saveConfig">保存配置</el-button>
          <span class="small muted note">修改等级分数线后会立即按新分数线重算所有事件等级（人工改过的除外）</span>
        </el-form-item>
      </el-form>
    </div>

    <el-dialog v-model="dialogOpen" :title="editingId === null ? '新增主题' : '编辑主题'" width="520px">
      <el-form ref="formRef" :model="topicForm" :rules="topicRules" label-width="90px">
        <el-form-item label="主题名称" prop="name">
          <el-input v-model="topicForm.name" maxlength="50" />
        </el-form-item>
        <el-form-item label="关键词" prop="keywords">
          <el-input v-model="topicForm.keywords" type="textarea" :rows="3" placeholder="多个关键词用逗号分隔" />
        </el-form-item>
        <el-form-item label="监测渠道">
          <el-checkbox v-for="s in SOURCE_TYPES" :key="s" v-model="topicForm.channels[s]">{{ s }}</el-checkbox>
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="topicForm.enabled" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogOpen = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveTopic">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ttl {
  margin: 0;
}
.block {
  margin-top: 10px;
}
.cfg {
  max-width: 760px;
}
.note {
  margin-left: 12px;
}
</style>
