<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http from './api/http'

const route = useRoute()
const router = useRouter()
const active = computed(() => route.path)
const titles = { '/sites': '站点管理', '/sources': '源库', '/configs': '配置方案', '/import': '导入', '/audit': '审计日志' }

async function logout() {
  try { await http.post('/logout') } catch { /* ignore */ }
  localStorage.removeItem('tvbox_token')
  router.push('/login')
}

// ---- 备份 / 恢复 / 改密 ----
const backupLoading = ref(false)
async function downloadBackup() {
  backupLoading.value = true
  try {
    const resp = await fetch('/backup', { headers: { Authorization: 'Bearer ' + localStorage.getItem('tvbox_token') } })
    if (!resp.ok) throw new Error('备份失败 HTTP ' + resp.status)
    const blob = await resp.blob()
    const cd = resp.headers.get('Content-Disposition') || ''
    const m = /filename="([^"]+)"/.exec(cd)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = m ? m[1] : 'tvbox_backup.zip'
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('备份已下载')
  } catch (e) { ElMessage.error(e.message) }
  backupLoading.value = false
}

const restoreDialog = ref(false)
const restoreLoading = ref(false)
const restoreFile = ref(null)
const uploadRef = ref()
function openRestore() {
  restoreFile.value = null
  restoreDialog.value = true
  setTimeout(() => uploadRef.value?.clearFiles(), 100)
}
function onRestorePick(file) {
  restoreFile.value = file.raw
  return false // 阻止 el-upload 自动上传
}
async function doRestore() {
  if (!restoreFile.value) return ElMessage.warning('请先选择备份 zip 文件')
  try {
    await ElMessageBox.confirm(
      '恢复将覆盖当前全部数据（站点/源/配置）并刷新页面，系统会先自动留存还原前快照。确定继续？',
      '危险操作', { type: 'warning', confirmButtonText: '确认恢复', cancelButtonText: '取消' })
  } catch { return }
  restoreLoading.value = true
  try {
    const fd = new FormData()
    fd.append('file', restoreFile.value)
    const resp = await fetch('/backup/restore', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + localStorage.getItem('tvbox_token') },
      body: fd,
    })
    const data = await resp.json()
    if (!resp.ok) throw new Error(data.detail || '恢复失败 HTTP ' + resp.status)
    restoreDialog.value = false
    await ElMessageBox.alert(`恢复成功：站点 ${data.counts.site} / 源 ${data.counts.source} / 方案 ${data.counts.config}，文件 ${data.restored_files} 个。`, '完成', { confirmButtonText: '刷新页面' })
    location.reload()
  } catch (e) { ElMessage.error(e.message) }
  restoreLoading.value = false
}

const pwDialog = ref(false)
const pwForm = ref({ old_password: '', new_password: '', confirm: '' })
const pwLoading = ref(false)
function openPwDialog() {
  pwForm.value = { old_password: '', new_password: '', confirm: '' }
  pwDialog.value = true
}
async function doChangePw() {
  const f = pwForm.value
  if (!f.old_password || !f.new_password) return ElMessage.warning('请填写完整')
  if (f.new_password.length < 8) return ElMessage.warning('新密码至少 8 位')
  if (f.new_password !== f.confirm) return ElMessage.warning('两次输入的新密码不一致')
  pwLoading.value = true
  try {
    await http.post('/change-password', { old_password: f.old_password, new_password: f.new_password })
    pwDialog.value = false
    ElMessage.success('密码已修改，请重新登录')
    localStorage.removeItem('tvbox_token')
    router.push('/login')
  } catch (e) { ElMessage.error(e.message || '修改失败') }
  pwLoading.value = false
}
</script>

