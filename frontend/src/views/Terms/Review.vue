<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import {
  Check,
  X,
  ClipboardCheck,
  RefreshCw,
  Loader2,
} from 'lucide-vue-next'
import { termApi } from '@/api/modules/term'
import type { Term } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { PageHeader } from '@/components/ui/page-header'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/ui/empty-state'
import { Dialog } from '@/components/ui/dialog'
import { Pagination } from '@/components/ui/pagination'

const loading = ref(true)
const terms = ref<Term[]>([])
const total = ref(0)

const query = reactive({
  status: 'pending',
  page: 1,
  page_size: 20,
})

async function fetchList() {
  loading.value = true
  try {
    const res = await termApi.getList(query)
    terms.value = res.items
    total.value = res.total
  } catch {
    terms.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function handlePageChange(page: number) {
  query.page = page
  fetchList()
}

// ---------- 审核 ----------
const reviewDialogVisible = ref(false)
const reviewTarget = ref<Term | null>(null)
const reviewAction = ref<'approve' | 'reject'>('approve')
const reviewing = ref(false)

function openReviewDialog(term: Term, action: 'approve' | 'reject') {
  reviewTarget.value = term
  reviewAction.value = action
  reviewDialogVisible.value = true
}

async function confirmReview() {
  if (!reviewTarget.value) return
  reviewing.value = true
  try {
    await termApi.review(reviewTarget.value.id, reviewAction.value)
    if (reviewAction.value === 'approve') {
      toast.success('已通过', `术语「${reviewTarget.value.term}」已通过审核`)
    } else {
      toast.success('已拒绝', `术语「${reviewTarget.value.term}」已拒绝`)
    }
    reviewDialogVisible.value = false
    await fetchList()
  } catch {
    // 错误已处理
  } finally {
    reviewing.value = false
  }
}

// ---------- 工具函数 ----------
function formatSynonyms(synonyms: string[] | undefined): string {
  if (!synonyms || synonyms.length === 0) return ''
  return synonyms.join('、')
}

function formatTime(value: string | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return value
  }
}

onMounted(fetchList)
</script>

<template>
  <div>
    <PageHeader title="术语审核" description="审核待处理的术语条目">
      <template #actions>
        <Button variant="outline" size="sm" @click="fetchList">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
      </template>
    </PageHeader>

    <!-- 待审核统计横幅 -->
    <div
      v-if="!loading && terms.length > 0"
      class="mb-4 flex items-center gap-3 rounded-md border border-primary/30 bg-primary/5 p-3"
    >
      <div class="flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
        <ClipboardCheck class="size-5" :stroke-width="1.5" />
      </div>
      <div class="flex-1">
        <p class="text-sm font-medium text-foreground">
          共 {{ total }} 条待审核术语
        </p>
        <p class="text-xs text-muted-foreground">
          审核通过的术语将正式加入术语库，可用于后续解析任务的术语标准化
        </p>
      </div>
    </div>

    <!-- 术语列表 -->
    <Card>
      <CardContent class="p-0">
        <!-- 表头 -->
        <div
          class="hidden grid-cols-12 gap-3 border-b border-border bg-muted/40 px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-muted-foreground lg:grid"
        >
          <div class="col-span-2">术语</div>
          <div class="col-span-2">英文</div>
          <div class="col-span-3">定义</div>
          <div class="col-span-2">同义词</div>
          <div class="col-span-2">创建时间</div>
          <div class="col-span-1 text-right">操作</div>
        </div>

        <!-- 加载态 -->
        <div v-if="loading" class="divide-y divide-border">
          <div v-for="i in 5" :key="i" class="grid grid-cols-12 gap-3 px-4 py-3">
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-3 h-5" />
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-2 h-5" />
            <Skeleton class="col-span-1 h-5" />
          </div>
        </div>

        <!-- 空态 -->
        <EmptyState
          v-else-if="terms.length === 0"
          :icon="ClipboardCheck"
          title="暂无待审核术语"
          description="所有术语均已审核完成，新提交的术语将出现在此处等待审核"
          class="py-16"
        />

        <!-- 数据行 -->
        <div v-else class="divide-y divide-border">
          <div
            v-for="term in terms"
            :key="term.id"
            class="grid grid-cols-12 gap-3 px-4 py-3 transition-colors hover:bg-muted/30"
          >
            <!-- 术语名 -->
            <div class="col-span-12 lg:col-span-2">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">术语</div>
              <div class="flex items-center gap-1.5">
                <span class="font-medium text-foreground">{{ term.term }}</span>
                <Badge v-if="term.category" variant="outline" class="text-[10px]">
                  {{ term.category }}
                </Badge>
              </div>
            </div>

            <!-- 英文 -->
            <div class="col-span-6 lg:col-span-2">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">英文</div>
              <span class="font-mono text-sm text-muted-foreground">
                {{ term.english_term || '-' }}
              </span>
            </div>

            <!-- 定义 -->
            <div class="col-span-12 lg:col-span-3">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">定义</div>
              <p class="line-clamp-2 text-sm text-muted-foreground" :title="term.definition">
                {{ term.definition || '-' }}
              </p>
            </div>

            <!-- 同义词 -->
            <div class="col-span-12 lg:col-span-2">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">同义词</div>
              <div v-if="term.synonyms?.length" class="flex flex-wrap gap-1">
                <span
                  v-for="syn in term.synonyms"
                  :key="syn"
                  class="inline-flex items-center rounded bg-muted/60 px-1.5 py-0.5 text-[10px] text-muted-foreground"
                >
                  {{ syn }}
                </span>
              </div>
              <span v-else class="text-muted-foreground">-</span>
            </div>

            <!-- 创建时间 -->
            <div class="col-span-6 lg:col-span-2">
              <div class="lg:hidden mb-1 text-[10px] uppercase tracking-wide text-muted-foreground">创建时间</div>
              <span class="font-mono text-xs text-muted-foreground">
                {{ formatTime(term.created_at) }}
              </span>
            </div>

            <!-- 操作 -->
            <div class="col-span-12 flex items-center justify-end gap-2 lg:col-span-1">
              <Button
                variant="outline"
                size="sm"
                class="h-7 gap-1 border-success/40 text-success hover:bg-success/10 hover:text-success"
                @click="openReviewDialog(term, 'approve')"
              >
                <Check class="size-3.5" :stroke-width="1.5" />
                <span class="hidden sm:inline">通过</span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                class="h-7 gap-1 border-danger/40 text-danger hover:bg-danger/10 hover:text-danger"
                @click="openReviewDialog(term, 'reject')"
              >
                <X class="size-3.5" :stroke-width="1.5" />
                <span class="hidden sm:inline">拒绝</span>
              </Button>
            </div>
          </div>
        </div>

        <!-- 分页 -->
        <div
          v-if="total > 0"
          class="flex items-center justify-between border-t border-border px-4 py-3"
        >
          <p class="text-xs text-muted-foreground">共 {{ total }} 条待审核</p>
          <Pagination
            :current-page="query.page"
            :page-size="query.page_size"
            :total="total"
            @current-change="handlePageChange"
          />
        </div>
      </CardContent>
    </Card>

    <!-- 审核确认 Dialog -->
    <Dialog
      :open="reviewDialogVisible"
      :title="reviewAction === 'approve' ? '确认通过术语' : '确认拒绝术语'"
      :description="`术语「${reviewTarget?.term}」`"
      @update:open="(v) => (reviewDialogVisible = v)"
    >
      <div v-if="reviewTarget" class="space-y-3">
        <div
          :class="[
            'flex items-start gap-3 rounded-md border p-3',
            reviewAction === 'approve'
              ? 'border-success/30 bg-success/5'
              : 'border-danger/30 bg-danger/5',
          ]"
        >
          <Check
            v-if="reviewAction === 'approve'"
            class="mt-0.5 size-4 shrink-0 text-success"
            :stroke-width="1.5"
          />
          <X
            v-else
            class="mt-0.5 size-4 shrink-0 text-danger"
            :stroke-width="1.5"
          />
          <div class="flex-1 space-y-1 text-sm">
            <p class="text-foreground">
              即将{{ reviewAction === 'approve' ? '通过' : '拒绝' }}术语
              <span class="font-medium">{{ reviewTarget.term }}</span>
            </p>
            <p class="text-xs text-muted-foreground">
              <template v-if="reviewAction === 'approve'">
                通过后该术语将正式加入术语库，可用于术语标准化
              </template>
              <template v-else>
                拒绝后该术语将不会被加入术语库
              </template>
            </p>
          </div>
        </div>

        <!-- 术语信息预览 -->
        <div class="space-y-2 rounded-md border border-border bg-muted/20 p-3">
          <div class="grid grid-cols-3 gap-2 text-xs">
            <div>
              <p class="text-muted-foreground">英文</p>
              <p class="font-mono text-foreground">{{ reviewTarget.english_term || '-' }}</p>
            </div>
            <div>
              <p class="text-muted-foreground">分类</p>
              <p class="text-foreground">{{ reviewTarget.category || '-' }}</p>
            </div>
            <div>
              <p class="text-muted-foreground">标准号</p>
              <p class="font-mono text-foreground">{{ reviewTarget.standard_number || '-' }}</p>
            </div>
          </div>
          <div class="border-t border-border pt-2">
            <p class="mb-1 text-xs text-muted-foreground">定义</p>
            <p class="text-sm text-foreground">{{ reviewTarget.definition || '-' }}</p>
          </div>
          <div v-if="reviewTarget.synonyms?.length" class="border-t border-border pt-2">
            <p class="mb-1 text-xs text-muted-foreground">同义词</p>
            <div class="flex flex-wrap gap-1">
              <Badge
                v-for="syn in reviewTarget.synonyms"
                :key="syn"
                variant="outline"
                class="text-[10px]"
              >
                {{ syn }}
              </Badge>
            </div>
          </div>
        </div>
      </div>

      <div class="mt-6 flex items-center justify-end gap-2">
        <Button variant="outline" @click="reviewDialogVisible = false">取消</Button>
        <Button
          v-if="reviewAction === 'approve'"
          :disabled="reviewing"
          class="bg-success text-success-foreground hover:bg-success/90"
          @click="confirmReview"
        >
          <Loader2 v-if="reviewing" class="size-4 animate-spin" :stroke-width="1.5" />
          <Check v-else class="size-4" :stroke-width="1.5" />
          确认通过
        </Button>
        <Button
          v-else
          variant="destructive"
          :disabled="reviewing"
          @click="confirmReview"
        >
          <Loader2 v-if="reviewing" class="size-4 animate-spin" :stroke-width="1.5" />
          <X v-else class="size-4" :stroke-width="1.5" />
          确认拒绝
        </Button>
      </div>
    </Dialog>
  </div>
</template>
