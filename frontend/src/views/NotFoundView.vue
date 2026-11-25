<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="nf">
    <el-result icon="warning" title="404" sub-title="页面不存在">
      <template #extra>
        <RouterLink to="/"><el-button type="primary">返回态势大盘</el-button></RouterLink>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.nf {
  padding-top: 12vh;
}
</style>
