<script setup lang="ts">
/**
 * 个人中心
 *
 * 功能：个人信息编辑 / 修改密码 / 账户安全信息
 * 权限：所有登录用户
 */
import { ref, onMounted, computed } from 'vue'
import {
  UserCircle,
  KeyRound,
  Mail,
  Phone,
  Building2,
  Loader2,
  Save,
  Shield,
  Clock,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api/modules/auth'
import { toast } from '@/components/ui/toast'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { PageHeader } from '@/components/ui/page-header'
import PasswordStrengthMeter from '@/components/common/PasswordStrengthMeter.vue'

const authStore = useAuthStore()
const user = computed(() => authStore.user)

// 资料表单
const profileForm = ref({
  email: '',
  full_name: '',
  phone: '',
  department: '',
})
const savingProfile = ref(false)

// 密码表单
const passwordForm = ref({
  old_password: '',
  new_password: '',
  confirm_password: '',
})
const savingPassword = ref(false)

function initProfileForm() {
  if (user.value) {
    profileForm.value = {
      email: user.value.email || '',
      full_name: user.value.full_name || '',
      phone: user.value.phone || '',
      department: user.value.department || '',
    }
  }
}

async function saveProfile() {
  savingProfile.value = true
  try {
    await authApi.updateProfile({
      email: profileForm.value.email,
      full_name: profileForm.value.full_name,
      phone: profileForm.value.phone,
      department: profileForm.value.department,
    })
    toast.success('资料已更新')
    await authStore.fetchUser()
  } catch {
    // 错误已由拦截器提示
  } finally {
    savingProfile.value = false
  }
}

async function changePassword() {
  if (passwordForm.value.new_password !== passwordForm.value.confirm_password) {
    toast.warning('两次输入的新密码不一致')
    return
  }
  if (passwordForm.value.new_password.length < 8) {
    toast.warning('新密码至少 8 位')
    return
  }
  savingPassword.value = true
  try {
    await authApi.changePassword({
      old_password: passwordForm.value.old_password,
      new_password: passwordForm.value.new_password,
    })
    toast.success('密码已修改')
    passwordForm.value = { old_password: '', new_password: '', confirm_password: '' }
  } catch {
    // 错误已由拦截器提示
  } finally {
    savingPassword.value = false
  }
}

function formatTime(value: string | null | undefined): string {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString('zh-CN')
  } catch {
    return value
  }
}

onMounted(() => {
  initProfileForm()
})
</script>

<template>
  <div>
    <PageHeader title="个人中心" description="管理个人信息与账户安全" />

    <div class="mx-auto max-w-3xl">
      <!-- 账户概览卡片 -->
      <Card class="mb-4">
        <CardContent class="flex items-center gap-4 p-5">
          <div class="flex size-16 shrink-0 items-center justify-center rounded-full bg-primary/10 text-primary">
            <span class="text-2xl font-semibold">{{ user?.username?.[0]?.toUpperCase() || 'U' }}</span>
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <h2 class="text-lg font-semibold text-foreground">{{ user?.username }}</h2>
              <Badge v-if="user?.is_superuser" variant="warning" class="text-[10px]">
                <Shield class="mr-0.5 size-3" :stroke-width="1.5" />
                超级管理员
              </Badge>
              <Badge
                variant="secondary"
                :class="user?.is_active ? 'bg-success/10 text-success' : 'bg-danger/10 text-danger'"
                class="text-[10px]"
              >
                {{ user?.is_active ? '启用' : '禁用' }}
              </Badge>
            </div>
            <p class="mt-1 text-sm text-muted-foreground">{{ user?.email || '未设置邮箱' }}</p>
            <div class="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
              <Clock class="size-3" :stroke-width="1.5" />
              上次登录 {{ formatTime(user?.last_login_at) }}
            </div>
          </div>
        </CardContent>
      </Card>

      <Tabs default-value="profile">
        <TabsList class="mb-4">
          <TabsTrigger value="profile">
            <UserCircle class="mr-1.5 size-4" :stroke-width="1.5" />
            个人资料
          </TabsTrigger>
          <TabsTrigger value="security">
            <KeyRound class="mr-1.5 size-4" :stroke-width="1.5" />
            账户安全
          </TabsTrigger>
        </TabsList>

        <!-- 个人资料 -->
        <TabsContent value="profile">
          <Card>
            <CardContent class="space-y-4 p-5">
              <div class="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div class="space-y-1.5">
                  <Label>
                    <Mail class="mr-1 inline size-3.5" :stroke-width="1.5" />
                    邮箱
                  </Label>
                  <Input v-model="profileForm.email" type="email" placeholder="user@example.com" />
                </div>
                <div class="space-y-1.5">
                  <Label>
                    <UserCircle class="mr-1 inline size-3.5" :stroke-width="1.5" />
                    姓名
                  </Label>
                  <Input v-model="profileForm.full_name" placeholder="真实姓名" />
                </div>
                <div class="space-y-1.5">
                  <Label>
                    <Phone class="mr-1 inline size-3.5" :stroke-width="1.5" />
                    手机
                  </Label>
                  <Input v-model="profileForm.phone" placeholder="手机号" />
                </div>
                <div class="space-y-1.5">
                  <Label>
                    <Building2 class="mr-1 inline size-3.5" :stroke-width="1.5" />
                    部门
                  </Label>
                  <Input v-model="profileForm.department" placeholder="所属部门" />
                </div>
              </div>

              <div class="flex justify-end">
                <Button :disabled="savingProfile" @click="saveProfile">
                  <Loader2 v-if="savingProfile" class="size-4 animate-spin" :stroke-width="1.5" />
                  <Save v-else class="size-4" :stroke-width="1.5" />
                  保存资料
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <!-- 账户安全 -->
        <TabsContent value="security">
          <Card>
            <CardContent class="space-y-4 p-5">
              <h3 class="text-sm font-medium">修改密码</h3>
              <div class="space-y-3">
                <div class="space-y-1.5">
                  <Label>当前密码</Label>
                  <Input v-model="passwordForm.old_password" type="password" placeholder="输入当前密码" />
                </div>
                <div class="space-y-1.5">
                  <Label>新密码</Label>
                  <Input v-model="passwordForm.new_password" type="password" placeholder="至少 8 位，含大小写数字" />
                  <PasswordStrengthMeter :password="passwordForm.new_password" />
                </div>
                <div class="space-y-1.5">
                  <Label>确认新密码</Label>
                  <Input v-model="passwordForm.confirm_password" type="password" placeholder="再次输入新密码" />
                </div>
              </div>

              <div class="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground">
                <p class="mb-1 font-medium">密码策略要求：</p>
                <ul class="ml-4 list-disc space-y-0.5">
                  <li>长度不少于 8 位</li>
                  <li>需包含大写字母、小写字母和数字</li>
                  <li>不能与最近使用的密码相同</li>
                </ul>
              </div>

              <div class="flex justify-end">
                <Button :disabled="savingPassword" @click="changePassword">
                  <Loader2 v-if="savingPassword" class="size-4 animate-spin" :stroke-width="1.5" />
                  <KeyRound v-else class="size-4" :stroke-width="1.5" />
                  修改密码
                </Button>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  </div>
</template>
