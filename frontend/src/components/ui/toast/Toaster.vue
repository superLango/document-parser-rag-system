<script setup lang="ts">
import { Teleport } from 'vue'
import { TransitionGroup } from 'vue'
import { useToastState, toast } from './useToast'
import ToastItem from './Toast.vue'

/**
 * Toaster 容器
 * 固定在视口右上角（桌面）/ 顶部全宽（移动端）
 * 在 App.vue 中挂载一次即可
 */
const state = useToastState()
</script>

<template>
  <Teleport to="body">
    <div
      class="pointer-events-none fixed inset-0 z-[1500] flex flex-col items-end justify-start p-4 sm:p-6"
      aria-live="assertive"
      aria-atomic="true"
    >
      <div class="flex w-full max-w-sm flex-col gap-2">
        <TransitionGroup
          enter-active-class="transition-all duration-300 ease-out"
          enter-from-class="translate-x-8 opacity-0"
          leave-active-class="transition-all duration-200 ease-in absolute"
          leave-to-class="translate-x-8 opacity-0 scale-95"
          move-class="transition-transform duration-200 ease-out"
        >
          <ToastItem
            v-for="t in state.toasts"
            :key="t.id"
            :toast="t"
            @dismiss="toast.dismiss($event)"
          />
        </TransitionGroup>
      </div>
    </div>
  </Teleport>
</template>
