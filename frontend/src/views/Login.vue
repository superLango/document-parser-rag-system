<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { FormInstance, FormRules } from 'element-plus'
import BrandLogo from '@/components/brand/BrandLogo.vue'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  if (!formRef.value) return
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    loading.value = true
    try {
      await auth.login(form.username, form.password)
      const redirect = (route.query.redirect as string) || '/'
      router.push(redirect)
    } finally {
      loading.value = false
    }
  })
}
</script>

<template>
  <div class="login-page">
    <!-- 背景装饰：右侧抽象图谱网格 -->
    <div class="bg-decor" aria-hidden="true">
      <svg viewBox="0 0 600 600" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid slice">
        <defs>
          <pattern id="dotgrid" x="0" y="0" width="32" height="32" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="1" fill="#2563EB" fill-opacity="0.08" />
          </pattern>
        </defs>
        <rect width="600" height="600" fill="url(#dotgrid)" />
      </svg>
    </div>

    <div class="login-card">
      <!-- 品牌区 -->
      <div class="brand">
        <BrandLogo :size="56" />
        <h1 class="brand-name">Hansight</h1>
        <p class="brand-sub">文档智能解析与 RAG 系统</p>
      </div>

      <!-- 表单 -->
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        size="large"
        @keyup.enter="handleLogin"
      >
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" show-password />
        </el-form-item>
        <el-button
          type="primary"
          class="login-btn btn-glow"
          :loading="loading"
          @click="handleLogin"
        >
          登 录
        </el-button>
      </el-form>

      <div class="login-footer mono">
        <span>Hansight · v1.0.0</span>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  position: relative;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: linear-gradient(135deg, #EFF6FF 0%, #F8FAFC 50%, #F1F5F9 100%);
  overflow: hidden;
}

.bg-decor {
  position: absolute;
  inset: 0;
  pointer-events: none;
  opacity: 0.6;

  svg {
    width: 100%;
    height: 100%;
  }
}

.login-card {
  position: relative;
  width: 100%;
  max-width: 400px;
  background: var(--bg-surface);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-xl);
  padding: 40px 32px;
  box-shadow: var(--shadow-xl);
  z-index: 1;
}

.brand {
  text-align: center;
  margin-bottom: 32px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;

  .brand-name {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: var(--text-primary);
    margin: 0;
  }

  .brand-sub {
    margin: 0;
    font-size: var(--fs-sm);
    color: var(--text-secondary);
  }
}

.login-btn {
  width: 100%;
  margin-top: 8px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.login-footer {
  margin-top: 24px;
  text-align: center;
  font-size: var(--fs-xs);
  color: var(--text-muted);
}

@media (max-width: 480px) {
  .login-card {
    padding: 32px 24px;
  }
  .brand .brand-name {
    font-size: 24px;
  }
}
</style>
