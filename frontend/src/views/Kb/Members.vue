<script setup lang="ts">
/**
 * 知识库成员管理
 *
 * 功能：成员列表/添加成员/角色变更/移除成员
 * 权限：viewer 可查看；admin+ 可管理成员
 * 角色说明：owner（所有者）/ admin（管理员）/ editor（编辑者）/ viewer（查看者）
 */
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  Users,
  UserPlus,
  Trash2,
  Crown,
  Shield,
  Edit,
  Eye,
  Loader2,
  RefreshCw,
  Search,
} from 'lucide-vue-next'
import { kbApi } from '@/api/modules/kb'
import { usersApi } from '@/api/modules/users'
import { useKbPermission } from '@/composables/useKbPermission'
import type { KbMember, KbRole, User } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader } from '@/components/ui/page-header'
import { Select } from '@/components/ui/select'
import { Dialog } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { EmptyState } from '@/components/ui/empty-state'
import { cn } from '@/lib/utils'
import { confirm } from '@/composables/useConfirm'

const route = useRoute()
const kbId = computed(() => route.params.kb_id as string)
const { isAdmin, isOwner, role } = useKbPermission()

const loading = ref(true)
const members = ref<KbMember[]>([])

const roleConfig: Record<KbRole, { label: string; icon: typeof Eye; color: string; bgGradient: string; borderColor: string; glowColor: string }> = {
  owner: {
    label: '所有者',
    icon: Crown,
    color: 'text-amber-600 dark:text-amber-400',
    bgGradient: 'bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-500/10 dark:to-orange-500/10',
    borderColor: 'border-amber-200/60 dark:border-amber-500/20',
    glowColor: 'shadow-amber-500/10',
  },
  admin: {
    label: '管理员',
    icon: Shield,
    color: 'text-success dark:text-success/90',
    bgGradient: 'bg-gradient-to-r from-emerald-50 to-teal-50 dark:from-emerald-500/10 dark:to-teal-500/10',
    borderColor: 'border-emerald-200/60 dark:border-emerald-500/20',
    glowColor: 'shadow-emerald-500/10',
  },
  editor: {
    label: '编辑者',
    icon: Edit,
    color: 'text-warning dark:text-warning/90',
    bgGradient: 'bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-blue-500/10 dark:to-indigo-500/10',
    borderColor: 'border-blue-200/60 dark:border-blue-500/20',
    glowColor: 'shadow-blue-500/10',
  },
  viewer: {
    label: '查看者',
    icon: Eye,
    color: 'text-muted-foreground',
    bgGradient: 'bg-gradient-to-r from-slate-50 to-zinc-50 dark:from-slate-500/10 dark:to-zinc-500/10',
    borderColor: 'border-slate-200/60 dark:border-slate-500/20',
    glowColor: 'shadow-slate-500/10',
  },
}

const editableRoles: KbRole[] = ['admin', 'editor', 'viewer']
const roleOptions = editableRoles.map((r) => ({ value: r, label: roleConfig[r].label }))

async function fetchMembers() {
  loading.value = true
  try {
    const res = await kbApi.listMembers(kbId.value)
    members.value = res.items
  } catch {
    members.value = []
  } finally {
    loading.value = false
  }
}

async function changeRole(member: KbMember, newRole: KbRole) {
  if (member.role === 'owner') {
    toast.warning('不可修改所有者角色')
    return
  }
  try {
    await kbApi.updateMemberRole(kbId.value, member.user_id, newRole)
    toast.success('角色已更新', `${member.username || member.user_id} → ${roleConfig[newRole].label}`)
    await fetchMembers()
  } catch {
    // 错误已由拦截器提示
  }
}

async function removeMember(member: KbMember) {
  if (member.role === 'owner') {
    toast.warning('不可移除所有者')
    return
  }
  if (!await confirm(`确定将「${member.username || member.user_id}」移出知识库？`)) return
  try {
    await kbApi.removeMember(kbId.value, member.user_id)
    toast.success('已移除', member.username || member.user_id)
    await fetchMembers()
  } catch {
    // 错误已由拦截器提示
  }
}

