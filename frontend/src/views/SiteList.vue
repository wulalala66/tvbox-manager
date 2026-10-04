<script setup>
import { ref, onMounted, reactive, computed, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listSites, createSite, updateSite, deleteSite, checkSite, checkAllSites,
  batchDeleteSites, batchEnableSites, batchAddConfigSites, batchTagSites, listConfigs, listSources,
  importSites, exportSites,
  healthSummary as fetchHealthSummary, healthHistory as fetchHealthHistory, checkProgress as fetchCheckProgress } from '../api'

const loading = ref(false)
const sites = ref([])
const page = ref(1)
const pageSize = ref(30)
const pagedSites = computed(() => filteredSites.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const q = ref('')
const dialog = ref(false)
const editing = ref(null)
const saving = ref(false)

const form = reactive({
  key: '', name: '', site_type: 3, api: '', ext: '', jar: '',
  searchable: true, changeable: true, hide: 0, timeout: null,
  quickSearch: true, indexs: 0, click: '', playUrl: '', categories: '', header: '',
  style_type: '', style_ratio: null,
})

// 从源库选源 → 自动填 api（日常加站一键引用源文件）
const sourceOptions = ref([])
async function loadSourceOptions() {
  try {
    const d = await listSources()  // 响应拦截已剥 axios 层：d 即数据
    sourceOptions.value = Array.isArray(d) ? d : (d?.items || [])
  } catch { sourceOptions.value = [] }
}
function pickSource(src) {
  form.api = `./${src.kind}/${src.filename}`
  ElMessage.success(`已填入 ./${src.kind}/${src.filename}`)
}
loadSourceOptions()

// ---- ext 编辑器：JSON 状态徽标 + 格式化/压缩（与方案全局字段同款体验）----
const extStatus = computed(() => {
  const t = (form.ext || '').trim()
  if (!t) return 'empty'
  if (!/^[{[]/.test(t)) return 'string'   // 非 { [ 开头视为纯字符串 ext
  try { JSON.parse(t); return 'json' } catch { return 'invalid' }
})
function formatExt() {
  if (extStatus.value === 'json') form.ext = JSON.stringify(JSON.parse(form.ext), null, 2)
}
function minifyExt() {
  if (extStatus.value === 'json') form.ext = JSON.stringify(JSON.parse(form.ext))
}

function openCreate() {
  editing.value = null
  Object.assign(form, { key: '', name: '', site_type: 3, api: '', ext: '', jar: '', searchable: true, changeable: true, hide: 0, timeout: null,
    quickSearch: true, indexs: 0, click: '', playUrl: '', categories: '', header: '', style_type: '', style_ratio: null })
  dialog.value = true
}

// 克隆：复用整份表单（key 加 -copy 后缀待改），仅 key 需要改
function cloneSite(s) {
  editing.value = null
  const extRaw = typeof s.ext === 'string' ? s.ext : JSON.stringify(s.ext ?? '')
  let extShown = extRaw
  if (extRaw && /^[{[]/.test(extRaw.trim())) {
    try { extShown = JSON.stringify(JSON.parse(extRaw), null, 2) } catch { /* 保持原样 */ }
  }
  Object.assign(form, {
    key: s.key + '_copy', name: s.name + ' 副本', site_type: s.site_type, api: s.api || '',
    ext: extShown, jar: s.jar || '',
    searchable: s.extra?.searchable !== false, changeable: s.extra?.changeable !== false,
    hide: s.extra?.hide || 0, timeout: s.extra?.timeout || null,
    quickSearch: s.extra?.quickSearch !== false, indexs: s.extra?.indexs || 0,
    click: s.extra?.click || '', playUrl: s.extra?.playUrl || '',
    categories: Array.isArray(s.extra?.categories) ? s.extra.categories.join(',') : '',
    header: s.extra?.header ? JSON.stringify(s.extra.header) : '',
    style_type: s.extra?.style?.type || '', style_ratio: s.extra?.style?.ratio ?? null,
  })
  dialog.value = true
  ElMessage.info('已载入站点副本，请修改 key 后保存')
}

function openEdit(s) {
  editing.value = s
  const extRaw = typeof s.ext === 'string' ? s.ext : JSON.stringify(s.ext ?? '')
  // 对象/数组型 ext 美化为缩进 JSON，便于编辑（保存时 JSON.parse 回对象）
  let extShown = extRaw
  if (extRaw && /^[{[]/.test(extRaw.trim())) {
    try { extShown = JSON.stringify(JSON.parse(extRaw), null, 2) } catch { /* 保持原样 */ }
  }
  Object.assign(form, {
    key: s.key, name: s.name, site_type: s.site_type, api: s.api || '',
    ext: extShown,
    jar: s.jar || '', searchable: s.extra?.searchable !== false,
    changeable: s.extra?.changeable !== false, hide: s.extra?.hide || 0,
    timeout: s.extra?.timeout || null,
    quickSearch: s.extra?.quickSearch !== false, indexs: s.extra?.indexs || 0,
    click: s.extra?.click || '', playUrl: s.extra?.playUrl || '',
    categories: Array.isArray(s.extra?.categories) ? s.extra.categories.join(',') : '',
    header: s.extra?.header ? JSON.stringify(s.extra.header) : '',
    style_type: s.extra?.style?.type || '', style_ratio: s.extra?.style?.ratio ?? null,
  })
  dialog.value = true
}

async function save() {
  if (!form.key || !form.name) return ElMessage.warning('key 和名称必填')
  // 类型↔api 联动校验（防呆：保存前拦下最常见的填错组合）
  // type=3 合法形态：csp_ 类名 / ./py|./js 相对路径源文件 / http 远程 spider 接口
  const apiTrim = (form.api || '').trim()
  if (form.site_type === 3 && !apiTrim.startsWith('csp_') && !apiTrim.startsWith('./py/') && !apiTrim.startsWith('./js/') && !/^https?:\/\//.test(apiTrim))
    return ElMessage.error('Spider 类型（3）的 api 应为 csp_Xyz、./py/xx.py、./js/xx.js 或 http(s):// 地址')
  if ((form.site_type === 0 || form.site_type === 1) && !/^https?:\/\//.test(apiTrim))
    return ElMessage.error('XML/JSON 类型（0/1）的 api 必须是 http(s):// 接口地址')
  saving.value = true
  // FongMi 站点级扩展字段（写入 extra，编译时并入产物 site 项）
  if (form.header && form.header.trim()) {
    try { JSON.parse(form.header) } catch {
      saving.value = false
      return ElMessage.error('header 不是合法 JSON 对象，请修正后再保存')
    }
  }
  const extra = {
    searchable: form.searchable, changeable: form.changeable, hide: form.hide,
    quickSearch: form.quickSearch,
    ...(form.indexs ? { indexs: form.indexs } : {}),
    ...(form.timeout ? { timeout: form.timeout } : {}),
    ...(form.click.trim() ? { click: form.click.trim() } : {}),
    ...(form.playUrl.trim() ? { playUrl: form.playUrl.trim() } : {}),
    ...(form.categories.trim() ? { categories: form.categories.split(/[,，]/).map(x => x.trim()).filter(Boolean) } : {}),
    ...(form.header.trim() ? { header: JSON.parse(form.header) } : {}),
    ...(form.style_type || form.style_ratio ? { style: { ...(form.style_type ? { type: form.style_type } : {}), ...(form.style_ratio ? { ratio: form.style_ratio } : {}) } } : {}),
  }
  const body = {
    key: form.key, name: form.name, site_type: form.site_type, api: form.api,
    extra,
  }
  if (form.ext) {
    body.ext = form.ext
    try { body.ext = JSON.parse(form.ext) } catch {
      // 语法错误的 JSON 不回传对象，但也不静默落库坏串——提示后中止
      if (extStatus.value === 'invalid') {
        saving.value = false
        return ElMessage.error('ext 不是合法 JSON，请修正后再保存（纯字符串可正常保存）')
      }
    }
  }
  if (form.jar) body.jar = form.jar
  try {
    if (editing.value) {
      await updateSite(editing.value.id, body)
      ElMessage.success('已保存')
    } else {
      await createSite(body)
      ElMessage.success('已创建')
    }
    dialog.value = false
    load()
  } catch (e) { ElMessage.error(e.message) }
  saving.value = false
}

// 测活状态筛选（纯前端过滤当前页数据）
const healthFilter = ref('all')
// 标签筛选（多选，取并集：命中任一标签即显示）
const tagFilter = ref([])
const allTags = computed(() => {
  const t = new Set()
  for (const s of sites.value) for (const tag of (s.tags || [])) t.add(tag)
  return [...t].sort()
})
const filteredSites = computed(() => {
  let list = sites.value
  if (tagFilter.value.length) list = list.filter(s => (s.tags || []).some(t => tagFilter.value.includes(t)))
  if (healthFilter.value === 'all') return list
  return list.filter(s => {
    const r = s.last_test_result
    if (healthFilter.value === 'untested') return !r
    if (healthFilter.value === 'ok') return r && r.ok
    if (healthFilter.value === 'fail') return r && !r.ok
    return true
  })
})

watch(filteredSites, () => { if ((page.value - 1) * pageSize.value >= filteredSites.value.length) page.value = 1 })

let loadSeq = 0
async function load() {
  const seq = ++loadSeq
  loading.value = true
  try {
    sites.value = await listSites(q.value ? { q: q.value } : {})
  } catch (e) { ElMessage.error(e.message) }
  if (seq !== loadSeq) return
  loading.value = false
}

let searchTimer = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(load, 300)
}

async function toggle(s) {
  try {
    await updateSite(s.id, { enabled: s.enabled })
    ElMessage.success(s.enabled ? '已启用' : '已停用')
  } catch (e) { ElMessage.error(e.message); s.enabled = !s.enabled }
}

async function remove(s) {
  try {
    await ElMessageBox.confirm(`确认删除站点「${s.name}」？`, '删除', { type: 'warning' })
  } catch { return }
  try {
    await deleteSite(s.id)
    ElMessage.success('已删除')
    load()
  } catch (e) { ElMessage.error(e.message) }
}

const typeLabel = { 0: 'XML', 1: 'JSON', 3: 'Spider', 4: '扩展JSON' }
const typeColor = { 0: 'info', 1: '', 3: 'success', 4: 'warning' }

// 测活
const checking = ref(new Set())
const health = ref(null)
const historyPoints = ref([])
async function loadHealth() {
  const d = await fetchHealthSummary()
  health.value = d.data ?? d
  try {
    const h = await fetchHealthHistory()
    historyPoints.value = (h.data ?? h).points || []
  } catch (e) { /* 趋势非关键，失败静默 */ }
}
function healthTag(s) {
  const r = s.last_test_result
  if (!r) return null
  return r.ok ? { type: 'success', text: '正常' } : { type: 'danger', text: '失效' }
}
function timeAgo(ts) {
  const diff = Date.now() - new Date(ts).getTime()
  if (isNaN(diff) || diff < 0) return ''
  const m = Math.floor(diff / 60000)
  if (m < 1) return '刚刚'
  if (m < 60) return `${m} 分钟前`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时前`
  return `${Math.floor(h / 24)} 天前`
}
async function doCheck(s) {
  checking.value = new Set(checking.value).add(s.id)
  try {
    const r = await checkSite(s.id)
    s.last_test_result = r
    ElMessage[r.ok ? 'success' : 'warning'](`${s.name}: ${r.message}`)
  } catch (e) { ElMessage.error(e.message) }
  const next = new Set(checking.value); next.delete(s.id); checking.value = next
}
const checkingAll = ref(false)
// 趋势点时间：后端存 UTC ISO（带 +00:00），转本地 "MM-DD HH:mm" 显示
function fmtTrendTime(iso) {
  const d = new Date(iso)
  if (isNaN(d)) return iso.slice(5, 16).replace('T', ' ')
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
// ---- 趋势迷你折线（纯 SVG，无新依赖）：ok 比率曲线 ----
const TREND_W = 288, TREND_H = 72
const trendSeries = computed(() => {
  const pts = historyPoints.value.slice(-20)
  return pts.map((p, i) => ({
    ...p,
    ratio: p.total > 0 ? p.ok / p.total : null,
    x: pts.length > 1 ? (i / (pts.length - 1)) * TREND_W : TREND_W / 2,
  }))
})
const trendPath = computed(() => {
  const pts = trendSeries.value.filter(p => p.ratio != null)
  if (pts.length < 2) return ''
  return pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${(TREND_H - p.ratio * (TREND_H - 8) - 4).toFixed(1)}`).join(' ')
})
const trendArea = computed(() => {
  if (!trendPath.value) return ''
  const pts = trendSeries.value.filter(p => p.ratio != null)
  return `${trendPath.value} L${pts[pts.length - 1].x.toFixed(1)},${TREND_H} L${pts[0].x.toFixed(1)},${TREND_H} Z`
})
const checkProg = ref(null)   // {running, done, total, ok, fail}
let _progTimer = null
function startProg() {
  checkProg.value = { running: true, done: 0, total: 0, ok: 0, fail: 0 }
  _progTimer = setInterval(async () => {
    try {
      const d = await fetchCheckProgress()
      const p = d.data ?? d
      checkProg.value = { running: p.running, done: p.done, total: p.total, ok: p.ok, fail: p.fail }
    } catch { /* ignore */ }
  }, 1200)
}
function stopProg() {
  if (_progTimer) { clearInterval(_progTimer); _progTimer = null }
  setTimeout(() => { checkProg.value = null }, 1500)
}
async function recheckFailed() {
  if (checkingAll.value) return
  ElMessage.info(`正在重测 ${health.value?.fail ?? '全部'} 个失败站点…`)
  await doCheckAll('fail')
}
async function doCheckAll(scope) {
  checkingAll.value = true
  startProg()
  try {
    const d = await checkAllSites(scope ? { scope } : {})
    ElMessage.success(`测活完成：${d.ok}/${d.total} 正常`)
    load()
    loadHealth()
  } catch (e) { ElMessage.error(e.message) }
  checkingAll.value = false
  stopProg()
}

// ---- 批量选择与操作 ----
const selected = ref([])
const tableRef = ref(null)
function onSelChange(rows) { selected.value = rows.map(r => r.id) }
const allSelected = computed(() => pagedSites.value.length > 0 && pagedSites.value.every(s => selected.value.includes(s.id)))
function toggleAll(v) {
  if (!tableRef.value) return
  tableRef.value.toggleAllSelection()
}

async function batchDelete() {
  if (!selected.value.length) return ElMessage.warning('先勾选站点')
  try {
    await ElMessageBox.confirm(`确认删除选中的 ${selected.value.length} 个站点？（方案关联一并清除）`, '批量删除', { type: 'warning' })
  } catch { return }
  try {
    const d = await batchDeleteSites(selected.value)
    ElMessage.success(`已删除 ${d.deleted.length} 个${d.missing.length ? '，' + d.missing.length + ' 个不存在' : ''}`)
    selected.value = []
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function batchToggle(enabled) {
  if (!selected.value.length) return ElMessage.warning('先勾选站点')
  try {
    const d = await batchEnableSites(selected.value, enabled)
    ElMessage.success(`已${enabled ? '启用' : '停用'} ${d.updated} 个`)
    load()
  } catch (e) { ElMessage.error(e.message) }
}

const configs = ref([])
listConfigs().then(d => { configs.value = d }).catch(() => {})

// ---- 批量导入 / 导出 ----
const impDialog = ref(false)
const impText = ref('')
const impBusy = ref(false)
async function doImport() {
  if (!impText.value.trim()) return ElMessage.warning('请粘贴要导入的站点行')
  impBusy.value = true
  try {
    const r = await importSites({ text: impText.value })
    if (r.errors?.length) ElMessage.warning(`导入 ${r.created} 个，跳过 ${r.skipped} 个；${r.errors.length} 行格式错误`)
    else ElMessage.success(`导入 ${r.created} 个，跳过 ${r.skipped} 个`)
    impDialog.value = false
    impText.value = ''
    load()
  } catch (e) { ElMessage.error(e.message) } finally { impBusy.value = false }
}
async function doExport() {
  try {
    const r = await exportSites(selected.value.length ? selected.value : null)
    const blob = new Blob([r.text], { type: 'text/plain;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'sites_export.txt'
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success(`已导出 ${r.count} 个站点`)
  } catch (e) { ElMessage.error(e.message) }
}
const addCfgDialog = ref(false)
const addCfgId = ref(null)
function openBatchAddToConfig() {
  if (!selected.value.length) return ElMessage.warning('先勾选站点')
  addCfgId.value = null
  addCfgDialog.value = true
}
async function doBatchAddToConfig() {
  if (!addCfgId.value) return ElMessage.warning('请选择方案')
  try {
    const d = await batchAddConfigSites(Number(addCfgId.value), selected.value)
    addCfgDialog.value = false
    ElMessage.success(`已加入「${(configs.value.find(c => c.id === Number(addCfgId.value)) || {}).name || addCfgId.value}」：新增 ${d.added.length} 个${d.skipped.length ? '，跳过 ' + d.skipped.length + ' 个（已在方案中）' : ''}`)
  } catch (e) { ElMessage.error(e.message) }
}

async function batchTag() {
  if (!selected.value.length) return ElMessage.warning('先勾选站点')
  try {
    const { value } = await ElMessageBox.prompt(
      '给选中的 ' + selected.value.length + ' 个站点追加标签（英文逗号分隔）：',
      '批量设置标签', { inputValue: '', inputPlaceholder: '例如: 4k,直播,常用' })
    const add = value.split(/[,,]/).map(s => s.trim()).filter(Boolean)
    const d = await batchTagSites({ ids: selected.value, add_tags: add })
    ElMessage.success('已更新 ' + d.updated + ' 个站点的标签')
    load()
  } catch (e) { if (e !== 'cancel' && e?.message) ElMessage.error(e.message) }
}

onMounted(() => {
  // 支持从方案页站点名跳转过来：/sites?q=名称
  const rq = useRoute().query.q
  if (rq) q.value = String(rq)
  load(); loadHealth()
})
</script>

<template>
  <div class="page">
    <div class="toolbar">
      <el-input v-model="q" placeholder="搜索 key / 名称" clearable style="width: 220px" @input="onSearchInput" @keyup.enter="load" @clear="load" />
      <el-button @click="load">搜索</el-button>
      <el-select v-model="tagFilter" multiple collapse-tags collapse-tags-tooltip placeholder="按标签筛选" clearable
                 style="width: 200px" size="default">
        <el-option v-for="t in allTags" :key="t" :label="t" :value="t" />
      </el-select>
      <div style="flex:1"></div>
      <el-button @click="impDialog = true">批量导入</el-button>
      <el-button @click="doExport">导出</el-button>
      <el-button :loading="checkingAll" @click="doCheckAll()">批量测活</el-button>
      <el-dropdown @command="c => doCheckAll(c)">
        <el-button :loading="checkingAll">筛选测活 ▾</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="untested">只测未测的</el-dropdown-item>
            <el-dropdown-item command="fail">只重测失败的</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button type="primary" @click="openCreate">＋ 新建站点</el-button>
    </div>

    <!-- 健康摘要（体验增强） -->
    <div v-if="health" class="health-bar">
      <el-tag type="success" effect="plain">正常 {{ health.ok }}</el-tag>
      <el-tag v-if="health.fail" type="danger" effect="plain" class="fail-click" @click="recheckFailed" :disabled="checkingAll">
        失效 {{ health.fail }}（点击重测）</el-tag>
      <el-tag v-if="health.untested" type="info" effect="plain">未测 {{ health.untested }}</el-tag>
      <span v-for="(n, reason) in health.fail_reasons || {}" :key="reason" class="fail-reason" title="点击重测失败站点">{{ reason }} × {{ n }}</span>
      <span class="health-total">共 {{ health.total }} 站</span>
      <el-popover placement="bottom-end" width="320" trigger="click">
        <template #reference>
          <el-button link type="primary" size="small">📈 趋势</el-button>
        </template>
        <div v-if="historyPoints.length > 1" class="trend-box">
          <svg v-if="trendPath" class="trend-svg" :viewBox="`0 0 ${TREND_W} ${TREND_H}`" width="100%" height="72">
            <defs>
              <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="#67c23a" stop-opacity="0.35" />
                <stop offset="100%" stop-color="#67c23a" stop-opacity="0.02" />
              </linearGradient>
            </defs>
            <path :d="trendArea" fill="url(#trendFill)" />
            <path :d="trendPath" fill="none" stroke="#67c23a" stroke-width="1.5" stroke-linejoin="round" />
            <circle v-for="(p, i) in trendSeries.filter(p => p.ratio != null)" :key="p.t"
                    :cx="p.x" :cy="TREND_H - p.ratio * (TREND_H - 8) - 4" r="2.5" fill="#67c23a" />          </svg>
          <div v-for="pt in historyPoints.slice(-8).reverse()" :key="pt.t" class="trend-row">
            <span class="trend-t">{{ fmtTrendTime(pt.t) }}</span>
            <el-tag size="small" type="success" effect="plain">正常 {{ pt.ok }}</el-tag>
            <el-tag v-if="pt.fail" size="small" type="danger" effect="plain">失效 {{ pt.fail }}</el-tag>
            <el-tag v-if="pt.untested" size="small" type="info" effect="plain">未测 {{ pt.untested }}</el-tag>
          </div>
          <div class="trend-note">共 {{ historyPoints.length }} 个记录点（每分钟最多 1 点，保留 200 点）</div>
        </div>
        <div v-else class="trend-note">暂无足够历史数据（记录点每分钟最多 1 个）</div>
      </el-popover>
      <el-radio-group v-model="healthFilter" size="small" class="hf-group">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="ok">正常</el-radio-button>
        <el-radio-button value="fail">失效</el-radio-button>
        <el-radio-button value="untested">未测</el-radio-button>
      </el-radio-group>
    </div>

    <!-- 测活进度条（体验增强：批量测活实时反馈） -->
    <div v-if="checkProg && checkProg.total" class="check-prog">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>测活中 {{ checkProg.done }}/{{ checkProg.total }}</span>
      <el-progress :percentage="Math.round(checkProg.done / checkProg.total * 100)" :stroke-width="10" style="flex:1" />
      <el-tag size="small" type="success">正常 {{ checkProg.ok }}</el-tag>
      <el-tag v-if="checkProg.fail" size="small" type="danger">失效 {{ checkProg.fail }}</el-tag>
    </div>

    <div class="mobile-list">
      <div v-if="selected.length" class="batch-bar">
        已选 {{ selected.length }} 个：
        <el-button size="small" type="danger" plain @click="batchDelete">删除</el-button>
        <el-button size="small" type="primary" plain @click="openBatchAddToConfig">加入方案…</el-button>
        <el-button size="small" text @click="selected = []">取消</el-button>
      </div>
      <el-card v-for="s in pagedSites" :key="s.id" class="m-card" shadow="never" :class="{ 'm-sel': selected.includes(s.id) }">
        <div class="m-head">
          <el-checkbox :model-value="selected.includes(s.id)" @change="v => s.id && (v ? selected.push(s.id) : selected = selected.filter(i => i !== s.id))" />
          <span class="m-name">{{ s.name }}</span>
          <el-tag :type="typeColor[s.site_type]" size="small">{{ typeLabel[s.site_type] || s.site_type }}</el-tag>
        </div>
        <div class="m-key">key: {{ s.key }}</div>
        <div class="m-api">{{ s.api }}</div>
        <div v-if="s.ext && s.ext.trim()" class="m-ext">ext: {{ s.ext.length > 60 ? s.ext.slice(0, 60) + '…' : s.ext }}</div>
        <div v-if="s.last_test_result && !s.last_test_result.ok" class="m-errmsg">{{ s.last_test_result.message }}</div>
        <div class="m-meta">
          <el-switch v-model="s.enabled" size="small" @change="toggle(s)" />
          <el-tag v-if="healthTag(s)" :type="healthTag(s).type" size="small" class="m-health">{{ healthTag(s).text }}<span v-if="s.last_test_at" style="font-weight:400;font-size:11px"> · {{ timeAgo(s.last_test_at) }}</span></el-tag>
          <el-tag v-for="t in s.tags" :key="t" size="small" type="info" class="m-tag">{{ t }}</el-tag>
        </div>
        <div class="m-actions">
          <el-button size="small" :loading="checking.has(s.id)" @click="doCheck(s)">测活</el-button>
          <el-button size="small" @click="openEdit(s)">编辑</el-button>
          <el-button size="small" @click="cloneSite(s)">克隆</el-button>
          <el-button size="small" type="danger" plain @click="remove(s)">删除</el-button>
        </div>
      </el-card>
    </div>

    <div v-if="selected.length" class="batch-bar">
      已选 {{ selected.length }} 个：
      <el-button size="small" type="danger" plain @click="batchDelete">批量删除</el-button>
      <el-button size="small" @click="batchToggle(true)">批量启用</el-button>
      <el-button size="small" @click="batchTag">设置标签…</el-button>
      <el-button size="small" @click="batchToggle(false)">批量停用</el-button>
      <el-button size="small" type="primary" plain @click="openBatchAddToConfig">加入方案…</el-button>
      <el-button size="small" text @click="tableRef?.clearSelection?.(); selected = []">取消选择</el-button>
    </div>

    <el-table ref="tableRef" :data="pagedSites" v-loading="loading" class="desktop-table" stripe @selection-change="onSelChange">
      <el-table-column type="selection" width="42">
        <template #header>
          <el-checkbox
            :model-value="allSelected"
            :indeterminate="selected.length > 0 && !allSelected"
            @change="toggleAll"
          />
        </template>
      </el-table-column>
      <el-table-column prop="order_num" label="序" width="60" />
      <el-table-column prop="name" label="名称" min-width="120" />
      <el-table-column prop="key" label="key" min-width="100" />
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <el-tag :type="typeColor[row.site_type]" size="small">{{ typeLabel[row.site_type] || row.site_type }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="api" label="api" min-width="200" show-overflow-tooltip />
      <el-table-column label="ext" min-width="100" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.ext && row.ext.trim()" style="font-size:12px;color:#909399">{{ row.ext }}</span>
          <span v-else style="color:#c0c4cc">—</span>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" size="small" @change="toggle(row)" />
        </template>
      </el-table-column>
      <el-table-column label="测活" width="130">
        <template #default="{ row }">
          <el-popover v-if="row.last_test_result && !row.last_test_result.ok" placement="top" :width="320" trigger="hover">
            <template #reference>
              <el-tag :type="healthTag(row).type" size="small" style="cursor:help">失效 · 详情</el-tag>
            </template>
            <div style="font-size:12px;line-height:1.6">
              <div style="font-weight:600;margin-bottom:4px">{{ row.name }}（{{ row.key }}）失败详情</div>
              <div style="color:#909399">时间：{{ row.last_test_at ? timeAgo(row.last_test_at) : '—' }}</div>
              <div style="word-break:break-all">{{ row.last_test_result.message || JSON.stringify(row.last_test_result) }}</div>
            </div>
          </el-popover>
          <el-tag v-else-if="healthTag(row)" :type="healthTag(row).type" size="small">{{ healthTag(row).text }}</el-tag>
          <span v-else style="color:#c0c4cc">未测</span>
          <div v-if="row.last_test_at" style="font-size:11px;color:#909399;margin-top:2px">{{ timeAgo(row.last_test_at) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="失败原因" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.last_test_result && !row.last_test_result.ok" style="font-size:12px;color:#f56c6c">{{ row.last_test_result.message }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" :loading="checking.has(row.id)" @click="doCheck(row)">测活</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" @click="cloneSite(row)">克隆</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

        <div class="pager-bar" v-if="sites.length > pageSize">
      <el-pagination v-model:current-page="page" :page-size="pageSize" :total="filteredSites.length"
                     layout="prev, pager, next, total" background small />
    </div>

<el-dialog v-model="dialog" :title="editing ? '编辑站点' : '新建站点'" width="94%">
      <el-form label-width="90px">
        <el-form-item label="key" required>
          <el-input v-model="form.key" :disabled="!!editing" placeholder="唯一标识，如 csp_Xyz" />
        </el-form-item>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.site_type" style="width: 100%">
            <el-option label="0 XML" :value="0" />
            <el-option label="1 JSON" :value="1" />
            <el-option label="3 Spider" :value="3" />
            <el-option label="4 扩展JSON" :value="4" />
          </el-select>
        </el-form-item>
        <el-form-item label="api">
          <el-input v-model="form.api" placeholder="csp_Xyz / ./js/xx.js / https://...">
            <template #append v-if="form.site_type === 3">
              <el-dropdown @command="pickSource" trigger="click">
                <el-button>选源 ▾</el-button>
                <template #dropdown>
                  <el-dropdown-menu style="max-height: 320px; overflow-y: auto">
                    <el-dropdown-item v-for="src in sourceOptions" :key="src.id" :command="src">
                      [{{ src.kind }}] {{ src.filename }}
                    </el-dropdown-item>
                    <el-dropdown-item v-if="!sourceOptions.length" disabled>源库为空</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="ext">
          <div class="ext-box">
            <el-input v-model="form.ext" type="textarea" :rows="8" resize="vertical"
                      class="ext-input" placeholder="字符串或 JSON（可空）" />
            <div class="ext-bar">
              <el-tag v-if="extStatus === 'json'" type="success" size="small" effect="plain">✓ 合法 JSON</el-tag>
              <el-tag v-else-if="extStatus === 'invalid'" type="danger" size="small" effect="plain">✗ JSON 语法错误</el-tag>
              <el-tag v-else size="small" type="info" effect="plain">纯字符串</el-tag>
              <span style="flex:1"></span>
              <el-button size="small" :disabled="extStatus === 'invalid' || !form.ext.trim()"
                         @click="formatExt">格式化</el-button>
              <el-button size="small" :disabled="extStatus !== 'json'" @click="minifyExt">压缩</el-button>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="jar">
          <el-input v-model="form.jar" placeholder="如 ./jar/spider.jar（可空）" />
        </el-form-item>
        <el-form-item label="可搜索">
          <el-switch v-model="form.searchable" />
        </el-form-item>
        <el-form-item label="可换源">
          <el-switch v-model="form.changeable" />
        </el-form-item>
        <el-form-item label="隐藏">
          <el-switch v-model="form.hide" :active-value="1" :inactive-value="0" active-text="hide=1 仅UI隐藏" />
        </el-form-item>
        <el-form-item label="快速搜索">
          <el-switch v-model="form.quickSearch" />
        </el-form-item>
        <el-form-item label="索引来源">
          <el-switch v-model="form.indexs" active-text="indexs=1 作为索引来源" />
        </el-form-item>
        <el-form-item label="timeout">
          <el-input-number v-model="form.timeout" :min="1" :max="600" controls-position="right" placeholder="秒（可空）" style="width: 160px" />
        </el-form-item>
        <el-form-item label="点击拦截 click">
          <el-input v-model="form.click" placeholder="点击拦截 URL 或规则（可空）" />
        </el-form-item>
        <el-form-item label="播放前缀 playUrl">
          <el-input v-model="form.playUrl" placeholder="播放 URL 前缀/转换规则（可空）" />
        </el-form-item>
        <el-form-item label="分类白名单">
          <el-input v-model="form.categories" placeholder="仅显示这些分类，逗号分隔（可空=全部）" />
        </el-form-item>
        <el-form-item label="请求头 header">
          <el-input v-model="form.header" type="textarea" :rows="2" placeholder='HTTP 请求头 JSON 对象，如 {"User-Agent":"Mozilla/5.0"}（可空）' />
        </el-form-item>
        <el-form-item label="卡片样式 style">
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <el-select v-model="form.style_type" clearable placeholder="类型（可空）" style="width: 130px">
              <el-option label="rect 矩形" value="rect" />
              <el-option label="oval 圆形" value="oval" />
              <el-option label="list 列表" value="list" />
            </el-select>
            <el-select v-model="form.style_ratio" clearable placeholder="比例（可空）" style="width: 130px">
              <el-option :value="0.75" label="0.75 直式海报 3:4" />
              <el-option :value="1" label="1 正方形" />
              <el-option :value="1.33" label="1.33 横式 4:3" />
              <el-option :value="1.78" label="1.78 宽屏 16:9" />
            </el-select>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="impDialog" title="批量导入站点" width="min(520px, 94vw)" align-center>
      <div style="font-size:12px;color:#909399;margin-bottom:8px">
        每行一条：<code>名称,接口地址[,类型]</code>，类型 0=XML 1=JSON 3=Spider，省略默认 1；# 开头为注释
      </div>
      <el-input v-model="impText" type="textarea" :rows="8" placeholder="示例站点,http://example.com/api?ac=videolist&#10;另一个,http://b.com/api,0" />
      <template #footer>
        <el-button @click="impDialog = false">取消</el-button>
        <el-button type="primary" :loading="impBusy" @click="doImport">导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="addCfgDialog" title="批量加入方案" width="min(380px, 94vw)" align-center>
      <div style="margin-bottom:10px;color:#909399;font-size:13px">将选中的 {{ selected.length }} 个站点加入：</div>
      <el-select v-model="addCfgId" placeholder="选择方案" style="width:100%" filterable>
        <el-option v-for="c in configs" :key="c.id" :label="`${c.id}. ${c.name}`" :value="c.id" />
      </el-select>
      <template #footer>
        <el-button @click="addCfgDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!addCfgId" @click="doBatchAddToConfig">加入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.desktop-table { display: block; }
.mobile-list { display: none; }
.m-card { margin-bottom: 10px; }
.m-head { display: flex; align-items: center; gap: 8px; }
.m-name { font-weight: 600; flex: 1; }
.m-key { color: #909399; font-size: 12px; margin-top: 4px; }
.m-api { color: #606266; font-size: 12px; margin-top: 2px; word-break: break-all; }
.m-ext { color: #909399; font-size: 11px; margin-top: 2px; word-break: break-all; }
.m-meta { display: flex; align-items: center; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
.m-actions { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 10px; }
.m-actions .el-button { width: 100%; margin-left: 0; height: 32px; }
.m-health { max-width: 200px; overflow: hidden; text-overflow: ellipsis; }
.m-errmsg { font-size: 11px; color: #f56c6c; margin-top: 4px; word-break: break-all; }
.m-tag { margin-right: 4px; }
.batch-bar { display: flex; align-items: center; gap: 8px; padding: 8px 10px; margin-bottom: 10px; background: #ecf5ff; border-radius: 6px; flex-wrap: wrap; font-size: 13px; }
.m-card.m-sel { border: 1px solid #409eff; }

@media (max-width: 768px) {
  .desktop-table { display: none; }
  .mobile-list { display: block; }
  .toolbar { flex-wrap: wrap; gap: 8px; }
  .toolbar .el-input { width: 100% !important; }
}
</style>

<style>
.check-prog { display: flex; align-items: center; gap: 10px; padding: 8px 12px; margin-bottom: 10px; background: #ecf5ff; border-radius: 8px; font-size: 13px; }
.health-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 12px; margin-bottom: 10px; background: #f8f9fb; border-radius: 8px; font-size: 13px; }
.health-bar .fail-reason { color: #c45656; }
.health-bar .fail-click { cursor: pointer; }
.health-bar .fail-click:hover { opacity: 0.8; }
.health-bar .health-total { margin-left: auto; color: #909399; }
.trend-svg { display: block; margin-bottom: 6px; }
.trend-row { display: flex; gap: 8px; align-items: center; padding: 3px 0; font-size: 12px; }
.trend-t { color: #606266; width: 96px; }
.trend-note { color: #909399; font-size: 11px; margin-top: 6px; }
@media (max-width: 768px) {
  .health-bar { padding: 6px 10px; font-size: 12px; }
  .health-bar .health-total { margin-left: 0; width: 100%; }
}
</style>

<style>
.pager-bar { display: flex; justify-content: center; padding: 12px 0 4px; }
@media (max-width: 768px) { .pager-bar :deep(.el-pagination) { flex-wrap: wrap; justify-content: center; } }
</style>

<style scoped>
.ext-box { width: 100%; }
.ext-input :deep(.el-textarea__inner) { font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 12.5px; }
.ext-bar { display: flex; align-items: center; gap: 8px; margin-top: 6px; }
</style>
