<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { FormInstance, FormRules } from 'element-plus'

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
  <div class="login-page blueprint-bg">
    <div class="login-card">
      <!-- 品牌区 -->
      <div class="brand">
        <div class="brand-mark">◈</div>
        <h1 class="brand-name mono">DOC<span class="accent">.</span>INTEL</h1>
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
        <span>TECHNICAL BLUEPRINT · v1.0.0</span>
      </div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--bg-surface);
  border: 1px solid var(--border-base);
  border-radius: var(--radius-lg);
  padding: 40px 32px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.5);
}

.brand {
  text-align: center;
  margin-bottom: 32px;

  .brand-mark {
    font-size: 40px;
    color: var(--accent-primary);
    filter: drop-shadow(0 0 12px rgba(0, 217, 255, 0.6));
    margin-bottom: 12px;
  }

  .brand-name {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: var(--text-primary);

    .accent {
      color: var(--accent-primary);
    }
  }

  .brand-sub {
    margin-top: 8px;
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
</style>