// ---------- 添加成员对话框 ----------
const addDialogOpen = ref(false)
const addSearchKw = ref('')
const addSearchLoading = ref(false)
const addUserCandidates = ref<User[]>([])
const addSelectedUserId = ref<string>('')
const addSelectedRole = ref<KbRole>('viewer')
const addSubmitting = ref(false)
const existingUserIds = computed(() => new Set(members.value.map((m) => m.user_id)))

async function searchUsers() {
  addSearchLoading.value = true
  addUserCandidates.value = []
  try {
    const res = await usersApi.list({
      page: 1,
      page_size: 20,
      keyword: addSearchKw.value.trim() || undefined,
      is_active: true,
    })
    addUserCandidates.value = (res.items || []).filter(
      (u: User) => !existingUserIds.value.has(u.id),
    )
  } catch (e) {
    toast.error('搜索失败', (e as Error).message || '请稍后重试')
  } finally {
    addSearchLoading.value = false
  }
}

function openAddDialog() {
  addSearchKw.value = ''
  addUserCandidates.value = []
  addSelectedUserId.value = ''
  addSelectedRole.value = 'viewer'
  addDialogOpen.value = true
  searchUsers()
}

async function submitAdd() {
  if (!addSelectedUserId.value) {
    toast.warning('请选择用户')
    return
  }
  addSubmitting.value = true
  try {
    await kbApi.addMember(kbId.value, addSelectedUserId.value, addSelectedRole.value)
    const u = addUserCandidates.value.find((x) => x.id === addSelectedUserId.value)
    toast.success('成员已添加', `${u?.username || addSelectedUserId.value} → ${roleConfig[addSelectedRole.value].label}`)
    addDialogOpen.value = false
    await fetchMembers()
  } catch {
    // 错误已由拦截器提示
  } finally {
    addSubmitting.value = false
  }
}

onMounted(fetchMembers)
</script>

