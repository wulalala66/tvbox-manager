<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getConfig, updateConfig, setConfigSites, addConfigSite, removeConfigSite,
  listSites, publishConfig, publishVerify, publishHistory, publishRollback, publishDiff, validateConfig, diagnoseConfig, previewConfig, batchAddConfigSites, previewConfigStats, previewLive,
  checkAllSites as checkSites, listSources,
} from '../api'

const route = useRoute()
const id = route.params.id
const cfg = ref(null)
const allSites = ref([])
const selectedSites = ref([])
const preview = ref(null)
const saving = ref(false)
const editForm = ref({ name: '', slug: '', global_spider: '', global_fields: '{}',
  wallpaper: '', app_logo: '', notice: '',
  encrypt: false, enc_key: '', enc_key_set: false })
const shareInfo = ref(null)

async function load() {
  try {
    cfg.value = await getConfig(id)
    allSites.value = await listSites()
    editForm.value = {
      name: cfg.value.name, slug: cfg.value.slug,
      global_spider: cfg.value.global_spider || '',
      global_fields: JSON.stringify(cfg.value.global_fields || {}, null, 2),
      wallpaper: cfg.value.global_fields?.wallpaper || '',
      app_logo: cfg.value.global_fields?.logo || '',
      notice: cfg.value.global_fields?.notice || '',
      encrypt: !!cfg.value.encrypt, enc_key: '', enc_key_set: !!cfg.value.enc_key_set,
    }
    loadStructured()
  } catch (e) { ElMessage.error(e.message) }
}

const inConfigIds = computed(() => new Set((cfg.value?.sites || []).map(s => s.id)))
const addable = computed(() => allSites.value.filter(s => !inConfigIds.value.has(s.id)))

