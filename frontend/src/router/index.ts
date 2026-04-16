import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/LoginView.vue'),
    meta: { guest: true },
  },
  {
    path: '/',
    component: () => import('@/components/AppLayout.vue'),
    meta: { auth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('@/views/DashboardView.vue'),
      },
      {
        path: 'stores',
        name: 'Stores',
        component: () => import('@/views/StoreListView.vue'),
      },
      {
        path: 'stores/:id',
        name: 'StoreDetail',
        component: () => import('@/views/StoreDetailView.vue'),
        props: true,
      },
      {
        path: 'products',
        name: 'Products',
        component: () => import('@/views/ProductListView.vue'),
      },
      {
        path: 'bids',
        name: 'Bids',
        component: () => import('@/views/BidConsoleView.vue'),
      },
      {
        path: 'listings',
        name: 'Listings',
        component: () => import('@/views/ListingJobsView.vue'),
      },
      {
        path: 'dropship',
        name: 'Dropship',
        component: () => import('@/views/DropshipJobsView.vue'),
      },
      {
        path: 'library',
        name: 'Library',
        component: () => import('@/views/ProductLibraryView.vue'),
      },
      {
        path: 'warehouse',
        name: 'Warehouse',
        component: () => import('@/views/WarehouseView.vue'),
      },
      {
        path: 'warehouse/print/:storeId/:shipmentId',
        name: 'WarehousePrint',
        component: () => import('@/views/WarehousePrintView.vue'),
        meta: { auth: true },
      },
      {
        path: 'cnexpress',
        name: 'CnExpress',
        component: () => import('@/views/CnExpressView.vue'),
      },
      {
        path: 'profit',
        name: 'ProfitCalc',
        component: () => import('@/views/ProfitCalcView.vue'),
      },
      {
        path: 'notifications',
        name: 'Notifications',
        component: () => import('@/views/NotificationsView.vue'),
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/SettingsView.vue'),
      },
      {
        path: 'admin',
        name: 'Admin',
        component: () => import('@/views/AdminView.vue'),
        meta: { admin: true },
      },
    ],
  },
  {
    path: '/extension/authorize',
    name: 'ExtensionAuth',
    component: () => import('@/views/ExtensionAuthView.vue'),
    meta: { auth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Navigation guard
router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('access_token')

  if (to.meta.auth && !token) {
    return next({ name: 'Login', query: { redirect: to.fullPath } })
  }

  if (to.meta.guest && token) {
    return next('/')
  }

  next()
})

export default router
