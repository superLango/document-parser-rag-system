<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import BrandLogo from '@/components/brand/BrandLogo.vue'
import {
  Odometer,
  Document,
  SetUp,
  Collection,
  Share,
  ChatDotRound,
  Fold,
  Expand,
  ArrowDown,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const appStore = useAppStore()

// ---------- 侧边栏导航项 ----------
interface NavItem {
  path: string
  title: string
  icon: unknown
}

const navItems: NavItem[] = [
  { path: '/', title: '仪表盘', icon: Odometer },
  { path: '/documents', title: '文档管理', icon: Document },
  { path: '/schemas', title: '抽取 Schema', icon: SetUp },
  { path: '/terms', title: '术语库', icon: Collection },
  { path: '/knowledge', title: '知识图谱', icon: Share },
  { path: '/qa', title: '智能问答', icon: ChatDotRound },
]

// ---------- 面包屑 ----------
const breadcrumb = computed(() => route.meta.title as string)

// ---------- 当前激活项 ----------
const activePath = computed(() => {
  if (route.path === '/') return '/'
  return `/${route.path.split('/')[1]}`
})

// ---------- 用户下拉操作 ----------
function handleCommand(command: string) {
  if (command === 'logout') {
    auth.logout()
    router.push('/login')
  }
}

// ---------- 响应式自动收缩 ----------
// 屏幕 < 1024px 时自动收缩侧边栏；用户仍可手动展开/收缩
const RESPONSIVE_BREAKPOINT = 1024
let lastWidth = 0

function handleResize() {
  const w = window.innerWidth
  // 仅在跨越断点时改变状态，避免覆盖用户手动操作
  if (lastWidth >= RESPONSIVE_BREAKPOINT && w < RESPONSIVE_BREAKPOINT) {
    appStore.sidebarCollapsed = true
  } else if (lastWidth > 0 && lastWidth < RESPONSIVE_BREAKPOINT && w >= RESPONSIVE_BREAKPOINT) {
    appStore.sidebarCollapsed = false
  }
  lastWidth = w
}

onMounted(() => {
  lastWidth = window.innerWidth
  // 初次加载：小屏默认收缩
  if (lastWidth < RESPONSIVE_BREAKPOINT) {
    appStore.sidebarCollapsed = true
  }
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
})

// 路由切换时，在小屏下自动收起侧边栏（移动端体验）
watch(() => route.path, () => {
  if (window.innerWidth < RESPONSIVE_BREAKPOINT && !appStore.sidebarCollapsed) {
    appStore.sidebarCollapsed = true
  }
})
</script>

<template>
  <div class="layout" :class="{ 'is-collapsed': appStore.sidebarCollapsed }">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <!-- Logo -->
      <div class="logo">
        <BrandLogo :size="30" />
        <span class="logo-text">Hansight</span>
      </div>

      <!-- 导航 -->
      <nav class="nav">
        <template v-for="item in navItems" :key="item.path">
          <el-tooltip
            v-if="appStore.sidebarCollapsed"
            :content="item.title"
            placement="right"
            :show-after="200"
            :hide-after="0"
          >
            <router-link
              :to="item.path"
              class="nav-item"
              :class="{ 'is-active': activePath === item.path }"
            >
              <span class="nav-icon">
                <component :is="item.icon" />
              </span>
              <span class="nav-label">{{ item.title }}</span>
            </router-link>
          </el-tooltip>
          <router-link
            v-else
            :to="item.path"
            class="nav-item"
            :class="{ 'is-active': activePath === item.path }"
          >
            <span class="nav-icon">
              <component :is="item.icon" />
            </span>
            <span class="nav-label">{{ item.title }}</span>
          </router-link>
        </template>
      </nav>

      <!-- 底部版本信息 -->
      <div class="sidebar-footer">
        <span class="mono version">v1.0.0</span>
      </div>
    </aside>

    <!-- 主区域 -->
    <div class="main">
      <!-- 顶栏 -->
      <header class="header">
        <div class="header-left">
          <el-button
            text
            class="collapse-btn"
            :aria-label="appStore.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            @click="appStore.toggleSidebar()"
          >
            <el-icon><Fold v-if="!appStore.sidebarCollapsed" /><Expand v-else /></el-icon>
          </el-button>
          <div class="breadcrumb mono">
            <span class="breadcrumb-sep">/</span>
            <span class="breadcrumb-current">{{ breadcrumb }}</span>
          </div>
        </div>

        <div class="header-right">
          <el-dropdown trigger="click" @command="handleCommand">
            <div class="user-info">
              <div class="user-avatar">{{ auth.userInitial }}</div>
              <span class="user-name">{{ auth.user?.username || '用户' }}</span>
              <el-icon class="user-arrow"><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- 内容区 -->
      <main class="content">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </main>
    </div>
  </div>
</template>

<style scoped lang="scss">
.layout {
  display: flex;
  height: 100vh;
  width: 100%;
  overflow: hidden;
}

// ---------- 侧边栏 ----------
.sidebar {
  width: var(--sidebar-width);
  flex-shrink: 0;
  background-color: var(--bg-sidebar);
  border-right: 1px solid var(--border-base);
  display: flex;
  flex-direction: column;
  transition: width var(--transition-base);
  z-index: var(--z-sidebar);
}

.is-collapsed .sidebar {
  width: var(--sidebar-collapsed-width);
}

.logo {
  height: var(--header-height);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 20px;
  border-bottom: 1px solid var(--border-base);
  overflow: hidden;

  .logo-text {
    font-family: var(--font-sans);
    font-weight: 700;
    font-size: 17px;
    letter-spacing: -0.01em;
    color: var(--text-primary);
    white-space: nowrap;
  }
}

.is-collapsed .logo {
  justify-content: center;
  padding: 0;
  gap: 0;
}

.is-collapsed .logo-text {
  display: none;
}

.nav {
  flex: 1;
  padding: 16px 0;
  overflow-y: auto;
  overflow-x: hidden;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 44px;
  padding: 0 20px;
  margin: 2px 12px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  cursor: pointer;
  position: relative;
  transition: background-color var(--transition-fast), color var(--transition-fast);
  white-space: nowrap;
  text-decoration: none;

  &:hover {
    background-color: var(--bg-surface-hover);
    color: var(--text-primary);
  }

  &.is-active {
    color: var(--accent-primary);
    background-color: var(--accent-primary-light);
    font-weight: 600;

    &::before {
      content: '';
      position: absolute;
      left: -12px;
      top: 50%;
      transform: translateY(-50%);
      width: 3px;
      height: 24px;
      background: var(--accent-primary);
      border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    }
  }

  .nav-icon {
    font-size: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 20px;
  }

  .nav-label {
    font-size: var(--fs-sm);
    font-weight: 500;
  }
}

.is-collapsed {
  .nav-item {
    justify-content: center;
    padding: 0;
    margin: 2px 10px;
  }
  .nav-label {
    display: none;
  }
  .nav-item.is-active::before {
    display: none;
  }
}

.sidebar-footer {
  padding: 12px 20px;
  border-top: 1px solid var(--border-base);

  .version {
    font-size: var(--fs-xs);
    color: var(--text-muted);
  }
}

.is-collapsed .sidebar-footer {
  text-align: center;
  padding: 12px 0;
}

// ---------- 主区域 ----------
.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.header {
  height: var(--header-height);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background-color: var(--bg-surface);
  border-bottom: 1px solid var(--border-base);
  z-index: var(--z-header);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;

  .collapse-btn {
    color: var(--text-secondary);
    padding: 4px;

    &:hover {
      color: var(--accent-primary);
    }
  }

  .breadcrumb {
    font-size: var(--fs-sm);
    color: var(--text-muted);
    display: flex;
    align-items: center;
    gap: 8px;

    .breadcrumb-sep {
      color: var(--text-muted);
    }

    .breadcrumb-current {
      color: var(--text-primary);
      font-weight: 500;
    }
  }
}

.header-right {
  .user-info {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    padding: 4px 8px;
    border-radius: var(--radius-md);
    transition: background-color var(--transition-fast);

    &:hover {
      background-color: var(--bg-surface-hover);
    }
  }

  .user-avatar {
    width: 32px;
    height: 32px;
    border-radius: var(--radius-full);
    background: linear-gradient(135deg, var(--accent-primary), var(--accent-primary-dim));
    color: #FFFFFF;
    font-weight: 600;
    font-size: var(--fs-sm);
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .user-name {
    color: var(--text-primary);
    font-size: var(--fs-sm);
    font-weight: 500;
  }

  .user-arrow {
    color: var(--text-muted);
    font-size: 12px;
  }
}

.content {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

// ---------- 移动端适配：用户名隐藏 ----------
@media (max-width: 640px) {
  .header {
    padding: 0 16px;
  }
  .header-right .user-name {
    display: none;
  }
  .content {
    padding: 16px;
  }
}

// ---------- 路由切换动画 ----------
:deep(.fade-slide-enter-active),
:deep(.fade-slide-leave-active) {
  transition: opacity var(--transition-base), transform var(--transition-base);
}
:deep(.fade-slide-enter-from) {
  opacity: 0;
  transform: translateY(8px);
}
:deep(.fade-slide-leave-to) {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
