<template>
  <el-container class="app-layout">
    <!-- Sidebar -->
    <aside :class="['app-sidebar', { collapsed: isCollapsed }]">
      <div class="logo" @click="$router.push('/')">
        <span v-if="!isCollapsed" class="logo-text">ProfitLens</span>
        <span v-else class="logo-icon">P</span>
      </div>

      <nav class="sidebar-nav">
        <router-link
          v-for="item in menuItems"
          :key="item.path"
          :to="item.path"
          :class="['nav-item', { active: isActive(item.path) }]"
        >
          <el-icon :size="20"><component :is="item.icon" /></el-icon>
          <span v-if="!isCollapsed" class="nav-label">{{ item.label }}</span>
        </router-link>

        <router-link
          v-if="authStore.isAdmin"
          to="/admin"
          :class="['nav-item', { active: isActive('/admin') }]"
        >
          <el-icon :size="20"><Setting /></el-icon>
          <span v-if="!isCollapsed" class="nav-label">管理后台</span>
        </router-link>
      </nav>
    </aside>

    <!-- Main -->
    <el-container class="main-container">
      <!-- Header -->
      <header class="app-header">
        <div class="header-left">
          <button class="collapse-btn" @click="isCollapsed = !isCollapsed">
            <el-icon :size="18"><Expand v-if="isCollapsed" /><Fold v-else /></el-icon>
          </button>
<!-- HEADER_PLACEHOLDER -->
          <el-select
            v-if="storeStore.stores.length > 0"
            :model-value="storeStore.activeStoreId"
            @change="storeStore.setActiveStore($event as number)"
            placeholder="选择店铺"
            size="default"
            class="store-selector"
            clearable
          >
            <el-option label="全部店铺" :value="0" />
            <el-option
              v-for="s in storeStore.stores"
              :key="s.id"
              :label="s.store_name || s.store_alias || `Store #${s.id}`"
              :value="s.id"
            />
          </el-select>
        </div>

        <div class="header-right">
          <el-badge :value="notifStore.unreadCount" :hidden="notifStore.unreadCount === 0" :max="99">
            <button class="icon-btn" @click="$router.push('/notifications')">
              <el-icon :size="20"><Bell /></el-icon>
            </button>
          </el-badge>

          <el-dropdown trigger="click" @command="handleUserCommand">
            <div class="user-pill">
              <div class="user-avatar">{{ authStore.username.charAt(0).toUpperCase() }}</div>
              <span class="user-name">{{ authStore.username }}</span>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="settings">个人设置</el-dropdown-item>
                <el-dropdown-item command="extension">扩展授权</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <!-- Page -->
      <main class="app-main">
        <transition name="page-fade" mode="out-in">
          <router-view />
        </transition>
      </main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useStoreStore } from '@/stores/store'
import { useNotificationStore } from '@/stores/notification'
import {
  Odometer, Shop, Goods, Timer, Upload, Connection, Search,
  Box, Van, Coin, Setting, Expand, Fold, Bell,
} from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const storeStore = useStoreStore()
const notifStore = useNotificationStore()

const isCollapsed = ref(false)

const menuItems = [
  { path: '/', icon: Odometer, label: '仪表盘' },
  { path: '/stores', icon: Shop, label: '店铺管理' },
  { path: '/products', icon: Goods, label: '商品管理' },
  { path: '/bids', icon: Timer, label: '自动出价' },
  { path: '/listings', icon: Upload, label: 'AI铺货' },
  { path: '/dropship', icon: Connection, label: '关键词铺货' },
  { path: '/library', icon: Search, label: '选品库' },
  { path: '/warehouse', icon: Box, label: '发货中心' },
  { path: '/cnexpress', icon: Van, label: 'CN Express' },
  { path: '/profit', icon: Coin, label: '利润计算' },
]

function isActive(path: string) {
  if (path === '/') return route.path === '/'
  return route.path.startsWith(path)
}

onMounted(() => {
  storeStore.fetchStores()
  notifStore.startPolling()
})

onUnmounted(() => {
  notifStore.stopPolling()
})

function handleUserCommand(cmd: string) {
  if (cmd === 'logout') authStore.logout()
  else if (cmd === 'settings') router.push('/settings')
  else if (cmd === 'extension') router.push('/extension/authorize')
}
</script>

<style scoped lang="scss">
.app-layout { height: 100vh; }

/* --- Sidebar --- */
.app-sidebar {
  width: 240px;
  min-width: 240px;
  height: 100vh;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-right: 1px solid rgba(0, 0, 0, 0.06);
  display: flex;
  flex-direction: column;
  transition: width 0.3s cubic-bezier(0.25, 0.1, 0.25, 1),
              min-width 0.3s cubic-bezier(0.25, 0.1, 0.25, 1);
  overflow: hidden;
  z-index: 10;

  &.collapsed {
    width: 72px;
    min-width: 72px;
  }
}

.logo {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  cursor: pointer;
  flex-shrink: 0;
}

.logo-text {
  font-size: 20px;
  font-weight: 700;
  color: #1d1d1f;
  letter-spacing: -0.02em;
  white-space: nowrap;
}

.logo-icon {
  font-size: 22px;
  font-weight: 700;
  color: #0071e3;
  margin: 0 auto;
}

.sidebar-nav {
  flex: 1;
  padding: 8px 12px;
  overflow-y: auto;
  overflow-x: hidden;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 8px;
  color: #6e6e73;
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  white-space: nowrap;
  transition: all 0.2s cubic-bezier(0.25, 0.1, 0.25, 1);
  position: relative;
  margin-bottom: 2px;

  &:hover {
    background: rgba(0, 0, 0, 0.04);
    color: #1d1d1f;
  }

  &.active {
    background: rgba(0, 113, 227, 0.08);
    color: #0071e3;

    &::before {
      content: '';
      position: absolute;
      left: 0;
      top: 50%;
      transform: translateY(-50%);
      width: 3px;
      height: 20px;
      background: #0071e3;
      border-radius: 0 2px 2px 0;
    }
  }
}

.collapsed .nav-item {
  justify-content: center;
  padding: 10px;
  &::before { display: none; }
}

.nav-label { transition: opacity 0.2s; }

/* --- Header --- */
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 56px;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  box-shadow: 0 1px 0 rgba(0, 0, 0, 0.04);
  flex-shrink: 0;
  z-index: 5;
}

.header-left { display: flex; align-items: center; gap: 16px; }
.header-right { display: flex; align-items: center; gap: 16px; }

.collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border: none;
  background: transparent;
  border-radius: 8px;
  cursor: pointer;
  color: #6e6e73;
  transition: all 0.2s;
  &:hover { background: rgba(0, 0, 0, 0.04); color: #1d1d1f; }
}

.store-selector { width: 200px; }

.icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: none;
  background: transparent;
  border-radius: 50%;
  cursor: pointer;
  color: #6e6e73;
  transition: all 0.2s;
  &:hover { background: rgba(0, 0, 0, 0.04); color: #1d1d1f; }
}

.user-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 12px 4px 4px;
  border-radius: 980px;
  cursor: pointer;
  transition: background 0.2s;
  &:hover { background: rgba(0, 0, 0, 0.04); }
}

.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: linear-gradient(135deg, #0071e3, #34c759);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-name {
  font-size: 14px;
  font-weight: 500;
  color: #1d1d1f;
}

/* --- Main --- */
.main-container { flex: 1; overflow: hidden; display: flex; flex-direction: column; }

.app-main {
  flex: 1;
  background: #f5f5f7;
  padding: 24px;
  overflow-y: auto;
}
</style>