async function add() {
  if (!selectedSites.value.length) return
  try {
    if (selectedSites.value.length === 1) {
      await addConfigSite(id, selectedSites.value[0])
      ElMessage.success('已添加')
    } else {
      const r = await batchAddConfigSites(id, selectedSites.value)
      ElMessage.success(`已添加 ${Array.isArray(r.added) ? r.added.length : selectedSites.value.length} 个站点`)
    }
    selectedSites.value = []
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function removeSite(s) {
  try { await removeConfigSite(id, s.id); load() } catch (e) { ElMessage.error(e.message) }
}

// ---- 单站字段覆盖（overrides）----
const ovDialog = ref(false)
const ovSite = ref(null)
const ovText = ref('{}')
const ovSaving = ref(false)

function openOverrides(s) {
  ovSite.value = s
  ovText.value = JSON.stringify(s.overrides || {}, null, 2)
  ovDialog.value = true
}

function formatOv() {
  try {
    ovText.value = JSON.stringify(JSON.parse(ovText.value || '{}'), null, 2)
    ElMessage.success('已格式化')
  } catch (e) {
    let pos = ''
    const m = /position (\d+)/.exec(e.message)
    if (m) {
      const upto = ovText.value.slice(0, Number(m[1]))
      pos = `（第 ${upto.split('\n').length} 行）`
    }
    ElMessage.error('JSON 语法错误' + pos + ': ' + e.message)
  }
}

async function saveOverrides() {
  let ov
  try { ov = JSON.parse(ovText.value || '{}') } catch (e) { ElMessage.error('不是合法 JSON，未保存'); return }
  if (ov && typeof ov === 'object' && !Array.isArray(ov) && Object.keys(ov).length === 0) ov = null
  ovSaving.value = true
  try {
    // 全量保存当前顺序 + 各站既有 overrides（当前站替换为新值）
    await setConfigSites(id, cfg.value.sites.map((s, i) => ({
      site_id: s.id, order_num: i,
      overrides: s.id === ovSite.value.id ? ov : (s.overrides || null),
    })))
    ElMessage.success(ov ? '已保存覆盖' : '已清除覆盖')
    ovDialog.value = false
    load()
  } catch (e) { ElMessage.error(e.message) }
  ovSaving.value = false
}

function move(idx, dir) {
  const list = [...cfg.value.sites]
  const j = idx + dir
  if (j < 0 || j >= list.length) return
  ;[list[idx], list[j]] = [list[j], list[idx]]
  saveOrder(list)
}

async function saveOrder(list) {
  try {
    await setConfigSites(id, list.map((s, i) => ({ site_id: s.id, order_num: i })))
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function saveBase() {
  saving.value = true
  try {
    let fields = {}
    try { fields = JSON.parse(editForm.value.global_fields || '{}') } catch { throw new Error('全局字段不是合法 JSON') }
    // FongMi 顶层外观字段 → global_fields（wallpaper/logo/notice）
    for (const k of ['wallpaper', 'logo', 'notice']) {
      const v = (editForm.value[k] || '').trim()
      if (v) fields[k] = v; else delete fields[k]
    }
    await updateConfig(id, {
      name: editForm.value.name, slug: editForm.value.slug,
      global_spider: editForm.value.global_spider || null,
      global_fields: fields,
      encrypt: editForm.value.encrypt,
      // P2 修复：关闭加密时不下发 enc_key，避免清空已存 key
      ...(editForm.value.encrypt && editForm.value.enc_key ? { enc_key: editForm.value.enc_key } : {}),
    })
    ElMessage.success('已保存')
    load()
  } catch (e) { ElMessage.error(e.message) }
  saving.value = false
}

async function publish() {
  // 发布前校验：error 级问题直接拦截发布
  try {
    const v = await validateConfig(id)
    if (v.errors && v.errors.length) {
      ElMessageBox.alert(
        v.errors.map(e => `• ${e}`).join('\n') + (v.warnings.length ? `\n\n另有提示 ${v.warnings.length} 条（不阻塞发布）：\n${v.warnings.map(w => `• ${w}`).join('\n')}` : ''),
        `校验未通过：${v.errors.length} 个错误`,
        { type: 'error', customStyle: { whiteSpace: 'pre-line' }, confirmButtonText: '返回修改' }
      ).catch(() => {})
      return
    }
    if (v.warnings && v.warnings.length) {
      await ElMessageBox.confirm(
        v.warnings.map(w => `• ${w}`).join('\n'),
        `校验通过，但有 ${v.warnings.length} 条提示`,
        { type: 'warning', customStyle: { whiteSpace: 'pre-line' }, confirmButtonText: '仍然发布', cancelButtonText: '取消' }
      ).catch(() => { throw Object.assign(new Error('已取消发布'), { silent: true }) })
    }
  } catch (e) {
    if (!e.silent) ElMessage.error('校验请求失败: ' + e.message)
    return
  }
  try {
    const r = await publishConfig(id)
    shareInfo.value = r
    ElMessage.success(`已发布 ${r.site_count} 个站点${r.encrypted ? '（2423 加密）' : ''}`)
    if (Array.isArray(r.unhealthy) && r.unhealthy.length) {
      ElMessageBox.alert(
        r.unhealthy.map(u => `• ${u.name}（${u.key}）：${u.message}`).join('\n'),
        `警告：${r.unhealthy.length} 个站点近次测活失败（已照常发布）`,
        { type: 'warning', customStyle: { whiteSpace: 'pre-line' }, confirmButtonText: '知道了' }
      ).catch(() => {})
    }
    load()
  } catch (e) { ElMessage.error(e.message) }
}

// 发布自检：验证「发布→下载→TVBox 解密」整条链路
const verifyResult = ref(null)
const verifyLoading = ref(false)
async function doVerify() {
  verifyLoading.value = true
  verifyResult.value = null
  try {
    verifyResult.value = await publishVerify(id)
  } catch (e) { ElMessage.error(e.message) }
  verifyLoading.value = false
}

async function doPreview() {
  try {
    const r = await previewConfig(id)
    // 后端已返回美化后的 JSON 文本
    preview.value = typeof r === 'string' ? r : JSON.stringify(r, null, 2)
  } catch (e) { ElMessage.error(e.message) }
}

async function exportJson() {
  try {
    const r = await previewConfig(id)
    const text = typeof r === 'string' ? r : JSON.stringify(r, null, 2)
    const blob = new Blob([text], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${cfg.value?.slug || 'config'}.json`
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('已导出明文 JSON')
  } catch (e) { ElMessage.error(e?.message || '导出失败') }
}

const typeLabel = { 0: 'XML', 1: 'JSON', 3: 'Spider', 4: '扩展' }
const origin = location.origin
const isMobile = ref(window.innerWidth < 640)
const _onResize = () => { isMobile.value = window.innerWidth < 640 }
window.addEventListener('resize', _onResize)
onUnmounted(() => window.removeEventListener('resize', _onResize))

function formatFields() {
  try {
    editForm.value.global_fields = JSON.stringify(JSON.parse(editForm.value.global_fields || '{}'), null, 2)
    ElMessage.success('已格式化')
    if (preview.value) doPreview()
  } catch (e) {
    // 定位语法错误位置（position: char offset → 行/列）
    let pos = ''
    const m = /position (\d+)/.exec(e.message)
    if (m) {
      const upto = editForm.value.global_fields.slice(0, Number(m[1]))
      const line = upto.split('\n').length
      const col = upto.length - upto.lastIndexOf('\n')
      pos = `（第 ${line} 行第 ${col} 列）`
    }
    ElMessage.error('JSON 语法错误' + pos + ': ' + e.message)
  }
}

async function copyShare() {
  const url = `${origin}/configs/${id}/download?token=${(shareInfo.value || cfg.value).share_token}`
  try { await navigator.clipboard.writeText(url); ElMessage.success('已复制') }
  catch { ElMessage.warning(url) }
}

const qrDialog = ref(false)
const qrDataUrl = ref('')
async function showShareQr() {
  const url = `${origin}/configs/${id}/download?token=${(shareInfo.value || cfg.value).share_token}`
  try {
    const QRCode = (await import('qrcode')).default
    qrDataUrl.value = await QRCode.toDataURL(url, { width: 240, margin: 2 })
    qrDialog.value = true
  } catch (e) { ElMessage.error('二维码生成失败: ' + e.message) }
}

// 方案统计（发布前 sanity check）
const statsDialog = ref(false)
const statsLoading = ref(false)
const stats = ref(null)
async function showStats() {
  statsLoading.value = true
  try {
    stats.value = await previewConfigStats(id)
    statsDialog.value = true
  } catch (e) { ElMessage.error(e.message) }
  statsLoading.value = false
}

const rechecking = ref(false)
async function recheckSites() {
  if (!cfg.value?.sites?.length) return
  rechecking.value = true
  try {
    const ids = cfg.value.sites.map(s => s.id)
    const r = await checkSites({ site_ids: ids })
    ElMessage.success(`重测完成：${r.ok} 正常 / ${r.fail} 失效`)
    load()
  } catch (e) { ElMessage.error(e.message) }
  rechecking.value = false
}

// ---- 直播源（lives）/ 解析（parses）/ 去广告嗅探规则 / 弹幕 结构化编辑（FongMi 扩展字段，写入 global_fields）----
const livesRows = ref([])
const parsesRows = ref([])
const adsRows = ref([])     // [{v}] → gf.ads: [域名]
const rulesRows = ref([])   // [{name,hosts,regex,exclude,script}] → gf.rules
const danmakuUrl = ref('')  // → gf.danmaku
// 顶层网络/平台小字段（FongMi Vod 顶层，后端零改动透传）
const flagsRows = ref([])   // [{v}] → gf.flags: ['qq',...]
const hostRows = ref([])    // [{v}] → gf.hosts: ['origin=target',...]（支持 * 通配）
const headerRows = ref([])  // [{k,v}] → gf.headers: [{host,header:{}}]
const dohRows = ref([])     // [{name,url,ips}] → gf.doh
const proxyRows = ref([])   // [{name,hosts,urls}] → gf.proxy
// 源库 jar 文件列表（全局 spider 下拉选择用）
const jarFiles = ref([])
async function loadJars() {
  try {
    const r = await listSources({ kind: 'jar', page_size: 500 })
    jarFiles.value = (r.items || r || []).filter(s => s.kind === 'jar')
  } catch { jarFiles.value = [] }
}
// 内置常用嗅探/去广告规则模板（FongMi 社区常见配置）
const RULE_TEMPLATES = [
  { name: '通用视频嗅探', hosts: '', regex: 'http(.+?)\\.(m3u8|mp4|flv|avi|mkv|mpeg|mov|ts|3gp|rm|rmvb|wmv)(.*)', exclude: '', script: '' },
  { name: '广告域拦截', hosts: '', regex: '', exclude: 'doubleclick,googlesyndication,adsserver,mi.gdt.qq.com', script: '' },
  { name: '腾讯视频嗅探', hosts: 'v.qq.com', regex: 'http(.+?)\\.mp4', exclude: '', script: '' },
]
const PARSE_TYPES = [
  { v: 0, label: '0 · 嗅探（WebView 拦截）' },
  { v: 1, label: '1 · JSON 接口' },
  { v: 2, label: '2 · JSON 扩展（送 JAR）' },
  { v: 3, label: '3 · JSON 聚合（送 JAR）' },
  { v: 4, label: '4 · 超级解析（并行尝试）' },
]

function loadStructured() {
  const gf = cfg.value?.global_fields || {}
  livesRows.value = Array.isArray(gf.lives) ? gf.lives.map(l => ({
    name: l.name || '', url: l.url || '', epg: l.epg || '', ua: l.ua || '',
    timeZone: l.timeZone || '', boot: !!l.boot,
    catchup_type: l.catchup?.type || '', catchup_source: l.catchup?.source || '', catchup_regex: l.catchup?.regex || '', catchup_replace: l.catchup?.replace || '',
  })) : []
  parsesRows.value = Array.isArray(gf.parses) ? gf.parses.map(p => ({
    name: p.name || '', type: Number(p.type ?? 1), url: p.url || '',
    flag: Array.isArray(p?.ext?.flag) ? p.ext.flag.join(',') : '',
    header: p?.ext?.header ? JSON.stringify(p.ext.header) : '',
  })) : []
  adsRows.value = Array.isArray(gf.ads) ? gf.ads.map(a => ({ v: String(a) })) : []
  rulesRows.value = Array.isArray(gf.rules) ? gf.rules.map(r => ({
    name: r.name || '', hosts: Array.isArray(r.hosts) ? r.hosts.join(',') : '',
    regex: r.regex || '', exclude: Array.isArray(r.exclude) ? r.exclude.join(',') : '',
    script: r.script || '',
  })) : []
  danmakuUrl.value = typeof gf.danmaku === 'string' ? gf.danmaku : ''
  flagsRows.value = Array.isArray(gf.flags) ? gf.flags.map(a => ({ v: String(a) })) : []
  hostRows.value = Array.isArray(gf.hosts) ? gf.hosts.map(a => ({ v: String(a) })) : []
  headerRows.value = Array.isArray(gf.headers) ? gf.headers.map(h => ({ k: h.host || '', v: h.header ? JSON.stringify(h.header) : '' })) : []
  dohRows.value = Array.isArray(gf.doh) ? gf.doh.map(d => ({ name: d.name || '', url: d.url || '', ips: Array.isArray(d.ips) ? d.ips.join(',') : '' })) : []
  proxyRows.value = Array.isArray(gf.proxy) ? gf.proxy.map(p => ({ name: p.name || '', hosts: Array.isArray(p.hosts) ? p.hosts.join(',') : '', urls: Array.isArray(p.urls) ? p.urls.join(',') : '' })) : []
}

function addLive() { livesRows.value.push({ name: '', url: '', epg: '', ua: '', timeZone: '', boot: false, catchup_type: '', catchup_source: '', catchup_regex: '', catchup_replace: '' }) }
function addParse() { parsesRows.value.push({ name: '', type: 1, url: '', flag: '', header: '' }) }
function addAd() { adsRows.value.push({ v: '' }) }
function addRule(t) { rulesRows.value.push(t ? { ...t } : { name: '', hosts: '', regex: '', exclude: '', script: '' }) }
function addFlag() { flagsRows.value.push({ v: '' }) }
function addHost() { hostRows.value.push({ v: '' }) }
function addHeader() { headerRows.value.push({ k: '', v: '' }) }
function addDoh() { dohRows.value.push({ name: '', url: '', ips: '' }) }
function addProxy() { proxyRows.value.push({ name: '', hosts: '', urls: '' }) }

// ---- 直播源预览（抓取 + 解析格式验证）----
const lpVisible = ref(false)
const lpLoading = ref(false)
const lpError = ref('')
const lpResult = ref(null)
async function doLivePreview(l) {
  if (!l.url || !l.url.trim()) { ElMessage.warning('请先填写直播源 url'); return }
  lpVisible.value = true; lpLoading.value = true; lpError.value = ''; lpResult.value = null
  try {
    const r = await previewLive(id, l.url.trim())
    if (!r.ok) { lpError.value = r.error || '抓取失败'; return }
    lpResult.value = r
  } catch (e) { lpError.value = e.message } finally { lpLoading.value = false }
}

// ---- 发布历史 + 回滚 + diff ----
const histVisible = ref(false)
const histLoading = ref(false)
const histItems = ref([])
const diffVisible = ref(false)
const diffLoading = ref(false)
const diffData = ref(null)
const diffFile = ref('')
async function showHistory() {
  histVisible.value = true; histLoading.value = true
  try { histItems.value = (await publishHistory(id)).items }
  catch (e) { ElMessage.error(e.message) } finally { histLoading.value = false }
}
async function showDiff(file) {
  diffVisible.value = true; diffLoading.value = true; diffFile.value = file
  try { diffData.value = await publishDiff(id, file) }
  catch (e) { ElMessage.error(e.message) } finally { diffLoading.value = false }
}
async function doRollback(file) {
  try {
    await ElMessageBox.confirm('将当前发布产物覆盖为该历史快照（当前产物本身也会先存入历史），确定回滚？', '回滚确认', { type: 'warning' })
  } catch { return }
  const r = await publishRollback(id, file)
  ElMessage.success(`已回滚到 ${r.file}（${r.bytes} 字节）`)
  await showHistory()
  await load()
}

// ---- 配置诊断 ----
const dgVisible = ref(false)
const dgLoading = ref(false)
const dgResult = ref(null)
async function doDiagnose() {
  dgVisible.value = true; dgLoading.value = true; dgResult.value = null
  try { dgResult.value = await diagnoseConfig(id) }
  catch (e) { ElMessage.error(e.message) } finally { dgLoading.value = false }
}
const DG_TAG = { error: 'danger', warn: 'warning', info: 'info', ok: 'success' }
const DG_LABEL = { error: '错误', warn: '警告', info: '提示', ok: '正常' }

function cleanObj(o) { // 去掉空值字段
  const out = {}
  for (const [k, v] of Object.entries(o)) if (v !== '' && v !== null && v !== undefined) out[k] = v
  return out
}

// 结构化数据 → 写回 global_fields 文本框 → 走统一保存链路
async function saveStructured() {
  const lives = livesRows.value.filter(r => r.name && r.url).map(r => cleanObj({
    name: r.name.trim(), url: r.url.trim(), epg: r.epg.trim() || undefined, ua: r.ua.trim() || undefined,
    timeZone: r.timeZone.trim() || undefined, boot: r.boot || undefined,
    catchup: (r.catchup_source.trim() || r.catchup_type) ? cleanObj({
      type: r.catchup_type.trim() || undefined, source: r.catchup_source.trim() || undefined, regex: r.catchup_regex.trim() || undefined,
      replace: r.catchup_replace.trim() || undefined,
    }) : undefined,
  }))
  const parses = []
  for (const r of parsesRows.value.filter(r => r.name && r.url)) {
    const p = { name: r.name.trim(), type: Number(r.type) || 0, url: r.url.trim() }
    const ext = {}
    if (r.flag.trim()) ext.flag = r.flag.split(/[,，]/).map(x => x.trim()).filter(Boolean)
    if (r.header.trim()) {
      try { ext.header = JSON.parse(r.header) } catch { ElMessage.error(`解析「${r.name}」的 header 不是合法 JSON，未保存`); return }
    }
    if (Object.keys(ext).length) p.ext = ext
    parses.push(p)
  }
  let fields
  try { fields = JSON.parse(editForm.value.global_fields || '{}') } catch { ElMessage.error('全局字段不是合法 JSON，请先修正后再保存结构化字段'); return }
  if (lives.length) fields.lives = lives; else delete fields.lives
  if (parses.length) fields.parses = parses; else delete fields.parses
  const ads = adsRows.value.map(r => r.v.trim()).filter(Boolean)
  if (ads.length) fields.ads = ads; else delete fields.ads
  const rules = rulesRows.value.filter(r => r.regex.trim() || r.hosts.trim() || r.exclude.trim()).map(r => cleanObj({
    name: r.name.trim() || undefined, hosts: r.hosts.trim() ? r.hosts.split(/[,，、]/).map(x => x.trim()).filter(Boolean) : undefined,
    regex: r.regex.trim() || undefined, exclude: r.exclude.trim() ? r.exclude.split(/[,，、]/).map(x => x.trim()).filter(Boolean) : undefined,
    script: r.script.trim() || undefined,
  }))
  if (rules.length) {
    for (const r of rules) {
      try { if (r.regex) new RegExp(r.regex) } catch { ElMessage.error(`规则「${r.name || '未命名'}」的 regex 不合法，未保存`); return }
    }
    fields.rules = rules
  } else delete fields.rules
  if (danmakuUrl.value.trim()) fields.danmaku = danmakuUrl.value.trim(); else delete fields.danmaku
  // 顶层网络/平台小字段（FongMi Vod 顶层）
  const flags = flagsRows.value.map(r => r.v.trim()).filter(Boolean).flatMap(v => v.split(/[,，]/).map(x => x.trim()).filter(Boolean))
  if (flags.length) fields.flags = flags; else delete fields.flags
  const hosts = hostRows.value.filter(r => r.v.trim()).map(r => r.v.trim())
  for (const h of hosts) {
    if (!h.includes('=')) { ElMessage.error(`hosts 项「${h}」缺少 = 分隔（格式 origin=target，支持 * 通配），未保存`); return }
  }
  if (hosts.length) fields.hosts = hosts; else delete fields.hosts
  const headers = headerRows.value.filter(r => r.k.trim()).map(r => ({ host: r.k.trim(), header: (() => { try { return JSON.parse(r.v || '{}') } catch { throw new Error(`headers 项「${r.k.trim()}」的 header 不是合法 JSON，未保存`) } })() }))
  try { for (const h of headers) if (typeof h.header !== 'object') throw new Error(`headers 项「${h.host}」的 header 需为 JSON 对象，未保存`) } catch (e) { ElMessage.error(e.message); return }
  if (headers.length) fields.headers = headers; else delete fields.headers
  const dohs = dohRows.value.filter(r => r.name.trim() && r.url.trim()).map(r => cleanObj({
    name: r.name.trim(), url: r.url.trim(),
    ips: r.ips.trim() ? r.ips.split(/[,，]/).map(x => x.trim()).filter(Boolean) : undefined,
  }))
  if (dohs.length) fields.doh = dohs; else delete fields.doh
  const proxies = proxyRows.value.filter(r => r.hosts.trim() || r.urls.trim()).map(r => cleanObj({
    name: r.name.trim(),
    hosts: r.hosts.trim() ? r.hosts.split(/[,，]/).map(x => x.trim()).filter(Boolean) : undefined,
    urls: r.urls.trim() ? r.urls.split(/[,，]/).map(x => x.trim()).filter(Boolean) : undefined,
  }))
  if (proxies.length) fields.proxy = proxies; else delete fields.proxy
  editForm.value.global_fields = JSON.stringify(fields, null, 2)
  await saveBase()
}

onMounted(() => { load(); loadJars() })
</script>

<template>
  <div class="page" v-if="cfg">
    <div class="head">
      <el-button size="small" @click="$router.push('/configs')">← 返回</el-button>
      <h3 style="margin: 0">{{ cfg.name }}</h3>
      <el-tag v-if="cfg.published_at" type="success" size="small">已发布</el-tag>
      <div style="flex:1"></div>
      <el-button type="primary" @click="publish">发布</el-button>
      <el-button @click="doVerify" :loading="verifyLoading" v-if="cfg.published_at">解密自检</el-button>
      <el-button @click="showHistory" v-if="cfg.published_at">发布历史</el-button>
      <el-button @click="doDiagnose" :loading="dgLoading">诊断</el-button>
      <el-button @click="doPreview">预览 JSON</el-button>
      <el-button @click="exportJson">导出 JSON</el-button>
      <el-button @click="showStats">统计</el-button>
      <el-button v-if="cfg.published_at" tag="a" :href="`/configs/${id}/download?token=${cfg.share_token}`">下载</el-button>
    </div>

    <el-card class="card-block" shadow="never">
      <template #header>基本信息</template>
      <el-form label-width="88px" size="small" class="cfg-form" :label-position="isMobile ? 'top' : 'right'">
        <el-form-item label="名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="slug"><el-input v-model="editForm.slug" /></el-form-item>
        <el-form-item label="全局 spider">
          <div style="display:flex;gap:8px;width:100%">
            <el-select v-model="editForm.global_spider" filterable allow-create default-first-option
              placeholder="从源库选择 jar 或手动输入路径" style="flex:1">
              <el-option v-for="j in jarFiles" :key="j.id" :label="`./jar/${j.filename}（${j.name}）`" :value="`./jar/${j.filename}`" />
            </el-select>
          </div>
          <div v-if="editForm.global_spider" class="spider-hint">当前：{{ editForm.global_spider }}</div>
        </el-form-item>
        <el-form-item label="壁纸 wallpaper"><el-input v-model="editForm.wallpaper" placeholder="桌布图片/视频 URL（可选，FongMi 顶层字段）" /></el-form-item>
        <el-form-item label="Logo"><el-input v-model="editForm.app_logo" placeholder="应用 Logo 图片 URL（可选）" /></el-form-item>
        <el-form-item label="启动公告"><el-input v-model="editForm.notice" placeholder="启动时显示的文字公告（可选）" maxlength="200" show-word-limit /></el-form-item>
        <el-form-item label="全局字段">
          <el-input v-model="editForm.global_fields" type="textarea" :rows="12" style="font-family: monospace" placeholder='如 {"lives":[...]}' />
          <div style="margin-top: 4px"><el-button size="small" @click="formatFields">整理 JSON</el-button></div>
        </el-form-item>
        <el-form-item label="发布加密">
          <el-switch v-model="editForm.encrypt" active-text="2423 加密（仅 TVBox 可载入）" />
        </el-form-item>
        <el-form-item v-if="editForm.encrypt" label="加密 key">
          <el-input v-model="editForm.enc_key" :placeholder="editForm.enc_key_set ? '已设置（留空保持原 key）' : '1~16 字符，如 mykey123（务必牢记）'" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveBase">保存</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card class="card-block" shadow="never">
      <template #header>
        <div style="display:flex;align-items:center;flex-wrap:wrap;gap:8px">
          <span>直播源 / 解析（FongMi 扩展字段）</span>
          <div style="flex:1"></div>
          <el-button size="small" @click="addLive">+ 直播源</el-button>
          <el-button size="small" @click="addParse">+ 解析</el-button>
          <el-button size="small" type="primary" :loading="saving" @click="saveStructured">保存结构化字段</el-button>
        </div>
      </template>
      <div class="st-tip">写入 <code>global_fields.lives / parses</code>，与全局字段文本框共享数据；发布时自动并入配置。</div>

      <div class="st-sec">
        <div class="st-title">直播源 lives（{{ livesRows.length }}）</div>
        <div class="st-tip" style="margin-bottom:6px">epg 支持逗号分隔多源与 {id}/{name}/{epg} 变量（含 xml/gz 的条目按 XMLTV 处理）；勾选 boot 启动自动选中。</div>
        <div v-for="(l, i) in livesRows" :key="'l'+i" class="live-block">
          <div class="st-row" style="margin-bottom:4px">
            <el-input v-model="l.name" placeholder="名称，如 CCTV" class="st-name" />
            <el-input v-model="l.url" placeholder="直播列表 url（txt/m3u/json）" class="st-url" />
            <el-checkbox v-model="l.boot" label="启动选中" />
            <el-button size="small" type="danger" text @click="livesRows.splice(i, 1)">删</el-button>
            <el-button size="small" text type="primary" :loading="l._loading" @click="doLivePreview(l)">预览</el-button>
          </div>
          <div class="st-row" style="margin-bottom:4px">
            <el-input v-model="l.epg" placeholder="epg 多源逗号分隔，支持 {id}/{name}/{epg} 变量（可选）" class="st-epg" />
            <el-input v-model="l.timeZone" placeholder="时区，如 Asia/Shanghai（可选）" class="st-epg" />
            <el-input v-model="l.ua" placeholder="UA（可选）" class="st-ua" />
          </div>
          <div class="st-row">
            <el-select v-model="l.catchup_type" placeholder="追看类型（可选）" clearable class="st-epg">
              <el-option label="append（默认：拼接回看参数）" value="append" />
              <el-option label="default（整串替换 url）" value="default" />
            </el-select>
            <el-input v-model="l.catchup_source" placeholder="回看 url 模板，如 ?playseek=${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}（可选）" class="st-url" />
            <el-input v-model="l.catchup_regex" placeholder="回看生效条件 regex（可选）" class="st-epg" />
            <el-input v-model="l.catchup_replace" placeholder="替换对「原,新」先替换原 url 再拼 source（可选）" class="st-epg" />
          </div>
        </div>
        <el-empty v-if="!livesRows.length" description="无直播源，点右上「+ 直播源」添加" :image-size="50" />
      </div>

      <div class="st-sec">
        <div class="st-title">网页解析 parses（{{ parsesRows.length }}）</div>
        <div v-for="(p, i) in parsesRows" :key="'p'+i" class="st-row">
          <el-input v-model="p.name" placeholder="名称" class="st-name" />
          <el-select v-model="p.type" class="st-type">
            <el-option v-for="t in PARSE_TYPES" :key="t.v" :label="t.label" :value="t.v" />
          </el-select>
          <el-input v-model="p.url" placeholder="解析接口 url（?url= 结尾）" class="st-url" />
          <el-input v-model="p.flag" placeholder="适用 flag 逗号分隔（可选）" class="st-epg" />
          <el-input v-model="p.header" placeholder='header JSON（可选）' class="st-ua" />
          <el-button size="small" type="danger" text @click="parsesRows.splice(i, 1)">删</el-button>
        </div>
        <el-empty v-if="!parsesRows.length" description="无解析规则，点右上「+ 解析」添加" :image-size="50" />
      </div>

      <div class="st-sec">
        <div class="st-title">去广告 ads（{{ adsRows.length }}）</div>
        <div v-for="(a, i) in adsRows" :key="'a'+i" class="st-row">
          <el-input v-model="a.v" placeholder="广告域名，如 ad.doubleclick.net" class="st-url" />
          <el-button size="small" type="danger" text @click="adsRows.splice(i, 1)">删</el-button>
        </div>
        <el-button size="small" text type="primary" @click="addAd">+ 域名</el-button>
        <el-empty v-if="!adsRows.length" description="无拦截域名（可选）" :image-size="40" />
      </div>

      <div class="st-sec">
        <div class="st-title">嗅探/去广告规则 rules（{{ rulesRows.length }}）</div>
        <div class="st-tip" style="margin-bottom:6px">regex 决定 WebView 嗅探哪些 url 算媒体（直接影响嗅探型站点能否出片）；hosts 限定生效域名；exclude 排除。可用模板：</div>
        <div style="margin-bottom:8px;display:flex;gap:6px;flex-wrap:wrap">
          <el-button v-for="t in RULE_TEMPLATES" :key="t.name" size="small" @click="addRule(t)">+ {{ t.name }}</el-button>
        </div>
        <div v-for="(r, i) in rulesRows" :key="'r'+i" class="rule-row">
          <div class="st-row" style="margin-bottom:4px">
            <el-input v-model="r.name" placeholder="规则名" class="st-name" />
            <el-input v-model="r.hosts" placeholder="hosts 逗号分隔（可选）" class="st-epg" />
            <el-button size="small" type="danger" text @click="rulesRows.splice(i, 1)">删</el-button>
          </div>
          <div class="st-row">
            <el-input v-model="r.regex" placeholder="媒体正则 regex，如 http(.+?)\.(m3u8|mp4)(.*)" class="st-url" />
            <el-input v-model="r.exclude" placeholder="排除正则（可选）" class="st-epg" />
          </div>
        </div>
        <el-button size="small" text type="primary" @click="addRule()">+ 规则</el-button>
        <el-empty v-if="!rulesRows.length" description="无自定义规则（可选，模板一键导入）" :image-size="40" />
      </div>

      <div class="st-sec">
        <div class="st-title">弹幕 danmaku</div>
        <div class="st-row">
          <el-input v-model="danmakuUrl" placeholder="弹幕接口 url，含 {name}/{episode} 占位走 GET，否则 POST form（可选）" class="st-url" />
        </div>
      </div>

      <div class="st-sec">
        <div class="st-title">网络 / 平台扩展字段（FongMi 顶层）</div>
        <div class="st-tip">flags 平台旗标 · hosts 域名解析覆盖（origin=target，支持 *）· headers 注入响应头解 CORS · doh 加密 DNS 防污染 · proxy 指定域名走代理</div>
        <div v-for="(r, i) in flagsRows" :key="'f' + i" class="st-row">
          <el-input v-model="r.v" placeholder="旗标，如 qq / iqiyi" class="st-name" />
          <el-button size="small" type="danger" text @click="flagsRows.splice(i, 1)">删</el-button>
        </div>
        <el-button size="small" text type="primary" @click="addFlag()">+ 旗标</el-button>
        <div v-for="(r, i) in hostRows" :key="'h' + i" class="st-row">
          <el-input v-model="r.v" placeholder="origin=target（支持 *，如 *.example.com=1.2.3.4）" class="st-url" />
          <el-button size="small" type="danger" text @click="hostRows.splice(i, 1)">删</el-button>
        </div>
        <el-button size="small" text type="primary" @click="addHost()">+ hosts</el-button>
        <div v-for="(r, i) in headerRows" :key="'hd' + i" class="st-row">
          <el-input v-model="r.k" placeholder="域名 host" class="st-name" />
          <el-input v-model="r.v" placeholder='header JSON 对象，如 {"Referer":"https://x.com"}' class="st-url" />
          <el-button size="small" type="danger" text @click="headerRows.splice(i, 1)">删</el-button>
        </div>
        <el-button size="small" text type="primary" @click="addHeader()">+ headers</el-button>
        <div v-for="(r, i) in dohRows" :key="'d' + i" class="st-row">
          <el-input v-model="r.name" placeholder="名称" class="st-name" />
          <el-input v-model="r.url" placeholder="DoH url，如 https://dns.alidns.com/dns-query" class="st-url" />
          <el-input v-model="r.ips" placeholder="bootstrap IP 逗号分隔（可选）" class="st-epg" />
          <el-button size="small" type="danger" text @click="dohRows.splice(i, 1)">删</el-button>
        </div>
        <el-button size="small" text type="primary" @click="addDoh()">+ DoH</el-button>
        <div v-for="(r, i) in proxyRows" :key="'p' + i" class="st-row">
          <el-input v-model="r.name" placeholder="名称" class="st-name" />
          <el-input v-model="r.hosts" placeholder="域名正则 逗号分隔" class="st-url" />
          <el-input v-model="r.urls" placeholder="代理 url 逗号分隔（http/socks）" class="st-url" />
          <el-button size="small" type="danger" text @click="proxyRows.splice(i, 1)">删</el-button>
        </div>
        <el-button size="small" text type="primary" @click="addProxy()">+ 代理</el-button>
      </div>

      <el-dialog v-model="dgVisible" title="配置诊断" width="640px">
        <template v-if="dgLoading"><el-skeleton :rows="5" animated /></template>
        <template v-else-if="dgResult">
          <el-alert v-if="!dgResult.issues.length" type="success" :closable="false"
            :title="`未发现错误 · 提示 ${dgResult.warnings.length} 条 · 站点 ${dgResult.counts.sites} 个`" />
          <el-alert v-else type="error" :closable="false"
            :title="`发现 ${dgResult.counts.errors} 个错误 · 警告 ${dgResult.counts.warnings} 条 · 站点 ${dgResult.counts.sites} 个`" />
          <div class="dg-list">
            <div v-for="(it, i) in dgResult.issues" :key="'e' + i" class="dg-row">
              <el-tag :type="DG_TAG[it.level]" size="small">{{ DG_LABEL[it.level] }}</el-tag>
              <span class="dg-item">{{ it.item }}</span><span class="dg-msg">{{ it.msg }}</span>
            </div>
            <div v-for="(it, i) in dgResult.warnings" :key="'w' + i" class="dg-row">
              <el-tag :type="DG_TAG[it.level]" size="small">{{ DG_LABEL[it.level] }}</el-tag>
              <span class="dg-item">{{ it.item }}</span><span class="dg-msg">{{ it.msg }}</span>
            </div>
          </div>
        </template>
      </el-dialog>

      <el-dialog v-model="histVisible" :title="`发布历史（最近 10 份快照）`" :width="isMobile ? '96%' : '620px'">
        <div class="hist-wrap">
        <el-table :data="histItems" v-loading="histLoading" size="small">
          <el-table-column prop="ts" label="快照时间 (UTC)" min-width="150" />
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag :type="row.encrypted ? 'warning' : 'info'" size="small">{{ row.encrypted ? '密文' : '明文' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="站点" width="70">
            <template #default="{ row }">{{ row.sites ?? '—' }}</template>
          </el-table-column>
          <el-table-column prop="bytes" label="字节" width="80" />
          <el-table-column label="操作" width="170">
            <template #default="{ row }">
              <el-button size="small" type="info" plain @click="showDiff(row.file)">对比</el-button>
              <el-button size="small" type="warning" plain @click="doRollback(row.file)">回滚到此</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div v-if="!histLoading && !histItems.length" style="color:#909399;font-size:13px;padding:12px 0">
          暂无历史快照——发布第二次起，每次发布都会把旧产物自动存档。
        </div>
        </div>
      </el-dialog>

      <el-dialog v-model="diffVisible" :title="`快照对比 · ${diffFile}`" :width="isMobile ? '96%' : '640px'">
        <template v-if="diffLoading"><el-skeleton :rows="4" animated /></template>
        <template v-else-if="diffData">
          <div class="diff-sum">
            站点数 {{ diffData.sites.old_count }} → {{ diffData.sites.cur_count }} ·
            新增 {{ diffData.sites.added.length }} · 移除 {{ diffData.sites.removed.length }} · 变更 {{ diffData.sites.changed.length }}
          </div>
          <div class="diff-sec" v-if="diffData.sites.added.length">
            <div class="diff-title">新增站点</div>
            <div v-for="s in diffData.sites.added" :key="s.key" class="diff-item add">+ {{ s.key }}{{ s.name ? `（${s.name}）` : '' }}</div>
          </div>
          <div class="diff-sec" v-if="diffData.sites.removed.length">
            <div class="diff-title">移除站点</div>
            <div v-for="s in diffData.sites.removed" :key="s.key" class="diff-item del">- {{ s.key }}{{ s.name ? `（${s.name}）` : '' }}</div>
          </div>
          <div class="diff-sec" v-if="diffData.sites.changed.length">
            <div class="diff-title">字段变更</div>
            <div v-for="s in diffData.sites.changed" :key="s.key" class="diff-item chg">~ {{ s.key }}{{ s.name ? `（${s.name}）` : '' }}: {{ s.fields.join(', ') }}</div>
          </div>
          <div class="diff-sec" v-if="diffData.top.added.length || diffData.top.removed.length || diffData.top.changed.length">
            <div class="diff-title">顶层字段</div>
            <div v-for="k in diffData.top.added" :key="'ta' + k" class="diff-item add">+ {{ k }}</div>
            <div v-for="k in diffData.top.removed" :key="'tr' + k" class="diff-item del">- {{ k }}</div>
            <div v-for="k in diffData.top.changed" :key="'tc' + k" class="diff-item chg">~ {{ k }}</div>
          </div>
          <div v-if="!diffData.sites.added.length && !diffData.sites.removed.length && !diffData.sites.changed.length
            && !diffData.top.added.length && !diffData.top.removed.length && !diffData.top.changed.length"
            style="color:#909399;font-size:13px">无差异——快照与当前产物完全一致。</div>
        </template>
      </el-dialog>

      <el-dialog v-model="lpVisible" title="直播源预览" width="560px">
        <template v-if="lpLoading"><el-skeleton :rows="4" animated /></template>
        <template v-else-if="lpError"><el-alert type="error" :title="lpError" :closable="false" /></template>
        <template v-else-if="lpResult">
          <el-descriptions :column="3" border size="small">
            <el-descriptions-item label="格式">{{ lpResult.format }}</el-descriptions-item>
            <el-descriptions-item label="分组">{{ lpResult.n_groups }}</el-descriptions-item>
            <el-descriptions-item label="频道">{{ lpResult.n_channels }}</el-descriptions-item>
          </el-descriptions>
          <div v-for="s in lpResult.sample" :key="s.group" class="lp-sample">
            <div class="lp-g">📁 {{ s.group }}（{{ s.count }} 个频道）</div>
            <div class="lp-ch" v-for="c in s.channels" :key="c">· {{ c }}</div>
          </div>
          <div v-if="!lpResult.sample?.length" style="color:#909399;font-size:12px;margin-top:8px">未解析到任何频道</div>
        </template>
      </el-dialog>
    </el-card>

    <el-card class="card-block" shadow="never">
      <template #header>
        <div style="display:flex;align-items:center">
          <span>方案站点（{{ cfg.sites.length }}）</span>
          <div style="flex:1"></div>
          <el-button size="small" :loading="rechecking" @click="recheckSites">🔄 重测本方案</el-button>
        </div>
      </template>
      <div class="add-row">
        <el-select v-model="selectedSites" multiple filterable collapse-tags collapse-tags-tooltip
                   placeholder="选择要加入的站点（可多选）" style="flex:1; max-width: 380px">
          <el-option v-for="s in addable" :key="s.id" :label="`${s.name} (${s.key})`" :value="s.id" />
        </el-select>
        <el-button type="primary" plain @click="add" :disabled="!selectedSites.length">
          添加{{ selectedSites.length > 1 ? `（${selectedSites.length} 个）` : '' }}</el-button>
      </div>
      <div class="site-list">
        <div v-for="(s, i) in cfg.sites" :key="s.id" class="site-row">
          <span class="idx">{{ i + 1 }}</span>
          <span class="sname" @click="$router.push({ path: '/sites', query: { q: s.name } })"
                style="cursor:pointer" title="到站点页查看/测活">{{ s.name }}</span>
          <el-tag size="small" type="info">{{ typeLabel[s.site_type] || s.site_type }}</el-tag>
          <el-tooltip v-if="s.health === 'fail'" :content="s.health_msg || '近次测活失败'" placement="top">
            <el-tag size="small" type="danger" style="cursor:help">失效</el-tag>
          </el-tooltip>
          <el-tag v-else-if="s.health === 'ok'" size="small" type="success">正常</el-tag>
          <el-tag v-else-if="s.health === 'untested'" size="small" type="info">未测</el-tag>
          <span class="skey">{{ s.key }}</span>
          <div style="flex:1"></div>
          <el-button size="small" text :disabled="i === 0" @click="move(i, -1)">↑</el-button>
          <el-button size="small" text :disabled="i === cfg.sites.length - 1" @click="move(i, 1)">↓</el-button>
          <el-button size="small" text :type="s.overrides ? 'warning' : ''" @click="openOverrides(s)">
            {{ s.overrides ? '覆盖●' : '覆盖' }}
          </el-button>
          <el-button size="small" type="danger" text @click="removeSite(s)">移除</el-button>
        </div>
        <el-empty v-if="!cfg.sites.length" description="还没有站点，从上方添加" :image-size="70" />
      </div>
    </el-card>

    <el-card v-if="shareInfo || cfg.published_at" class="card-block" shadow="never">
      <template #header>
        <div style="display:flex;align-items:center">
          <span>分享链接（发布成功）</span>
          <div style="flex:1"></div>
          <el-button size="small" text @click="shareInfo = null">关闭</el-button>
        </div>
      </template>
      <div class="share-box">
        <div>订阅地址（填入 TVBox 配置地址）：</div>
        <code class="share-url">{{ origin }}/configs/{{ id }}/download?token={{ (shareInfo || cfg).share_token }}</code>
        <el-button size="small" @click="copyShare">复制</el-button>
        <el-button size="small" @click="showShareQr">二维码</el-button>
      </div>
      <div class="share-tip" v-if="(shareInfo || cfg).encrypted">
        内容已 2423 AES 加密：只有 TVBox/FongMi 输入正确配置才能解析，浏览器直接打开只会看到乱码。
      </div>
      <div class="share-tip" v-else style="color:#909399">
        当前为明文发布。建议开启「发布加密」，避免源配置被白嫖。
      </div>
    </el-card>

    <el-dialog v-model="ovDialog" :title="`站点字段覆盖 — ${ovSite?.name || ''}`" width="min(560px, 94vw)">
      <div class="ov-tip">
        仅覆盖该方案内此站点的字段（如 name/api/ext/jar），站点库原值不变。留 <code>{}</code> 保存即清除覆盖。
      </div>
      <el-input v-model="ovText" type="textarea" :rows="10" style="font-family: monospace"
        placeholder='如 {"name": "别名", "api": "https://..."}' />
      <template #footer>
        <el-button size="small" @click="formatOv">整理 JSON</el-button>
        <el-button @click="ovDialog = false">取消</el-button>
        <el-button type="primary" :loading="ovSaving" @click="saveOverrides">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="qrDialog" title="订阅二维码" width="300px" align-center>
      <div style="text-align: center">
        <img v-if="qrDataUrl" :src="qrDataUrl" alt="订阅二维码" style="width: 240px; height: 240px" />
      </div>
    </el-dialog>

    <el-dialog v-model="statsDialog" title="方案统计" width="min(380px, 94vw)" align-center>
      <template v-if="stats">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="启用站点">{{ stats.sites }} 个</el-descriptions-item>
          <el-descriptions-item label="已禁用（不进配置）">{{ stats.disabled }} 个</el-descriptions-item>
          <el-descriptions-item label="类型分布">
            <el-tag v-for="(n, t) in stats.types" :key="t" size="small" style="margin-right: 6px">
              {{ typeLabel[t] || t }} × {{ n }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="全局 spider">{{ stats.has_spider ? '已配置' : '未配置' }}</el-descriptions-item>
          <el-descriptions-item label="发布加密">{{ stats.encrypted ? '2423 加密' : '明文' }}</el-descriptions-item>
        </el-descriptions>
        <el-alert v-if="!stats.sites" type="warning" :closable="false" show-icon
                  title="方案中没有任何启用站点，发布会被拒绝" style="margin-top: 10px" />
      </template>
    </el-dialog>

    <el-card v-if="verifyResult" class="card-block" shadow="never">
      <template #header>
        <div style="display:flex;align-items:center">
          <span>解密自检（发布→下载→解密链路）</span>
          <div style="flex:1"></div>
          <el-button size="small" text @click="verifyResult = null">关闭</el-button>
        </div>
      </template>
      <el-result v-if="verifyResult.ok" icon="success"
                 :title="verifyResult.encrypted ? '密文可正常解密' : '明文 JSON 校验通过'"
                 :sub-title="`站点 ${verifyResult.sites} 个 · ${verifyResult.bytes} 字节 · 顶层字段: ${verifyResult.top_keys.join(', ')}`" />
      <el-result v-else icon="error" title="自检失败" :sub-title="verifyResult.error" />
    </el-card>

    <el-card v-if="preview" class="card-block" shadow="never">
      <template #header>
        <div style="display:flex;align-items:center">
          <span>预览（发布后实际输出）</span>
          <div style="flex:1"></div>
          <el-button size="small" text @click="preview = null">关闭</el-button>
        </div>
      </template>
      <pre class="preview-json">{{ preview }}</pre>
    </el-card>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.add-row { display: flex; gap: 8px; margin-bottom: 12px; }
.site-list { max-height: 420px; overflow-y: auto; }
.site-row { display: flex; align-items: center; gap: 8px; padding: 7px 4px; border-bottom: 1px solid #f0f0f0; flex-wrap: wrap; }
.site-row:last-child { border-bottom: none; }
@media (max-width: 640px) {
  .site-row :deep(.el-button) { margin-left: 0; }
  .site-row { row-gap: 2px; }
  .head { gap: 6px; }
  .head :deep(.el-button) { margin-left: 0; }
  .share-url { flex: 1; }
}
.share-url { background: #f5f7fa; padding: 6px 10px; border-radius: 4px; font-size: 12px; word-break: break-all; }
.idx { color: #909399; width: 24px; font-size: 13px; }
.sname { font-weight: 500; }
.skey { color: #909399; font-size: 12px; }
.share-tip { margin-top: 8px; color: #e6a23c; font-size: 12px; }
/* 直播源/解析结构化编辑 */
.st-tip { color: #909399; font-size: 12px; margin-bottom: 10px; }
.st-tip code { background: #f5f7fa; padding: 1px 4px; border-radius: 3px; }
.st-sec { margin-bottom: 14px; }
.st-sec:last-child { margin-bottom: 0; }
.st-title { font-weight: 600; font-size: 13px; margin-bottom: 8px; }
.st-row { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
.st-row .st-name { width: 150px; }
.st-row .st-url { flex: 1; min-width: 200px; }
.st-row .st-epg { width: 160px; }
.st-row .st-ua { width: 180px; }
.st-row .st-type { width: 190px; }
.rule-row { border: 1px dashed #dcdfe6; border-radius: 6px; padding: 8px; margin-bottom: 8px; }
.live-block { border: 1px dashed #dcdfe6; border-radius: 6px; padding: 8px; margin-bottom: 8px; }
.spider-hint { font-size: 12px; color: #909399; margin-top: 4px; width: 100%; }
.lp-sample { margin-top: 10px; }
.lp-g { font-weight: 600; font-size: 13px; margin-bottom: 4px; }
.lp-ch { color: #606266; font-size: 12px; padding-left: 12px; line-height: 1.7; }
.hist-wrap { overflow-x: auto; }
.diff-sum { font-size: 13px; color: #606266; margin-bottom: 10px; }
.diff-sec { margin-bottom: 10px; }
.diff-title { font-size: 13px; font-weight: 600; color: #303133; margin: 6px 0 4px; }
.diff-item { font-size: 12px; font-family: monospace; padding: 2px 6px; border-radius: 4px; word-break: break-all; }
.diff-item.add { color: #67c23a; background: #f0f9eb; }
.diff-item.del { color: #f56c6c; background: #fef0f0; }
.diff-item.chg { color: #e6a23c; background: #fdf6ec; }
.dg-list { margin-top: 10px; max-height: 420px; overflow-y: auto; }
.dg-row { display: flex; align-items: flex-start; gap: 8px; padding: 5px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; }
.dg-item { font-weight: 600; min-width: 110px; }
.dg-msg { color: #606266; word-break: break-all; }
@media (max-width: 640px) {
  .st-row .st-name, .st-row .st-url, .st-row .st-epg, .st-row .st-ua, .st-row .st-type { width: 100%; min-width: 0; flex: none; }
  .st-row { gap: 4px; }
}
.ov-tip { color: #909399; font-size: 12px; margin-bottom: 8px; }
.ov-tip code { background: #f5f7fa; padding: 1px 4px; border-radius: 3px; }
.preview-json {
  background: #282c34; color: #abb2bf; padding: 12px; border-radius: 6px;
  font-size: 12px; overflow: auto; max-height: 480px; margin: 0;
}
</style>