<template>
  <div class="space-y-4">
    <PageHeader title="成员管理" description="管理知识库成员与角色权限">
      <template #actions>
        <Button
          variant="outline"
          @click="fetchMembers"
          class="transition-all duration-200 hover:border-primary/50 hover:bg-primary/5 hover:shadow-sm"
        >
          <RefreshCw class="size-4 transition-transform duration-500" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button
          v-if="isAdmin"
          @click="openAddDialog"
          class="relative overflow-hidden transition-all duration-300 hover:shadow-primary-lg hover:-translate-y-0.5 active:translate-y-0"
        >
          <UserPlus class="size-4" :stroke-width="1.5" />
          添加成员
        </Button>
      </template>
    </PageHeader>

    <!-- 权限说明 -->
    <Card class="group/card overflow-hidden border border-border/60 bg-card/50 backdrop-blur-sm transition-all duration-300 hover:border-primary/20 hover:shadow-md hover:shadow-primary/5">
      <CardContent class="p-5">
        <div class="mb-4 flex items-center gap-2">
          <div class="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Shield class="size-4" :stroke-width="1.5" />
          </div>
          <h3 class="text-sm font-semibold tracking-tight">角色权限说明</h3>
        </div>
        <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div
            v-for="(cfg, r) in roleConfig"
            :key="r"
            class="group/role relative overflow-hidden rounded-xl border p-3 transition-all duration-300 hover:-translate-y-0.5 hover:shadow-md"
            :class="[cfg.bgGradient, cfg.borderColor, cfg.glowColor]"
          >
            <div class="flex items-start gap-2.5">
              <div class="flex size-9 shrink-0 items-center justify-center rounded-lg bg-white/60 shadow-sm backdrop-blur-sm transition-transform duration-300 group-hover/role:scale-110 dark:bg-black/20">
                <component :is="cfg.icon" class="size-4" :class="cfg.color" :stroke-width="1.5" />
              </div>
              <div class="min-w-0 flex-1">
                <p class="text-sm font-semibold text-foreground">{{ cfg.label }}</p>
                <p class="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                  {{
                    r === 'owner'
                      ? '全部权限 + 删除知识库'
                      : r === 'admin'
                        ? '管理配置与成员'
                        : r === 'editor'
                          ? '上传文档与抽取'
                          : '只读访问'
                  }}
                </p>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 成员列表 -->
    <div v-if="loading" class="space-y-3">
      <Skeleton v-for="i in 3" :key="i" class="h-20 w-full rounded-xl" />
    </div>

    <EmptyState
      v-else-if="members.length === 0"
      :icon="Users"
      title="暂无成员"
      description="点击右上角「添加成员」邀请用户加入"
      class="py-16"
    />

    <div v-else class="space-y-3">
      <Card
        v-for="m in members"
        :key="m.user_id"
        class="group/member group relative overflow-hidden border border-border/60 bg-card/50 backdrop-blur-sm transition-all duration-300 hover:-translate-y-1 hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5"
      >
        <div class="absolute inset-0 bg-gradient-to-r from-transparent via-primary/[0.02] to-transparent opacity-0 transition-opacity duration-500 group-hover/member:opacity-100" />
        <CardContent class="relative flex items-center gap-4 p-4">
          <div class="relative">
            <div class="flex size-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary/20 to-primary/5 font-semibold text-primary shadow-sm ring-1 ring-primary/10 transition-all duration-300 group-hover/member:scale-105 group-hover/member:ring-primary/30">
              <span class="text-sm">{{ (m.username || m.user_id)[0]?.toUpperCase() }}</span>
            </div>
            <div class="absolute -bottom-0.5 -right-0.5 size-3 rounded-full border-2 border-background bg-emerald-500 shadow-sm" />
          </div>

          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <p class="truncate text-sm font-semibold tracking-tight text-foreground">{{ m.username || m.user_id }}</p>
              <Badge
                :class="cn(
                  'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium shadow-sm transition-all duration-200',
                  roleConfig[m.role as KbRole].bgGradient,
                  roleConfig[m.role as KbRole].borderColor,
                  roleConfig[m.role as KbRole].color,
                )"
              >
                <component :is="roleConfig[m.role as KbRole].icon" class="size-3" :stroke-width="2" />
                {{ roleConfig[m.role as KbRole].label }}
              </Badge>
            </div>
            <p class="mt-1 truncate text-xs text-muted-foreground">{{ m.email || m.user_id }}</p>
          </div>

          <div v-if="isAdmin && m.role !== 'owner'" class="flex shrink-0 items-center gap-2">
            <Select
              :model-value="m.role"
              :options="roleOptions"
              class="w-28 transition-all duration-200 hover:border-primary/50"
              @update:model-value="(v: string) => changeRole(m, v as KbRole)"
            />
            <Button
              variant="ghost"
              size="sm"
              class="group/btn text-muted-foreground transition-all duration-200 hover:bg-destructive/10 hover:text-destructive"
              @click="removeMember(m)"
            >
              <Trash2 class="size-4 transition-transform duration-200 group-hover/btn:scale-110" :stroke-width="1.5" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 添加成员对话框 -->
    <Dialog
      :open="addDialogOpen"
      title="添加成员"
      description="从系统用户中选择并指定角色，加入当前知识库"
      class="max-w-lg overflow-hidden"
      @update:open="(v: boolean) => (addDialogOpen = v)"
    >
      <div class="space-y-5">
        <div class="space-y-2.5">
          <Label class="text-sm font-medium">搜索用户（用户名/邮箱/姓名）</Label>
          <div class="flex gap-2">
            <div class="relative flex-1">
              <Search class="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground transition-colors duration-200" :stroke-width="1.5" />
              <Input
                v-model="addSearchKw"
                placeholder="输入关键字后点击搜索"
                class="pl-9 transition-all duration-200 focus:border-primary/50 focus:ring-primary/20"
                @keyup.enter="searchUsers"
              />
            </div>
            <Button
              variant="outline"
              :disabled="addSearchLoading"
              class="transition-all duration-200 hover:border-primary/50 hover:bg-primary/5"
              @click="searchUsers"
            >
              <Loader2 v-if="addSearchLoading" class="size-4 animate-spin" :stroke-width="1.5" />
              <Search v-else class="size-4" :stroke-width="1.5" />
              搜索
            </Button>
          </div>
        </div>

        <div class="space-y-2.5">
          <Label class="text-sm font-medium">选择用户</Label>
          <div class="max-h-60 overflow-auto rounded-xl border border-border/60 bg-muted/20 transition-all duration-200 focus-within:border-primary/30 focus-within:ring-2 focus-within:ring-primary/10">
            <div v-if="addSearchLoading" class="flex h-32 items-center justify-center text-xs text-muted-foreground">
              <Loader2 class="mr-2 size-4 animate-spin" :stroke-width="1.5" />
              搜索中...
            </div>
            <EmptyState
              v-else-if="addUserCandidates.length === 0"
              :icon="Users"
              title="没有可添加的用户"
              description="请修改关键字搜索，或先到「用户管理」创建用户"
              class="py-10"
              icon-class="size-7"
              title-class="text-sm"
              desc-class="text-xs"
            />
            <label
              v-for="u in addUserCandidates"
              :key="u.id"
              class="group/user flex cursor-pointer items-center gap-3 border-b border-border/40 px-4 py-3 transition-all duration-200 last:border-b-0 hover:bg-muted/50 has-[:checked]:bg-primary/5"
            >
              <input
                type="radio"
                :value="u.id"
                v-model="addSelectedUserId"
                class="size-4 accent-primary transition-transform duration-200"
              />
              <div class="flex size-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-primary/20 to-primary/5 font-semibold text-primary shadow-sm ring-1 ring-primary/10 transition-all duration-200 group-hover/user:scale-105">
                <span class="text-xs">{{ u.username[0]?.toUpperCase() }}</span>
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="text-sm font-medium text-foreground">{{ u.username }}</span>
                  <Badge v-if="u.is_superuser" class="rounded-full bg-gradient-to-r from-amber-500/10 to-orange-500/10 text-[10px] font-medium text-amber-600 ring-1 ring-amber-500/20 dark:text-amber-400">超管</Badge>
                  <Badge v-if="!u.is_active" class="rounded-full bg-gradient-to-r from-red-500/10 to-rose-500/10 text-[10px] font-medium text-red-600 ring-1 ring-red-500/20 dark:text-red-400">已禁用</Badge>
                </div>
                <div class="truncate text-xs text-muted-foreground">
                  <span v-if="u.email">{{ u.email }}</span>
                  <span v-if="u.full_name" class="ml-2">· {{ u.full_name }}</span>
                </div>
              </div>
            </label>
          </div>
        </div>

        <div class="space-y-2.5">
          <Label class="text-sm font-medium">指定角色</Label>
          <Select
            v-model="addSelectedRole"
            :options="roleOptions"
            class="transition-all duration-200 hover:border-primary/50"
          />
        </div>
      </div>

      <div class="mt-6 flex justify-end gap-2 pt-2">
        <Button
          variant="outline"
          class="transition-all duration-200 hover:bg-muted/50"
          @click="addDialogOpen = false"
        >
          取消
        </Button>
        <Button
          :disabled="!addSelectedUserId || addSubmitting"
          class="relative overflow-hidden transition-all duration-300 hover:shadow-primary-lg hover:-translate-y-0.5 active:translate-y-0 disabled:opacity-50 disabled:hover:translate-y-0 disabled:hover:shadow-none"
          @click="submitAdd"
        >
          <Loader2 v-if="addSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ addSubmitting ? '添加中...' : '确认添加' }}
        </Button>
      </div>
    </Dialog>
  </div>
</template>
