<script setup lang="ts">
import { computed } from 'vue'
import { Check, X } from 'lucide-vue-next'

const props = defineProps<{
  password: string
}>()

interface Requirement {
  label: string
  test: (pwd: string) => boolean
}

const requirements: Requirement[] = [
  { label: '至少 8 位', test: (p) => p.length >= 8 },
  { label: '包含大写字母', test: (p) => /[A-Z]/.test(p) },
  { label: '包含小写字母', test: (p) => /[a-z]/.test(p) },
  { label: '包含数字', test: (p) => /\d/.test(p) },
  { label: '包含特殊字符', test: (p) => /[!@#$%^&*()_+\-=\[\]{};':",.<>/?\\|`~]/.test(p) },
]

const checks = computed(() => requirements.map(r => ({
  label: r.label,
  passed: r.test(props.password),
})))

const passedCount = computed(() => checks.value.filter(c => c.passed).length)

const strengthLevel = computed(() => {
  if (!props.password) return 0
  const count = passedCount.value
  if (count <= 2) return 1
  if (count <= 3) return 2
  if (count <= 4) return 3
  return 4
})

const strengthLabel = computed(() => {
  const labels = ['', '弱', '中', '强', '很强']
  return labels[strengthLevel.value]
})

const strengthColor = computed(() => {
  const colors = ['bg-muted', 'bg-danger', 'bg-warning', 'bg-primary', 'bg-success']
  return colors[strengthLevel.value]
})
</script>

<template>
  <div v-if="password" class="mt-2 space-y-2">
    <!-- 强度条 -->
    <div class="flex gap-1">
      <div
        v-for="i in 4"
        :key="i"
        class="h-1 flex-1 rounded-full transition-colors"
        :class="i <= strengthLevel ? strengthColor : 'bg-muted'"
      />
    </div>
    <p class="text-xs" :class="{
      'text-muted-foreground': strengthLevel === 0,
      'text-danger': strengthLevel === 1,
      'text-warning': strengthLevel === 2,
      'text-primary': strengthLevel === 3,
      'text-success': strengthLevel === 4,
    }">
      密码强度：{{ strengthLabel }}
    </p>
    <!-- 要求清单 -->
    <ul class="space-y-1">
      <li
        v-for="check in checks"
        :key="check.label"
        class="flex items-center gap-1.5 text-xs"
        :class="check.passed ? 'text-success' : 'text-muted-foreground'"
      >
        <Check v-if="check.passed" class="size-3 shrink-0" :stroke-width="2" />
        <X v-else class="size-3 shrink-0" :stroke-width="2" />
        {{ check.label }}
      </li>
    </ul>
  </div>
</template>
