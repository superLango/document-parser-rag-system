<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import BrandLogo from '@/components/brand/BrandLogo.vue'
import { Tooltip } from '@/components/ui/tooltip'
import { navItems } from './navigation'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    isDrawer?: boolean
    class?: string
  }>(),
  { isDrawer: false },
)

const route = useRoute()
const appStore = useAppStore()

const collapsed = computed(() => appStore.sidebarCollapsed && !props.isDrawer)

// 当前激活项
const activePath = computed(() => {
  if (route.path === '/') return '/'
  return `/${route.path.split('/')[1]}`
})
</script>

<template>
  <aside
    :class="
      cn(
        'flex h-full flex-col border-r border-border bg-card text-card-foreground',
        collapsed ? 'w-[var(--sidebar-collapsed-width)]' : 'w-[var(--sidebar-width)]',
        props.isDrawer ? 'w-[var(--sidebar-width)] shadow-2xl' : '',
        'transition-[width] duration-200 ease-out',
        props.class,
      )
    "
  >
    <!-- 品牌区 -->
    <div
      :class="
        cn(
          'flex h-14 items-center gap-2.5 border-b border-border',
          collapsed ? 'justify-center px-0' : 'px-5',
        )
      "
    >
      <BrandLogo :size="28" />
      <span
        v-if="!collapsed"
        class="text-[17px] font-semibold tracking-tight text-foreground"
      >
        Hansight
      </span>
    </div>

    <!-- 导航菜单 -->
    <nav
      :class="cn('flex-1 overflow-y-auto overflow-x-hidden py-3', collapsed ? 'px-2' : 'px-3')"
      aria-label="主导航"
    >
      <ul class="flex flex-col gap-0.5">
        <li v-for="item in navItems" :key="item.path">
          <Tooltip
            v-if="collapsed"
            :side="'right'"
            :delay-ms="200"
          >
            <template #trigger>
              <router-link
                :to="item.path"
                :class="
                  cn(
                    'group flex h-9 items-center rounded-md text-sm transition-colors',
                    collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                    activePath === item.path
                      ? 'bg-primary/10 font-medium text-primary'
                      : 'text-muted-foreground hover:bg-muted hover:text-foreground',
                  )
                "
              >
                <component :is="item.icon" class="size-4 shrink-0" :stroke-width="1.5" />
                <span v-if="!collapsed" class="truncate">{{ item.title }}</span>
              </router-link>
            </template>
            <span>{{ item.title }}</span>
          </Tooltip>

          <router-link
            v-else
            :to="item.path"
            :class="
              cn(
                'group flex h-9 items-center rounded-md text-sm transition-colors',
                collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                activePath === item.path
                  ? 'bg-primary/10 font-medium text-primary'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground',
              )
            "
          >
            <component :is="item.icon" class="size-4 shrink-0" :stroke-width="1.5" />
            <span v-if="!collapsed" class="truncate">{{ item.title }}</span>
          </router-link>
        </li>
      </ul>
    </nav>

    <!-- 底部信息 -->
    <div
      :class="
        cn(
          'border-t border-border py-3 text-xs text-muted-foreground',
          collapsed ? 'px-0 text-center' : 'px-5',
        )
      "
    >
      <span v-if="!collapsed">Hansight 控制台</span>
      <span v-else class="text-[10px]">·</span>
    </div>
  </aside>
</template>
