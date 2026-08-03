<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { toast } from '@/components/ui/toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Loader2, FileSearch } from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const loading = ref(false)
const form = reactive({
  username: '',
  password: '',
})

async function handleLogin() {
  if (!form.username || !form.password) {
    toast.warning('请填写完整', '用户名和密码不能为空')
    return
  }
  loading.value = true
  try {
    await auth.login(form.username, form.password)
    toast.success('登录成功', `欢迎回来，${form.username}`)
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch (e) {
    // 错误已由 axios 拦截器统一 toast
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div
    class="relative flex min-h-dvh items-center justify-center overflow-hidden bg-background p-6"
  >
    <!-- 背景装饰：极简点阵网格 -->
    <div
      class="pointer-events-none absolute inset-0 opacity-50"
      style="
        background-image: radial-gradient(
          circle at 1px 1px,
          oklch(0.71 0.01 260 / 0.18) 1px,
          transparent 0
        );
        background-size: 28px 28px;
      "
      aria-hidden="true"
    />

    <Card class="relative w-full max-w-sm">
      <CardHeader class="items-center text-center">
        <div
          class="mb-2 flex size-12 items-center justify-center rounded-lg bg-primary text-primary-foreground"
        >
          <FileSearch class="size-6" :stroke-width="1.5" />
        </div>
        <CardTitle class="text-xl">HansonDOC</CardTitle>
        <CardDescription>文档智能解析与 RAG 系统</CardDescription>
      </CardHeader>

      <CardContent class="space-y-4">
        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground" for="login-username">用户名</label>
          <Input
            id="login-username"
            v-model="form.username"
            placeholder="请输入用户名"
            :disabled="loading"
            autocomplete="username"
            @keyup.enter="handleLogin"
          />
        </div>

        <div class="space-y-1.5">
          <label class="text-sm font-medium text-foreground" for="login-password">密码</label>
          <Input
            id="login-password"
            v-model="form.password"
            type="password"
            placeholder="请输入密码"
            :disabled="loading"
            autocomplete="current-password"
            @keyup.enter="handleLogin"
          />
        </div>

        <Button
          type="button"
          class="w-full"
          :disabled="loading"
          @click="handleLogin"
        >
          <Loader2 v-if="loading" class="size-4 animate-spin" :stroke-width="1.5" />
          <span>{{ loading ? '登录中...' : '登 录' }}</span>
        </Button>

        <p class="text-center text-xs text-muted-foreground">
          HansonDOC · 文档智能解析与 RAG 系统
        </p>
      </CardContent>
    </Card>
  </div>
</template>
