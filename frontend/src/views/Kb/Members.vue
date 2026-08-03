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

const route = useRoute()
const kbId = computed(() => route.params.kb_id as string)
const { isAdmin, isOwner, role } = useKbPermission()

const loading = ref(true)
const members = ref<KbMember[]>([])

const roleConfig: Record<KbRole, { label: string; icon: typeof Eye; color: string }> = {
  owner: { label: '所有者', icon: Crown, color: 'bg-primary/10 text-primary' },
  admin: { label: '管理员', icon: Shield, color: 'bg-success/10 text-success' },
  editor: { label: '编辑者', icon: Edit, color: 'bg-warning/10 text-warning' },
  viewer: { label: '查看者', icon: Eye, color: 'bg-muted text-muted-foreground' },
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
  if (!confirm(`确定将「${member.username || member.user_id}」移出知识库？`)) return
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
    // 过滤已在成员列表的用户
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
  <div>
    <PageHeader title="成员管理" description="管理知识库成员与角色权限">
      <template #actions>
        <Button variant="outline" @click="fetchMembers">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button v-if="isAdmin" @click="openAddDialog">
          <UserPlus class="size-4" :stroke-width="1.5" />
          添加成员
        </Button>
      </template>
    </PageHeader>

    <!-- 权限说明 -->
    <Card class="mb-4">
      <CardContent class="p-4">
        <h3 class="mb-2 text-sm font-medium">角色权限说明</h3>
        <div class="grid grid-cols-2 gap-3 text-xs lg:grid-cols-4">
          <div v-for="(cfg, r) in roleConfig" :key="r" class="flex items-center gap-2">
            <div class="flex size-7 items-center justify-center rounded-md" :class="cfg.color">
              <component :is="cfg.icon" class="size-3.5" :stroke-width="1.5" />
            </div>
            <div>
              <p class="font-medium text-foreground">{{ cfg.label }}</p>
              <p class="text-muted-foreground">
                {{ r === 'owner' ? '全部权限+删除KB' : r === 'admin' ? '管理配置/成员' : r === 'editor' ? '上传/抽取' : '只读' }}
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- 成员列表 -->
    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 3" :key="i" class="h-16 w-full" />
    </div>

    <EmptyState
      v-else-if="members.length === 0"
      :icon="Users"
      title="暂无成员"
      description="点击右上角「添加成员」邀请用户加入"
      class="py-12"
    />

    <div v-else class="space-y-2">
      <Card v-for="m in members" :key="m.user_id">
        <CardContent class="flex items-center gap-3 p-3">
          <!-- 头像 -->
          <div class="flex size-10 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <span class="text-sm font-medium">{{ (m.username || m.user_id)[0]?.toUpperCase() }}</span>
          </div>

          <!-- 用户信息 -->
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <p class="font-medium text-foreground">{{ m.username || m.user_id }}</p>
              <Badge variant="secondary" :class="roleConfig[m.role as KbRole].color" class="text-[10px]">
                <component :is="roleConfig[m.role as KbRole].icon" class="mr-1 size-3" :stroke-width="1.5" />
                {{ roleConfig[m.role as KbRole].label }}
              </Badge>
            </div>
            <p class="mt-0.5 truncate text-xs text-muted-foreground">{{ m.email || m.user_id }}</p>
          </div>

          <!-- 操作 -->
          <div v-if="isAdmin && m.role !== 'owner'" class="flex shrink-0 items-center gap-2">
            <Select
              :model-value="m.role"
              :options="roleOptions"
              class="w-28"
              @update:model-value="(v: string) => changeRole(m, v as KbRole)"
            />
            <Button variant="ghost" size="sm" @click="removeMember(m)">
              <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
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
      class="max-w-lg"
      @update:open="(v: boolean) => (addDialogOpen = v)"
    >
      <div class="space-y-4">
        <div class="space-y-2">
          <Label>搜索用户（用户名/邮箱/姓名）</Label>
          <div class="flex gap-2">
            <div class="relative flex-1">
              <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" :stroke-width="1.5" />
              <Input
                v-model="addSearchKw"
                placeholder="输入关键字后点击搜索"
                class="pl-8"
                @keyup.enter="searchUsers"
              />
            </div>
            <Button variant="outline" :disabled="addSearchLoading" @click="searchUsers">
              <Loader2 v-if="addSearchLoading" class="size-4 animate-spin" :stroke-width="1.5" />
              <Search v-else class="size-4" :stroke-width="1.5" />
              搜索
            </Button>
          </div>
        </div>

        <div class="space-y-2">
          <Label>选择用户</Label>
          <div class="max-h-56 overflow-auto rounded-md border border-border">
            <div v-if="addSearchLoading" class="flex h-28 items-center justify-center text-xs text-muted-foreground">
              <Loader2 class="mr-2 size-4 animate-spin" :stroke-width="1.5" />
              搜索中...
            </div>
            <EmptyState
              v-else-if="addUserCandidates.length === 0"
              :icon="Users"
              title="没有可添加的用户"
              description="请修改关键字搜索，或先到「用户管理」创建用户"
              class="py-8"
              icon-class="size-6"
              title-class="text-sm"
              desc-class="text-xs"
            />
            <label
              v-for="u in addUserCandidates"
              :key="u.id"
              class="flex cursor-pointer items-center gap-3 border-b border-border/60 px-3 py-2 last:border-b-0 hover:bg-muted/40 has-[:checked]:bg-primary/5"
            >
              <input
                type="radio"
                :value="u.id"
                v-model="addSelectedUserId"
                class="size-4 accent-primary"
              />
              <div class="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
                <span class="text-xs font-medium">{{ u.username[0]?.toUpperCase() }}</span>
              </div>
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-1.5">
                  <span class="text-sm font-medium text-foreground">{{ u.username }}</span>
                  <Badge v-if="u.is_superuser" variant="warning" class="text-[10px]">超管</Badge>
                  <Badge v-if="!u.is_active" variant="danger" class="text-[10px]">已禁用</Badge>
                </div>
                <div class="truncate text-xs text-muted-foreground">
                  <span v-if="u.email">{{ u.email }}</span>
                  <span v-if="u.full_name" class="ml-2">· {{ u.full_name }}</span>
                </div>
              </div>
            </label>
          </div>
        </div>

        <div class="space-y-2">
          <Label>指定角色</Label>
          <Select
            v-model="addSelectedRole"
            :model-value="addSelectedRole"
            :options="roleOptions"
            @update:model-value="(v: string) => (addSelectedRole = v as KbRole)"
          />
        </div>
      </div>

      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="addDialogOpen = false">取消</Button>
        <Button :disabled="!addSelectedUserId || addSubmitting" @click="submitAdd">
          <Loader2 v-if="addSubmitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ addSubmitting ? '添加中...' : '确认添加' }}
        </Button>
      </div>
    </Dialog>
  </div>
</template>
