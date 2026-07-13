<script setup lang="ts">
import { useRouter } from 'vue-router'

const router = useRouter()
</script>

<template>
  <div class="not-found blueprint-bg">
    <div class="nf-content">
      <div class="nf-code mono">404</div>
      <h2 class="nf-title">页面未找到</h2>
      <p class="nf-desc">请求的路径不存在或已被移除</p>
      <el-button type="primary" class="btn-glow" @click="router.push('/')">
        返回仪表盘
      </el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.not-found {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

.nf-content {
  text-align: center;
}

.nf-code {
  font-size: 96px;
  font-weight: 700;
  color: var(--accent-primary);
  filter: drop-shadow(0 0 24px rgba(0, 217, 255, 0.4));
  line-height: 1;
}

.nf-title {
  font-size: var(--fs-xl);
  margin: 16px 0 8px;
  color: var(--text-primary);
}

.nf-desc {
  color: var(--text-secondary);
  margin-bottom: 24px;
}
</style>
