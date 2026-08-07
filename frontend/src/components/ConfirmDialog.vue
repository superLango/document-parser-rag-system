<script setup lang="ts">
import {
  DialogRoot,
  DialogPortal,
  DialogOverlay,
  DialogContent,
  DialogTitle,
  DialogDescription,
} from 'reka-ui'
import { AlertTriangle, Info } from 'lucide-vue-next'
import { useConfirmState, handleConfirm, handleCancel } from '@/composables/useConfirm'
import { Button } from '@/components/ui/button'

const state = useConfirmState()
</script>

<template>
  <DialogRoot :open="state.open" @update:open="(v) => { if (!v) handleCancel() }">
    <DialogPortal>
      <DialogOverlay
        class="fixed inset-0 z-[1299] bg-foreground/25 backdrop-blur-md data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 duration-300"
      />
      <DialogContent
        class="fixed left-1/2 top-1/2 z-[1300] w-[calc(100%-2rem)] max-w-[420px] -translate-x-1/2 -translate-y-1/2 overflow-hidden rounded-2xl border border-glass-border bg-glass backdrop-blur-2xl saturate-150 shadow-2xl data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=closed]:slide-out-to-left-1/2 data-[state=closed]:slide-out-to-top-[48%] data-[state=open]:slide-in-from-left-1/2 data-[state=open]:slide-in-from-top-[48%] duration-300 ease-[cubic-bezier(0.16,1,0.3,1)]"
      >
        <!-- 顶部渐变色带 -->
        <div
          class="h-[3px] w-full"
          :class="
            state.variant === 'danger'
              ? 'bg-gradient-to-r from-red-500/0 via-red-500/80 to-red-500/0'
              : 'bg-gradient-to-r from-primary/0 via-primary/80 to-primary/0'
          "
        />

        <div class="p-6">
          <!-- 图标 + 标题 + 描述 -->
          <div class="flex items-start gap-4">
            <div
              class="relative flex size-11 shrink-0 items-center justify-center rounded-full"
              :class="
                state.variant === 'danger'
                  ? 'bg-red-500/10 text-red-500'
                  : 'bg-primary/10 text-primary'
              "
            >
              <!-- 图标外圈光晕 -->
              <div
                class="absolute inset-0 rounded-full"
                :class="
                  state.variant === 'danger'
                    ? 'bg-red-500/5 ring-1 ring-red-500/20'
                    : 'bg-primary/5 ring-1 ring-primary/20'
                "
              />
              <AlertTriangle
                v-if="state.variant === 'danger'"
                class="relative size-5"
                :stroke-width="2"
              />
              <Info v-else class="relative size-5" :stroke-width="2" />
            </div>

            <div class="min-w-0 flex-1 space-y-1.5 pt-0.5">
              <DialogTitle class="text-base font-semibold leading-tight tracking-tight">
                {{ state.title }}
              </DialogTitle>
              <DialogDescription
                v-if="state.description"
                class="text-sm leading-relaxed text-muted-foreground"
              >
                {{ state.description }}
              </DialogDescription>
            </div>
          </div>

          <!-- 按钮区域 -->
          <div class="mt-6 flex items-center justify-end gap-3">
            <Button
              variant="outline"
              size="sm"
              class="min-w-[72px]"
              @click="handleCancel"
            >
              {{ state.cancelText }}
            </Button>
            <Button
              :variant="state.variant === 'danger' ? 'destructive' : 'default'"
              size="sm"
              class="min-w-[72px]"
              @click="handleConfirm"
            >
              {{ state.confirmText }}
            </Button>
          </div>
        </div>
      </DialogContent>
    </DialogPortal>
  </DialogRoot>
</template>
