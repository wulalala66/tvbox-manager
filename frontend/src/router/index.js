import { createRouter, createWebHashHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue'), meta: { title: '登录', public: true } },
  { path: '/', redirect: '/sites' },
  { path: '/sites', name: 'sites', component: () => import('../views/SiteList.vue'), meta: { title: '站点' } },
  { path: '/sources', name: 'sources', component: () => import('../views/SourceList.vue'), meta: { title: '源库' } },
  { path: '/sources/:id', name: 'source-view', component: () => import('../views/SourceView.vue'), meta: { title: '源详情' } },
  { path: '/configs', name: 'configs', component: () => import('../views/ConfigList.vue'), meta: { title: '配置方案' } },
  { path: '/configs/:id', name: 'config-detail', component: () => import('../views/ConfigDetail.vue'), meta: { title: '方案详情' } },
  { path: '/import', name: 'import', component: () => import('../views/ImportWizard.vue'), meta: { title: '导入' } },
  { path: '/audit', name: 'audit', component: () => import('../views/AuditLog.vue'), meta: { title: '审计日志' } },
  { path: '/:pathMatch(.*)*', redirect: '/sites' }, // 404 兜底：未知路径回站点页
]

const router = createRouter({ history: createWebHashHistory(), routes })

// 路由守卫：未登录跳登录页
router.beforeEach((to) => {
  if (to.meta.public) return true
  if (!localStorage.getItem('tvbox_token')) {
    // 记住目标页，登录后跳回
    if (to.fullPath && to.fullPath !== '/login') sessionStorage.setItem('tvbox_redirect', '#' + to.fullPath)
    return { name: 'login' }
  }
  return true
})

router.afterEach((t) => {
  document.title = (t.meta.title ? t.meta.title + ' · ' : '') + 'TVBox 管理器'
})
export default router
