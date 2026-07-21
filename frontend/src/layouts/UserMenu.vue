<script setup lang="ts">
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { DropdownMenu, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from '@/components/ui/dropdown-menu'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { ChevronDown, LogOut, User as UserIcon } from 'lucide-vue-next'

const router = useRouter()
const auth = useAuthStore()

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <DropdownMenu>
    <template #trigger>
      <button
        type="button"
        class="flex items-center gap-2 rounded-md p-1 pr-2 text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Avatar size="sm" class="bg-primary/10 text-primary">
          <AvatarFallback class="font-medium">{{ auth.userInitial }}</AvatarFallback>
        </Avatar>
        <span class="hidden text-sm font-medium text-foreground sm:inline">
          {{ auth.user?.username || '未登录' }}
        </span>
        <ChevronDown class="size-3.5 text-muted-foreground" :stroke-width="1.5" />
      </button>
    </template>

    <DropdownMenuLabel>
      <div class="flex flex-col gap-0.5">
        <span class="text-sm font-medium text-foreground">{{ auth.user?.username || '未登录' }}</span>
        <span v-if="auth.user?.email" class="text-xs font-normal text-muted-foreground">
          {{ auth.user.email }}
        </span>
      </div>
    </DropdownMenuLabel>
    <DropdownMenuSeparator />
    <DropdownMenuItem>
      <UserIcon class="size-4" :stroke-width="1.5" />
      <span>个人信息</span>
    </DropdownMenuItem>
    <DropdownMenuItem variant="destructive" @select="handleLogout">
      <LogOut class="size-4" :stroke-width="1.5" />
      <span>退出登录</span>
    </DropdownMenuItem>
  </DropdownMenu>
</template>
