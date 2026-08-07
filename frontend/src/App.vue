<script setup lang="ts">
import { onMounted } from 'vue'
import { TooltipProvider } from 'reka-ui'
import { useAuthStore } from '@/stores/auth'
import { Toaster } from '@/components/ui/toast'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const auth = useAuthStore()

onMounted(() => {
  if (auth.isAuthenticated && !auth.user) {
    auth.fetchUser()
  }
})
</script>

<template>
  <TooltipProvider :delay-duration="300">
    <div class="min-h-screen bg-background">
      <router-view v-slot="{ Component }">
        <component :is="Component" />
      </router-view>
    </div>
    <Toaster />
    <ConfirmDialog />
  </TooltipProvider>
</template>
