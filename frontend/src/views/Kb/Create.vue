<script setup lang="ts">
/**
 * 新建知识库向导
 *
 * 两步流程：
 *   1. 选择领域模板（或空白知识库）
 *   2. 填写基本信息（名称、描述）
 *
 * 创建成功后跳转到知识库概览页。
 */
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Loader2,
  Database,
  FlaskConical,
  HeartPulse,
  FileText,
  MessageSquare,
  Sparkles,
  AlertCircle,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import type { DomainTemplateSummary } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'

const router = useRouter()

const step = ref<1 | 2>(1)
const loading = ref(true)
const creating = ref(false)
const templates = ref<DomainTemplateSummary[]>([])
const selectedTemplate = ref<string | null>(null) // null = 空白知识库

// 表单
const formName = ref('')
const formDescription = ref('')

// 模板图标映射
const templateIcons: Record<string, typeof Database> = {
  material_testing: FlaskConical,
  medical_device: HeartPulse,
  contract: FileText,
  general_qa: MessageSquare,
}

const selectedTpl = computed(() =>
  templates.value.find((t) => t.code === selectedTemplate.value),
)

const domainCode = computed(() => {
  if (selectedTemplate.value) {
    return selectedTpl.value?.domain_code || selectedTemplate.value
  }
  return 'general' // 空白知识库默认 general 领域
})

async function fetchTemplates() {
  loading.value = true
  try {
    const res = await kbApi.listTemplates()
    templates.value = res.items
  } catch {
    templates.value = []
  } finally {
    loading.value = false
  }
}

function selectTemplate(code: string | null) {
  selectedTemplate.value = code
}

function nextStep() {
  if (step.value === 1) {
    step.value = 2
  }
}

function prevStep() {
  if (step.value === 2) {
    step.value = 1
  }
}

async function handleCreate() {
  if (!formName.value.trim()) {
    toast.warning('请填写名称', '知识库名称不能为空')
    return
  }

  creating.value = true
  try {
    const res = await kbApi.create({
      name: formName.value.trim(),
      description: formDescription.value.trim() || undefined,
      domain_code: domainCode.value,
      template_code: selectedTemplate.value || undefined,
    })

    // 检查资源初始化结果
    const failedSteps = Object.entries(res.resources).filter(
      ([, v]) => !v.ok && !v.skipped,
    )
    if (failedSteps.length > 0) {
      toast.warning(
        '知识库已创建（部分资源初始化失败）',
        `失败步骤: ${failedSteps.map(([k]) => k).join(', ')}`,
      )
    } else {
      toast.success('创建成功', `知识库「${res.knowledge_base.name}」已创建`)
    }

    // 检查模板应用结果
    if (selectedTemplate.value && !res.template.applied) {
      toast.warning('模板未应用', res.template.reason || res.template.error || '未知原因')
    }

    router.push({ name: 'KbOverview', params: { kb_id: res.knowledge_base.id } })
  } catch {
    // 错误已由拦截器提示
  } finally {
    creating.value = false
  }
}

function goBack() {
  router.push({ name: 'KbList' })
}

onMounted(fetchTemplates)
</script>

