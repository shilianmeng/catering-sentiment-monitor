<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import type { FormInstance, FormRules } from 'element-plus'

import { useAuthStore } from '@/stores/auth'
import { APP_TITLE } from '@/utils/constants'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const formRef = ref<FormInstance>()
const form = reactive({ username: '', password: '' })
const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}
const loading = ref(false)
const error = ref('')

const DEMO_ACCOUNTS = [
  { username: 'analyst', role: '分析师', can: '维护主题词包、人工改级、生成报告' },
  { username: 'pr', role: '公关', can: '处置流转、生成并采纳话术草案' },
  { username: 'admin', role: '管理员', can: '全部功能，含预警阈值与通知渠道' },
]

function fill(username: string) {
  form.username = username
  form.password = '123456'
}

async function onSubmit() {
  if (!(await formRef.value?.validate().catch(() => false))) return
  loading.value = true
  error.value = ''
  try {
    await auth.login(form.username, form.password)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect.startsWith('/') ? redirect : '/')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-wrap">
    <div class="card">
      <h2>{{ APP_TITLE }}平台</h2>
      <p class="muted small">演示数据均为模拟数据，「香满园」是虚构的演示品牌。</p>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" autocomplete="username" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            autocomplete="current-password"
            show-password
          />
        </el-form-item>
        <el-button type="primary" native-type="submit" :loading="loading" class="full">登 录</el-button>
        <p v-if="error" class="err small">{{ error }}</p>
      </el-form>
    </div>
    <div class="card small">
      <b>演示账号</b>（密码统一 <code>123456</code>，点击快速填入）
      <table class="plain">
        <thead>
          <tr>
            <th>账号</th>
            <th>角色</th>
            <th>能做什么</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in DEMO_ACCOUNTS" :key="a.username">
            <td><a @click="fill(a.username)">{{ a.username }}</a></td>
            <td>{{ a.role }}</td>
            <td>{{ a.can }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  max-width: 420px;
  margin: 10vh auto 0;
  padding: 0 16px;
}
.full {
  width: 100%;
}
.err {
  color: var(--neg);
  margin: 8px 0 0;
}
</style>
