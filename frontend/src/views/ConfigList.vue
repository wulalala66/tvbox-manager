<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listConfigs, createConfig, deleteConfig, publishConfig, duplicateConfig, getConfigKey } from '../api'

const router = useRouter()
const items = ref([])
const loading = ref(false)
const dialog = ref(false)
const form = ref({ name: '', slug: '', global_spider: '' })
const keyword = ref('')
const sortBy = ref('id')          // id | name | sites | published_at
const sortAsc = ref(true)

async function load() {
  loading.value = true
  try { items.value = await listConfigs() } catch (e) { ElMessage.error(e.message) }
  loading.value = false
}

// 搜索 + 排序（前端 computed，配置数量小无需后端分页）
const filtered = computed(() => {
  let list = items.value
  const kw = keyword.value.trim().toLowerCase()
  if (kw) list = list.filter(c =>
    (c.name || '').toLowerCase().includes(kw) || (c.slug || '').toLowerCase().includes(kw))
  const dir = sortAsc.value ? 1 : -1
  const val = (c) => {
    switch (sortBy.value) {
      case 'name': return (c.name || '').toLowerCase()
      case 'sites': return c.sites?.length || 0
      case 'published_at': return c.published_at || ''
      default: return c.id
    }
  }
  return [...list].sort((a, b) => {
    const va = val(a), vb = val(b)
    return va < vb ? -dir : va > vb ? dir : 0
  })
})

function toggleSort(col) {
  if (sortBy.value === col) sortAsc.value = !sortAsc.value
  else { sortBy.value = col; sortAsc.value = true }
}

