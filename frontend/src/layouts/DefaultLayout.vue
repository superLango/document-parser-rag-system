<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'
import {
  Odometer,
  Document,
  View,
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

// 图标映射：meta.icon 名称 -> 组件
const iconMap: Record<string, unknown> = {
  Odometer,
  Document,
  View,
  SetUp,
  Collection,
  Share,
  ChatDotRound,
}

// 侧边栏导航项（与路由 children 对应，过滤隐藏项）
const navItems = computed(() => {
  const parentRoute = router.getRoutes().find((r) => r.path === '/')
  if (!parentRoute?.children) return []
  return parentRoute.children
    .filter((child) => !child.meta?.hidden)
    .map((child) => ({
      path: child.path === '' ? '/' : `/${child.path}`,
      name: String(child.name),
      title: (child.meta?.title as string) || String(child.name),
      icon: (child.meta?.icon as string) || '',
    }))
})

// 面包屑：根据当前路由 meta.title
const breadcrumb = computed(() => route.meta.title as string)

// 当前激活项
const activePath = computed(() => {
  if (route.path === '/') return '/'
  return `/${route.path.split('/')[1]}`
})

// 用户下拉操作
function handleCommand(command: string) {
  if (command === 'logout') {
    auth.logout()
    router.push('/login')
  }
}
</script>

<template>
  <div class="layout" :class="{ 'is-collapsed': appStore.sidebarCollapsed }">
    <!-- 侧边栏 -->
    <aside class="sidebar">
      <!-- Logo -->
      <div class="logo">
        <span class="logo-mark">◈</span>
        <span class="logo-text">DOC<span class="logo-accent">.</span>INTEL</span>
      </div>

      <!-- 导航 -->
      <nav class="nav">
        <router-link
          v-for="item in navItems"
          :key="item.name"
          :to="item.path"
          class="nav-item"
          :class="{ 'is-active': activePath === item.path }"
        >
          <span class="nav-icon">
            <component :is="iconMap[item.icon]" v-if="item.icon" />
          </span>
          <span class="nav-label">{{ item.title }}</span>
        </router-link>
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
      <main class="content blueprint-bg">
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
  background-color: var(--bg-surface);
  border-right: 1px solid var(--border-base);
  display: flex;
  flex-direction: column;
  transition: width var(--transition-base);
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

  .logo-mark {
    color: var(--accent-primary);
    font-size: 20px;
    filter: drop-shadow(0 0 6px rgba(0, 217, 255, 0.5));
  }

  .logo-text {
    font-family: var(--font-mono);
    font-weight: 600;
    font-size: 16px;
    letter-spacing: 0.05em;
    color: var(--text-primary);
    white-space: nowrap;
  }

  .logo-accent {
    color: var(--accent-primary);
  }
}

.is-collapsed .logo-text {
  display: none;
}

.nav {
  flex: 1;
  padding: 16px 0;
  overflow-y: auto;
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
  transition: all var(--transition-fast);
  white-space: nowrap;

  &:hover {
    background-color: var(--bg-surface-hover);
    color: var(--text-primary);
  }

  &.is-active {
    color: var(--accent-primary);
    background-color: rgba(0, 217, 255, 0.08);

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
      box-shadow: 0 0 12px rgba(0, 217, 255, 0.6);
    }
  }

  .nav-icon {
    font-size: 18px;
    display: flex;
    align-items: center;
    flex-shrink: 0;
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
  }
  .nav-label {
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
    color: var(--bg-base);
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
</style>