<template>
  <div>
    <PageHeader title="新建知识库" description="选择领域模板，快速初始化知识库配置">
      <template #actions>
        <Button variant="outline" @click="goBack">
          <ArrowLeft class="size-4" :stroke-width="1.5" />
          返回列表
        </Button>
      </template>
    </PageHeader>

    <!-- 步骤指示器 -->
    <div class="mb-6 flex items-center justify-center gap-4">
      <div class="flex items-center gap-2">
        <div
          class="flex size-8 items-center justify-center rounded-full text-sm font-medium transition-colors"
          :class="step >= 1 ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'"
        >
          <Check v-if="step > 1" class="size-4" :stroke-width="2" />
          <span v-else>1</span>
        </div>
        <span class="text-sm font-medium" :class="step >= 1 ? 'text-foreground' : 'text-muted-foreground'">
          选择模板
        </span>
      </div>
      <div class="h-px w-12 bg-border" />
      <div class="flex items-center gap-2">
        <div
          class="flex size-8 items-center justify-center rounded-full text-sm font-medium transition-colors"
          :class="step >= 2 ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground'"
        >
          2
        </div>
        <span class="text-sm font-medium" :class="step >= 2 ? 'text-foreground' : 'text-muted-foreground'">
          填写信息
        </span>
      </div>
    </div>

    <!-- 步骤 1：选择模板 -->
    <div v-if="step === 1">
      <div v-if="loading" class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card v-for="i in 4" :key="i">
          <CardContent class="p-5">
            <Skeleton class="mb-3 h-10 w-10 rounded-md" />
            <Skeleton class="mb-2 h-5 w-2/3" />
            <Skeleton class="h-4 w-full" />
          </CardContent>
        </Card>
      </div>

      <div v-else class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <!-- 空白知识库 -->
        <Card
          class="cursor-pointer border-2 transition-all hover:border-primary/40"
          :class="selectedTemplate === null ? 'border-primary bg-primary/5' : 'border-border'"
          @click="selectTemplate(null)"
        >
          <CardContent class="p-5">
            <div class="mb-3 flex size-10 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <Database class="size-5" :stroke-width="1.5" />
            </div>
            <p class="mb-1 font-semibold text-foreground">空白知识库</p>
            <p class="text-xs text-muted-foreground">不应用任何模板，手动配置全部内容</p>
          </CardContent>
        </Card>

        <!-- 领域模板 -->
        <Card
          v-for="tpl in templates"
          :key="tpl.code"
          class="cursor-pointer border-2 transition-all hover:border-primary/40"
          :class="selectedTemplate === tpl.code ? 'border-primary bg-primary/5' : 'border-border'"
          @click="selectTemplate(tpl.code)"
        >
          <CardContent class="p-5">
            <div class="mb-3 flex size-10 items-center justify-center rounded-md bg-primary/10 text-primary">
              <component :is="templateIcons[tpl.code] || Sparkles" class="size-5" :stroke-width="1.5" />
            </div>
            <p class="mb-1 font-semibold text-foreground">{{ tpl.name }}</p>
            <p class="mb-3 line-clamp-2 text-xs text-muted-foreground">{{ tpl.description }}</p>
            <div class="flex flex-wrap gap-1">
              <Badge variant="secondary" class="text-[10px]">{{ tpl.category_count }} 类别</Badge>
              <Badge variant="secondary" class="text-[10px]">{{ tpl.regex_rule_count }} 正则</Badge>
              <Badge v-if="tpl.has_hook" variant="secondary" class="text-[10px]">Hook</Badge>
            </div>
          </CardContent>
        </Card>
      </div>

      <!-- 底部操作 -->
      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="goBack">取消</Button>
        <Button :disabled="!selectedTemplate && selectedTemplate !== null" @click="nextStep">
          下一步
          <ArrowRight class="size-4" :stroke-width="1.5" />
        </Button>
      </div>
    </div>

    <!-- 步骤 2：填写信息 -->
    <div v-else-if="step === 2" class="mx-auto max-w-lg">
      <Card>
        <CardContent class="space-y-5 p-6">
          <!-- 已选模板回显 -->
          <div v-if="selectedTpl" class="flex items-center gap-3 rounded-md border border-border bg-muted/20 p-3">
            <div class="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
              <component :is="templateIcons[selectedTpl.code] || Sparkles" class="size-4" :stroke-width="1.5" />
            </div>
            <div class="flex-1 min-w-0">
              <p class="text-sm font-medium text-foreground">{{ selectedTpl.name }}</p>
              <p class="truncate text-xs text-muted-foreground">{{ selectedTpl.description }}</p>
            </div>
            <button
              class="text-xs text-primary hover:underline"
              @click="prevStep"
            >
              更换
            </button>
          </div>

          <div v-else class="flex items-center gap-3 rounded-md border border-border bg-muted/20 p-3">
            <Database class="size-4 text-muted-foreground" :stroke-width="1.5" />
            <span class="text-sm text-muted-foreground">空白知识库（手动配置）</span>
          </div>

          <!-- 名称 -->
          <div class="space-y-2">
            <label class="text-sm font-medium text-foreground">
              知识库名称 <span class="text-danger">*</span>
            </label>
            <Input
              v-model="formName"
              placeholder="如：航天航空检测标准抽取"
              maxlength="100"
            />
          </div>

          <!-- 描述 -->
          <div class="space-y-2">
            <label class="text-sm font-medium text-foreground">描述</label>
            <Input
              v-model="formDescription"
              placeholder="简要描述知识库的用途与领域"
              maxlength="500"
            />
          </div>

          <!-- 领域编码（只读，来自模板） -->
          <div class="space-y-2">
            <label class="text-sm font-medium text-foreground">领域编码</label>
            <div class="flex items-center gap-2 rounded-md border border-border bg-muted/20 px-3 py-2">
              <span class="font-mono text-sm text-muted-foreground">{{ domainCode }}</span>
              <span class="text-xs text-muted-foreground">（由模板决定）</span>
            </div>
          </div>

          <!-- 资源初始化提示 -->
          <div class="flex items-start gap-2 rounded-md border border-primary/20 bg-primary/5 p-3">
            <AlertCircle class="mt-0.5 size-4 shrink-0 text-primary" :stroke-width="1.5" />
            <p class="text-xs text-muted-foreground">
              创建后将自动初始化物理资源（Milvus 向量库、MinIO 对象存储、NebulaGraph 图谱、Redis 缓存），
              并应用所选模板的领域配置。
            </p>
          </div>

          <!-- 操作按钮 -->
          <div class="flex items-center justify-between pt-2">
            <Button variant="outline" @click="prevStep">
              <ArrowLeft class="size-4" :stroke-width="1.5" />
              上一步
            </Button>
            <Button :disabled="creating || !formName.trim()" @click="handleCreate">
              <Loader2 v-if="creating" class="size-4 animate-spin" :stroke-width="1.5" />
              <Database v-else class="size-4" :stroke-width="1.5" />
              {{ creating ? '创建中...' : '创建知识库' }}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
</template>
