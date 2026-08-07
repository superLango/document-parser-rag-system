<script setup lang="ts">
/**
 * 用户管理（超管专属）
 *
 * 功能：用户列表/创建/编辑/启用禁用/超管设置/重置密码/软删除
 * 权限：仅超级管理员可访问（router 守卫 + 后端 require_superuser 双重保护）
 */
import { ref, onMounted, computed } from 'vue'
import {
  ShieldCheck,
  UserPlus,
  RefreshCw,
  Loader2,
  Search,
  KeyRound,
  Trash2,
  Crown,
  CheckCircle2,
  XCircle,
  Power,
} from 'lucide-vue-next'
import { usersApi } from '@/api/modules/users'
import type { User } from '@/api/types'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Dialog } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { PageHeader } from '@/components/ui/page-header'
import { EmptyState } from '@/components/ui/empty-state'
import { Pagination } from '@/components/ui/pagination'
import { confirm } from '@/composables/useConfirm'

const loading = ref(true)
const users = ref<User[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const keyword = ref('')
const activeFilter = ref<string>('')

// 创建/编辑对话框
const dialogOpen = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const editingUser = ref<User | null>(null)
const submitting = ref(false)
const form = ref({
  username: '',
  email: '',
  password: '',
  full_name: '',
  phone: '',
  department: '',
  is_superuser: false,
  is_active: true,
  notes: '',
})

// 重置密码对话框
const resetDialogOpen = ref(false)
const resetTarget = ref<User | null>(null)
const newPassword = ref('')

const isCreate = computed(() => dialogMode.value === 'create')

async function fetchUsers() {
  loading.value = true
  try {
    const res = await usersApi.list({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value || undefined,
      is_active: activeFilter.value === '' ? undefined : activeFilter.value === 'true',
    })
    users.value = res.items
    total.value = res.total
  } catch {
    users.value = []
  } finally {
    loading.value = false
  }
}

function openCreate() {
  dialogMode.value = 'create'
  editingUser.value = null
  form.value = {
    username: '',
    email: '',
    password: '',
    full_name: '',
    phone: '',
    department: '',
    is_superuser: false,
    is_active: true,
    notes: '',
  }
  dialogOpen.value = true
}

function openEdit(user: User) {
  dialogMode.value = 'edit'
  editingUser.value = user
  form.value = {
    username: user.username,
    email: user.email,
    password: '',
    full_name: user.full_name || '',
    phone: user.phone || '',
    department: user.department || '',
    is_superuser: user.is_superuser || false,
    is_active: user.is_active,
    notes: '',
  }
  dialogOpen.value = true
}

async function submitForm() {
  if (isCreate.value && (!form.value.username || !form.value.password)) {
    toast.warning('请填写用户名和密码')
    return
  }
  submitting.value = true
  try {
    if (isCreate.value) {
      await usersApi.create({
        username: form.value.username,
        email: form.value.email || undefined,
        password: form.value.password,
        full_name: form.value.full_name || undefined,
        phone: form.value.phone || undefined,
        department: form.value.department || undefined,
        is_superuser: form.value.is_superuser,
      })
      toast.success('用户已创建', form.value.username)
    } else if (editingUser.value) {
      await usersApi.update(editingUser.value.id, {
        email: form.value.email || undefined,
        full_name: form.value.full_name || undefined,
        phone: form.value.phone || undefined,
        department: form.value.department || undefined,
        notes: form.value.notes || undefined,
        is_active: form.value.is_active,
        is_superuser: form.value.is_superuser,
      })
      toast.success('用户已更新', form.value.username)
    }
    dialogOpen.value = false
    await fetchUsers()
  } catch {
    // 错误已由拦截器提示
  } finally {
    submitting.value = false
  }
}

async function toggleActive(user: User) {
  try {
    await usersApi.setActive(user.id, !user.is_active)
    toast.success(user.is_active ? '已禁用' : '已启用', user.username)
    await fetchUsers()
  } catch {
    // 错误已由拦截器提示
  }
}

async function toggleSuperuser(user: User) {
  try {
    await usersApi.setSuperuser(user.id, !user.is_superuser)
    toast.success(user.is_superuser ? '已撤销超管' : '已设为超管', user.username)
    await fetchUsers()
  } catch {
    // 错误已由拦截器提示
  }
}

function openReset(user: User) {
  resetTarget.value = user
  newPassword.value = ''
  resetDialogOpen.value = true
}

async function submitReset() {
  if (!resetTarget.value || !newPassword.value) {
    toast.warning('请输入新密码')
    return
  }
  submitting.value = true
  try {
    await usersApi.resetPassword(resetTarget.value.id, newPassword.value)
    toast.success('密码已重置', resetTarget.value.username)
    resetDialogOpen.value = false
  } catch {
    // 错误已由拦截器提示
  } finally {
    submitting.value = false
  }
}

async function deleteUser(user: User) {
  if (!await confirm({ title: `确定删除用户「${user.username}」？`, description: '此操作为软删除，可联系 DBA 恢复。', variant: 'danger', confirmText: '删除' })) return
  try {
    await usersApi.delete(user.id)
    toast.success('已删除', user.username)
    await fetchUsers()
  } catch {
    // 错误已由拦截器提示
  }
}

function handleSearch() {
  page.value = 1
  fetchUsers()
}

function handlePageChange(p: number) {
  page.value = p
  fetchUsers()
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

onMounted(fetchUsers)
</script>

<template>
  <div>
    <PageHeader title="用户管理" description="管理系统用户、角色与状态">
      <template #actions>
        <Button variant="outline" @click="fetchUsers">
          <RefreshCw class="size-4" :class="{ 'animate-spin': loading }" :stroke-width="1.5" />
          刷新
        </Button>
        <Button @click="openCreate">
          <UserPlus class="size-4" :stroke-width="1.5" />
          新建用户
        </Button>
      </template>
    </PageHeader>

    <!-- 过滤栏 -->
    <Card class="mb-4">
      <CardContent class="flex flex-wrap items-center gap-3 p-3">
        <div class="relative min-w-[200px] flex-1">
          <Search class="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" :stroke-width="1.5" />
          <Input
            v-model="keyword"
            placeholder="搜索用户名 / 邮箱 / 姓名"
            class="pl-8"
            @keyup.enter="handleSearch"
          />
        </div>
        <Select
          :model-value="activeFilter"
          :options="[
            { value: '', label: '全部状态' },
            { value: 'true', label: '已启用' },
            { value: 'false', label: '已禁用' },
          ]"
          class="w-32"
          @update:model-value="(v: string) => { activeFilter = v; handleSearch() }"
        />
        <Button variant="outline" size="sm" @click="handleSearch">
          <Search class="size-4" :stroke-width="1.5" />
          搜索
        </Button>
      </CardContent>
    </Card>

    <!-- 用户列表 -->
    <div v-if="loading" class="space-y-2">
      <Skeleton v-for="i in 5" :key="i" class="h-16 w-full" />
    </div>

    <EmptyState
      v-else-if="users.length === 0"
      :icon="ShieldCheck"
      title="暂无用户"
      description="点击「新建用户」创建第一个用户"
      class="py-12"
    />

    <div v-else class="space-y-2">
      <Card v-for="u in users" :key="u.id">
        <CardContent class="flex items-center gap-3 p-3">
          <!-- 头像 -->
          <div
            class="flex size-10 shrink-0 items-center justify-center rounded-full"
            :class="u.is_superuser ? 'bg-warning/10 text-warning' : 'bg-primary/10 text-primary'"
          >
            <Crown v-if="u.is_superuser" class="size-5" :stroke-width="1.5" />
            <span v-else class="text-sm font-medium">{{ u.username[0]?.toUpperCase() }}</span>
          </div>

          <!-- 用户信息 -->
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <p class="font-medium text-foreground">{{ u.username }}</p>
              <Badge v-if="u.is_superuser" variant="warning" class="text-[10px]">
                <Crown class="mr-0.5 size-3" :stroke-width="1.5" />
                超管
              </Badge>
              <Badge
                variant="secondary"
                :class="u.is_active ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'"
                class="text-[10px]"
              >
                <component
                  :is="u.is_active ? CheckCircle2 : XCircle"
                  class="mr-0.5 size-3"
                  :stroke-width="1.5"
                />
                {{ u.is_active ? '启用' : '禁用' }}
              </Badge>
            </div>
            <div class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
              <span v-if="u.email">{{ u.email }}</span>
              <span v-if="u.full_name">· {{ u.full_name }}</span>
              <span v-if="u.department">· {{ u.department }}</span>
              <span>· 注册 {{ formatTime(u.created_at) }}</span>
            </div>
          </div>

          <!-- 操作 -->
          <div class="flex shrink-0 items-center gap-1">
            <Button variant="ghost" size="sm" :title="u.is_active ? '禁用' : '启用'" @click="toggleActive(u)">
              <Power class="size-4" :class="{ 'text-danger': u.is_active }" :stroke-width="1.5" />
            </Button>
            <Button variant="ghost" size="sm" title="重置密码" @click="openReset(u)">
              <KeyRound class="size-4" :stroke-width="1.5" />
            </Button>
            <Button variant="ghost" size="sm" title="编辑" @click="openEdit(u)">
              <ShieldCheck class="size-4" :stroke-width="1.5" />
            </Button>
            <Button
              v-if="!u.is_superuser"
              variant="ghost"
              size="sm"
              title="设为超管"
              @click="toggleSuperuser(u)"
            >
              <Crown class="size-4" :stroke-width="1.5" />
            </Button>
            <Button variant="ghost" size="sm" title="删除" @click="deleteUser(u)">
              <Trash2 class="size-4 text-danger" :stroke-width="1.5" />
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- 分页 -->
    <div v-if="total > pageSize" class="mt-4 flex justify-center">
      <Pagination
        :page="page"
        :page-size="pageSize"
        :total="total"
        @change="(p: number) => handlePageChange(p)"
      />
    </div>

    <!-- 创建/编辑对话框 -->
    <Dialog
      :open="dialogOpen"
      :title="isCreate ? '新建用户' : `编辑用户 · ${editingUser?.username}`"
      :description="isCreate ? '创建新用户账户' : '修改用户信息与状态'"
      class="max-w-xl"
      @update:open="(v: boolean) => (dialogOpen = v)"
    >
      <div class="space-y-4">
        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <Label>用户名 *</Label>
            <Input v-model="form.username" :disabled="!isCreate" placeholder="登录用户名" />
          </div>
          <div class="space-y-1.5">
            <Label>邮箱</Label>
            <Input v-model="form.email" type="email" placeholder="user@example.com" />
          </div>
        </div>

        <div v-if="isCreate" class="space-y-1.5">
          <Label>密码 *</Label>
          <Input v-model="form.password" type="password" placeholder="至少 8 位，含大小写数字" />
        </div>

        <div class="grid grid-cols-2 gap-3">
          <div class="space-y-1.5">
            <Label>姓名</Label>
            <Input v-model="form.full_name" placeholder="真实姓名" />
          </div>
          <div class="space-y-1.5">
            <Label>手机</Label>
            <Input v-model="form.phone" placeholder="手机号" />
          </div>
        </div>

        <div class="space-y-1.5">
          <Label>部门</Label>
          <Input v-model="form.department" placeholder="所属部门" />
        </div>

        <div class="flex items-center gap-6">
          <label class="flex items-center gap-2 text-sm">
            <Switch :model-value="form.is_active" @update:model-value="(v: boolean) => (form.is_active = v)" />
            启用账户
          </label>
          <label class="flex items-center gap-2 text-sm">
            <Switch :model-value="form.is_superuser" @update:model-value="(v: boolean) => (form.is_superuser = v)" />
            超级管理员
          </label>
        </div>
      </div>

      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="dialogOpen = false">取消</Button>
        <Button :disabled="submitting" @click="submitForm">
          <Loader2 v-if="submitting" class="size-4 animate-spin" :stroke-width="1.5" />
          {{ isCreate ? '创建' : '保存' }}
        </Button>
      </div>
    </Dialog>

    <!-- 重置密码对话框 -->
    <Dialog
      :key="resetTarget?.id ?? 'new'"
      :open="resetDialogOpen"
      title="重置密码"
      :description="resetTarget ? `为用户「${resetTarget.username}」设置新密码` : '为用户设置新密码'"
      @update:open="(v: boolean) => (resetDialogOpen = v)"
    >
      <div class="space-y-3">
        <div class="space-y-1.5">
          <Label>新密码</Label>
          <Input v-model="newPassword" type="password" placeholder="至少 8 位，含大小写数字" />
        </div>
        <p class="text-xs text-muted-foreground">重置后用户需使用新密码登录，旧密码立即失效。</p>
      </div>
      <div class="mt-6 flex justify-end gap-2">
        <Button variant="outline" @click="resetDialogOpen = false">取消</Button>
        <Button :disabled="submitting" @click="submitReset">
          <Loader2 v-if="submitting" class="size-4 animate-spin" :stroke-width="1.5" />
          确认重置
        </Button>
      </div>
    </Dialog>
  </div>
</template>
