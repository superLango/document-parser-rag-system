<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import BrandLogo from '@/components/brand/BrandLogo.vue'
import { Tooltip } from '@/components/ui/tooltip'
import { navItems, adminNavItems } from './navigation'
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
const authStore = useAuthStore()

const collapsed = computed(() => appStore.sidebarCollapsed && !props.isDrawer)

const visibleAdminItems = computed(() =>
  authStore.isSuperuser ? adminNavItems : [],
)

const activePath = computed(() => {
  if (route.path === '/') return '/'
  if (route.path.startsWith('/admin')) {
    return adminNavItems.find((i) => route.path.startsWith(i.path))?.path ?? ''
  }
  return `/${route.path.split('/')[1]}`
})
</script>

<template>
  <aside
    :class="
      cn(
        'flex h-full flex-col border-r border-border/60 bg-card/80 backdrop-blur-sm text-card-foreground relative',
        collapsed ? 'w-[var(--sidebar-collapsed-width)]' : 'w-[var(--sidebar-width)]',
        props.isDrawer ? 'w-[var(--sidebar-width)] shadow-2xl' : '',
        'transition-[width] duration-300 ease-[var(--ease-spring)]',
        props.class,
      )
    "
  >
    <!-- 品牌区 -->
    <div
      :class="
        cn(
          'flex h-14 items-center gap-2.5 border-b border-border/40 relative z-10',
          collapsed ? 'justify-center px-0' : 'px-5',
        )
      "
    >
      <div class="relative">
        <BrandLogo :size="28" />
        <div class="absolute -inset-1 rounded-lg bg-primary/10 blur-md opacity-0 group-hover:opacity-100 transition-opacity" />
      </div>
      <span
        v-if="!collapsed"
        class="text-[17px] font-semibold tracking-tight text-foreground transition-all duration-200"
      >
        HansonDOC
      </span>
    </div>

    <!-- 导航菜单 -->
    <nav
      :class="cn('flex-1 overflow-y-auto overflow-x-hidden py-4', collapsed ? 'px-2' : 'px-3')"
      aria-label="主导航"
    >
      <!-- 主导航 -->
      <ul class="flex flex-col gap-0.5">
        <li v-for="item in navItems" :key="item.path" class="relative">
          <!-- 活动指示器条 -->
          <span
            v-if="!collapsed && activePath === item.path"
            class="nav-indicator nav-indicator-active"
          />

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
                    'group relative flex h-10 items-center rounded-lg text-sm transition-all duration-200',
                    collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                    activePath === item.path
                      ? 'bg-primary/10 text-primary font-medium shadow-sm shadow-primary/10'
                      : 'text-muted-foreground hover:bg-muted/80 hover:text-foreground hover:translate-x-0.5',
                  )
                "
              >
                <component
                  :is="item.icon"
                  :stroke-width="activePath === item.path ? 2 : 1.5"
                  :class="cn(
                    'shrink-0 transition-all duration-200',
                    collapsed ? 'size-5' : 'size-[18px]',
                    activePath === item.path ? 'text-primary' : 'group-hover:text-foreground',
                  )"
                />
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
                'group relative flex h-10 items-center rounded-lg text-sm transition-all duration-200',
                collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                activePath === item.path
                  ? 'bg-primary/10 text-primary font-medium shadow-sm shadow-primary/10'
                  : 'text-muted-foreground hover:bg-muted/80 hover:text-foreground hover:translate-x-0.5',
              )
            "
          >
            <component
              :is="item.icon"
              :stroke-width="activePath === item.path ? 2 : 1.5"
              :class="cn(
                'shrink-0 transition-all duration-200',
                collapsed ? 'size-5' : 'size-[18px]',
                activePath === item.path ? 'text-primary' : 'group-hover:text-foreground',
              )"
            />
            <span v-if="!collapsed" class="truncate">{{ item.title }}</span>
          </router-link>
        </li>
      </ul>

      <!-- 管理员导航（仅超管可见） -->
      <template v-if="visibleAdminItems.length > 0">
        <div
          :class="
            cn(
              'mt-6 mb-2 flex items-center gap-2',
              collapsed ? 'justify-center px-0' : 'px-3',
            )
          "
        >
          <div class="h-px flex-1 bg-border/60" />
          <span
            v-if="!collapsed"
            class="text-[10px] font-semibold uppercase tracking-[0.15em] text-muted-foreground/50"
          >
            系统管理
          </span>
          <div v-if="collapsed" class="h-px w-4 bg-border/60" />
        </div>
        <ul class="flex flex-col gap-0.5">
          <li v-for="item in visibleAdminItems" :key="item.path" class="relative">
            <span
              v-if="!collapsed && activePath === item.path"
              class="nav-indicator nav-indicator-active"
            />

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
                      'group relative flex h-10 items-center rounded-lg text-sm transition-all duration-200',
                      collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                      activePath === item.path
                        ? 'bg-primary/10 text-primary font-medium shadow-sm shadow-primary/10'
                        : 'text-muted-foreground hover:bg-muted/80 hover:text-foreground hover:translate-x-0.5',
                    )
                  "
                >
                  <component
                    :is="item.icon"
                    :stroke-width="activePath === item.path ? 2 : 1.5"
                    :class="cn(
                      'shrink-0 transition-all duration-200',
                      collapsed ? 'size-5' : 'size-[18px]',
                      activePath === item.path ? 'text-primary' : 'group-hover:text-foreground',
                    )"
                  />
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
                  'group relative flex h-10 items-center rounded-lg text-sm transition-all duration-200',
                  collapsed ? 'justify-center px-0' : 'gap-3 px-3',
                  activePath === item.path
                    ? 'bg-primary/10 text-primary font-medium shadow-sm shadow-primary/10'
                    : 'text-muted-foreground hover:bg-muted/80 hover:text-foreground hover:translate-x-0.5',
                )
              "
            >
              <component
                :is="item.icon"
                :stroke-width="activePath === item.path ? 2 : 1.5"
                :class="cn(
                  'shrink-0 transition-all duration-200',
                  collapsed ? 'size-5' : 'size-[18px]',
                  activePath === item.path ? 'text-primary' : 'group-hover:text-foreground',
                )"
              />
              <span v-if="!collapsed" class="truncate">{{ item.title }}</span>
            </router-link>
          </li>
        </ul>
      </template>
    </nav>

    <!-- 底部信息 -->
    <div
      :class="
        cn(
          'border-t border-border/40 py-3 text-xs text-muted-foreground/70',
          collapsed ? 'px-0 text-center' : 'px-5',
        )
      "
    >
      <div
        v-if="!collapsed"
        class="flex items-center gap-2"
      >
        <div class="size-1.5 rounded-full bg-emerald-500 shadow-sm shadow-emerald-500/50" />
        <span>HansonDOC 控制台</span>
      </div>
      <div v-else class="flex justify-center">
        <div class="size-1.5 rounded-full bg-emerald-500 shadow-sm shadow-emerald-500/50" />
      </div>
    </div>
  </aside>
</template>