function fmtTime(iso) {
  if (!iso) return '—'
  // 后端 UTC isoformat；带 offset（+00:00/Z）可直接解析，naive 才补 Z
  const needsZ = !/[Zz]|[+-]\d{2}:?\d{2}$/.test(iso)
  const d = new Date(needsZ ? iso + 'Z' : iso)
  if (isNaN(d)) return iso
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth()+1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function create() {
  if (!form.value.name) { ElMessage.warning('请填写名称'); return }
  try {
    const c = await createConfig(form.value)
    dialog.value = false
    ElMessage.success('已创建')
    router.push(`/configs/${c.id}`)
  } catch (e) { ElMessage.error(e.message) }
}

async function publish(c) {
  try {
    const r = await publishConfig(c.id)
    ElMessage.success(`已发布：${r.path}（${r.site_count} 站点）`)
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function remove(c) {
  try { await ElMessageBox.confirm(`删除方案「${c.name}」？`, '删除', { type: 'warning' }) } catch { return }
  try { await deleteConfig(c.id); ElMessage.success('已删除'); load() } catch (e) { ElMessage.error(e.message) }
}

async function duplicate(c) {
  try {
    const { value: name } = await ElMessageBox.prompt(`将「${c.name}」复制为新方案，请输入新方案名称：`, '复制方案', {
      inputValue: `${c.name} 副本`, inputValidator: v => !!v?.trim() || '名称不能为空',
    })
    const n = await duplicateConfig(c.id, { name: name.trim() })
    ElMessage.success(`已复制为「${n.name}」（${n.site_count ?? n.sites?.length ?? 0} 站点）`)
    router.push(`/configs/${n.id}`)
  } catch (e) { if (e !== 'cancel' && e?.message !== 'cancel' && e !== false) ElMessage.error(e.message) }
}

async function copyLink(c) {
  if (!c.share_token) { ElMessage.warning('尚未发布，无订阅链接'); return }
  const url = `${location.origin}/configs/${c.id}/download?token=${c.share_token}`
  try { await navigator.clipboard.writeText(url); ElMessage.success('订阅链接已复制') }
  catch { ElMessageBox.alert(url, '订阅链接（请手动复制）', { confirmButtonText: '关闭' }) }
}

// 复制订阅+解密 key（2423 加密方案在 TVBox 端填配置时两者都要）
async function copyFull(c) {
  if (!c.share_token) { ElMessage.warning('尚未发布，无订阅链接'); return }
  let key = null
  try { key = (await getConfigKey(c.id)).key } catch { /* 未加密则无 key */ }
  const url = `${location.origin}/configs/${c.id}/download?token=${c.share_token}`
  const text = key ? `${url}\n解密密钥：${key}` : url
  try { await navigator.clipboard.writeText(text); ElMessage.success(key ? '订阅链接 + 解密密钥已复制' : '订阅链接已复制（未加密）') }
  catch { ElMessageBox.alert(text, '订阅信息（请手动复制）', { customStyle: { whiteSpace: 'pre-line' }, confirmButtonText: '关闭' }) }
}

const qrDialog = ref(false)
const qrDataUrl = ref('')
const qrName = ref('')
async function showQr(c) {
  if (!c.share_token) { ElMessage.warning('尚未发布，无订阅链接'); return }
  const url = `${location.origin}/configs/${c.id}/download?token=${c.share_token}`
  try {
    const QRCode = (await import('qrcode')).default
    qrDataUrl.value = await QRCode.toDataURL(url, { width: 240, margin: 2 })
    qrName.value = c.name
    qrDialog.value = true
  } catch (e) { ElMessage.error('二维码生成失败: ' + e.message) }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索名称 / slug" clearable style="max-width: 240px" @keyup.enter="page = 1" @clear="page = 1" />
      <div style="flex:1"></div>
      <el-button type="primary" @click="dialog = true">＋ 新建方案</el-button>
    </div>

    <div class="mobile-list">
      <el-card v-for="c in filtered" :key="c.id" class="m-card" shadow="never" @click="router.push(`/configs/${c.id}`)">
        <div class="m-head">
          <span class="m-name">{{ c.name }}</span>
          <el-tag v-if="c.published_at" type="success" size="small">已发布</el-tag>
        </div>
        <div class="m-slug">slug: {{ c.slug }} · {{ c.sites?.length || 0 }} 站点</div>
        <div class="m-foot">
          <el-button size="small" type="primary" plain @click.stop="publish(c)">发布</el-button>
          <el-button size="small" @click.stop="copyLink(c)">订阅</el-button>
          <el-button size="small" @click.stop="copyFull(c)">链接+密钥</el-button>
          <el-button size="small" @click.stop="showQr(c)">二维码</el-button>
          <el-button size="small" type="warning" plain @click.stop="duplicate(c)">复制</el-button>
          <el-button size="small" type="danger" plain @click.stop="remove(c)">删除</el-button>
        </div>
      </el-card>
      <el-empty v-if="!filtered.length && !loading" description="没有匹配的配置方案" />
    </div>

    <el-table :data="filtered" v-loading="loading" class="desktop-table" stripe>
      <el-table-column label="名称" min-width="140" sortable :sort-method="null" @click="toggleSort('name')">
        <template #header><span class="sort-hd" @click="toggleSort('name')">名称{{ sortBy==='name' ? (sortAsc?' ↑':' ↓') : '' }}</span></template>
        <template #default="{ row }">{{ row.name }}</template>
      </el-table-column>
      <el-table-column prop="slug" label="slug" min-width="120" />
      <el-table-column min-width="90">
        <template #header><span class="sort-hd" @click="toggleSort('sites')">站点数{{ sortBy==='sites' ? (sortAsc?' ↑':' ↓') : '' }}</span></template>
        <template #default="{ row }">{{ row.sites?.length || 0 }}</template>
      </el-table-column>
      <el-table-column min-width="150">
        <template #header><span class="sort-hd" @click="toggleSort('published_at')">发布时间{{ sortBy==='published_at' ? (sortAsc?' ↑':' ↓') : '' }}</span></template>
        <template #default="{ row }">{{ fmtTime(row.published_at) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.published_at" type="success" size="small">已发布</el-tag>
          <el-tag v-else type="info" size="small">草稿</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="240" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="router.push(`/configs/${row.id}`)">编辑</el-button>
          <el-button size="small" type="success" plain @click="publish(row)">发布</el-button>
          <el-button size="small" @click="copyLink(row)">订阅链接</el-button>
          <el-button size="small" @click="copyFull(row)">链接+密钥</el-button>
          <el-button size="small" @click="showQr(row)">二维码</el-button>
          <el-button size="small" type="warning" plain @click.stop="duplicate(row)">复制</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="新建配置方案" width="94%">
      <el-form label-width="90px">
        <el-form-item label="名称" required>
          <el-input v-model="form.name" placeholder="如：我的 TVBox 配置" />
        </el-form-item>
        <el-form-item label="slug">
          <el-input v-model="form.slug" placeholder="URL 标识，留空自动生成" />
        </el-form-item>
        <el-form-item label="全局 spider">
          <el-input v-model="form.global_spider" placeholder="如 ./jar/spider.jar（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="create">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="qrDialog" :title="`订阅二维码 · ${qrName}`" width="300px" align-center>
      <div style="text-align: center">
        <img v-if="qrDataUrl" :src="qrDataUrl" alt="订阅二维码" style="width: 240px; height: 240px" />
        <p style="color: #909399; font-size: 12px; margin-top: 8px; word-break: break-all">
          TVBox 扫码或输入订阅链接即可导入
        </p>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.desktop-table { display: block; }
.mobile-list { display: none; }
.m-card { margin-bottom: 10px; cursor: pointer; }
.m-head { display: flex; align-items: center; gap: 8px; }
.m-name { font-weight: 600; flex: 1; }
.m-slug { color: #909399; font-size: 12px; margin-top: 4px; }
.m-foot { display: flex; gap: 8px; margin-top: 10px; }
.sort-hd { cursor: pointer; user-select: none; }
.sort-hd:hover { color: #409eff; }

@media (max-width: 768px) {
  .desktop-table { display: none; }
  .mobile-list { display: block; }
}
</style>