<template>
  <div class="layout">
    <!-- 桌面端侧边栏 -->
    <aside class="sidebar">
      <div class="logo">📦 TVBox 管理器
        <el-button size="small" text class="logout-btn" @click="logout">退出</el-button>
      </div>
      <nav>
        <router-link to="/sites" class="nav-item" :class="{ on: active.startsWith('/sites') }">🌐 站点管理</router-link>
        <router-link to="/sources" class="nav-item" :class="{ on: active.startsWith('/sources') }">📁 源库</router-link>
        <router-link to="/configs" class="nav-item" :class="{ on: active.startsWith('/configs') }">🗂️ 配置方案</router-link>
        <router-link to="/import" class="nav-item" :class="{ on: active.startsWith('/import') }">📥 导入</router-link>
        <router-link to="/audit" class="nav-item" :class="{ on: active.startsWith('/audit') }">📋 审计日志</router-link>
        <div class="nav-sep"></div>
        <a href="javascript:void 0" class="nav-item" @click="downloadBackup">
          💾 备份数据<span v-if="backupLoading" class="nav-spin">…</span></a>
        <a href="javascript:void 0" class="nav-item" @click="openRestore">♻️ 恢复备份</a>
        <a href="javascript:void 0" class="nav-item" @click="openPwDialog">🔑 修改密码</a>
      </nav>
    </aside>

    <div class="main">
      <!-- 移动端顶栏 -->
      <header class="mobile-bar">
        <div class="m-title">{{ titles[active] || 'TVBox 管理器' }}
          <el-button size="small" text class="logout-btn" @click="logout">退出</el-button>
        </div>
        <div class="m-navs">
          <router-link to="/sites" class="m-nav" :class="{ on: active.startsWith('/sites') }">站点</router-link>
          <router-link to="/sources" class="m-nav" :class="{ on: active.startsWith('/sources') }">源库</router-link>
          <router-link to="/configs" class="m-nav" :class="{ on: active.startsWith('/configs') }">方案</router-link>
          <router-link to="/import" class="m-nav" :class="{ on: active.startsWith('/import') }">导入</router-link>
          <a href="javascript:void 0" class="m-nav" @click="downloadBackup">备份</a>
          <a href="javascript:void 0" class="m-nav" @click="openRestore">恢复</a>
        </div>
      </header>

      <main class="content">
        <router-view />
      </main>
    </div>

    <el-dialog v-model="restoreDialog" title="♻️ 恢复备份" width="420px">
      <el-alert type="warning" :closable="false" show-icon
                title="恢复将覆盖当前全部数据" description="站点、源库、配置方案都会被备份包内容替换。系统会先自动留存还原前快照（data/backups/pre_restore_*）。" />
      <el-upload ref="uploadRef" drag accept=".zip" :limit="1" :auto-upload="false"
                 :on-change="onRestorePick" style="margin-top: 14px">
        <div style="padding: 18px 0">将备份 zip 拖到此处，或<em>点击选择</em></div>
      </el-upload>
      <template #footer>
        <el-button @click="restoreDialog = false">取消</el-button>
        <el-button type="danger" :loading="restoreLoading" @click="doRestore">确认恢复</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="pwDialog" title="修改密码" width="360px">
      <el-form label-width="80px">
        <el-form-item label="当前密码">
          <el-input v-model="pwForm.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwForm.new_password" type="password" show-password placeholder="至少 8 位" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="pwForm.confirm" type="password" show-password @keyup.enter="doChangePw" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwDialog = false">取消</el-button>
        <el-button type="primary" :loading="pwLoading" @click="doChangePw">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.layout { display: flex; height: 100%; }
.sidebar {
  width: 200px; flex-shrink: 0; background: #1d2b3a; color: #cfd8e3;
  display: flex; flex-direction: column; padding: 16px 0;
}
.logo { font-weight: 700; font-size: 16px; padding: 0 18px 18px; color: #fff; display: flex; align-items: center; justify-content: space-between; }
.logout-btn { color: #9fb3c8; }
.nav-item {
  display: block; padding: 11px 18px; color: #cfd8e3; text-decoration: none;
  font-size: 14px; border-left: 3px solid transparent;
}
.nav-item.on { background: #16222e; color: #409eff; border-left-color: #409eff; }
.nav-item:hover { background: #24344a; }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.content { flex: 1; overflow-y: auto; }

.mobile-bar { display: none; }

@media (max-width: 768px) {
  .layout { flex-direction: column; }
  .sidebar { display: none; }
  .mobile-bar {
    display: block; background: #1d2b3a; padding: 10px 12px;
    position: sticky; top: 0; z-index: 100;
  }
  .m-title { color: #fff; font-weight: 700; margin-bottom: 8px; font-size: 15px; display: flex; align-items: center; justify-content: space-between; }
  .logout-btn { color: #9fb3c8; }
  .m-navs { display: flex; gap: 6px; }
  .m-nav {
    flex: 1; text-align: center; padding: 7px 0; border-radius: 6px;
    color: #cfd8e3; text-decoration: none; font-size: 13px; background: #24344a;
  }
  .m-nav.on { background: #409eff; color: #fff; }
}
</style>
