<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, onBeforeRouteLeave } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getSource, getSourceContent, saveSourceContent, getSourceVersions, rollbackSource, getSourceUsages } from '../api'

const route = useRoute()
const id = route.params.id
const info = ref(null)
const content = ref('')
const contentLoaded = ref(false)
const versions = ref([])
const usages = ref([])
const tab = ref('info')
const saving = ref(false)
const savedContent = ref('')  // 服务器上的最新内容基线，用于 dirty 比对

const isText = computed(() => info.value && info.value.kind !== 'jar')

// 移动端判定（版本历史用卡片布局替代表格）
const isMobile = ref(window.innerWidth <= 640)
window.addEventListener('resize', () => { isMobile.value = window.innerWidth <= 640 })

function fmtTs(ts) {
  if (!ts) return ''
  const d = new Date(ts.includes('T') ? ts : ts.replace(' ', 'T'))
  return isNaN(d) ? ts : d.toLocaleString('zh-CN', { hour12: false })
}

async function load() {
  try {
    info.value = await getSource(id)
    usages.value = await getSourceUsages(id)
    if (isText.value) {
      const c = await getSourceContent(id)
      content.value = c.content
      savedContent.value = c.content
      contentLoaded.value = true
    }
    versions.value = await getSourceVersions(id)
  } catch (e) { ElMessage.error(e.message) }
}

// 只刷新元信息与版本历史，不动编辑器内容（避免覆盖保存后继续输入的字符）
async function loadMeta() {
  try {
    info.value = await getSource(id)
    versions.value = await getSourceVersions(id)
  } catch (e) { ElMessage.error(e.message) }
}

const dirty = computed(() => contentLoaded.value && content.value !== savedContent.value)

// 保存前轻量语法预检：py 用后端 compile 校验，js/json 用浏览器端启发式
const syntaxStatus = computed(() => {
  const kind = info.value?.kind
  const txt = content.value
  if (!dirty.value || !txt.trim()) return null
  if (kind === 'json') {
    try { JSON.parse(txt); return { level: 'ok', text: '✓ 合法 JSON' } }
    catch (e) { return { level: 'bad', text: `✗ JSON 语法错误：${e.message.slice(0, 60)}` } }
  }
  if (kind === 'py') {
    // 浏览器无法编译 python：只做括号/引号平衡粗检，精确校验交给保存后端 compile
    // 逐行扫描：跳过整行注释与多行字符串的简化处理——按行处理，行内先截断 # 注释
    const pairs = { '(': ')', '[': ']', '{': '}' }
    const stack = []
    let inS = null, esc = false, lineComment = false
    for (const ch of txt) {
      if (ch === '\n') { lineComment = false; continue }
      if (lineComment) continue
      if (esc) { esc = false; continue }
      if (ch === '\\') { esc = true; continue }
      if (inS) { if (ch === inS) inS = null; continue }
      if (ch === '"' || ch === "'") { inS = ch; continue }
      if (ch === '#') { lineComment = true; continue }
      if (pairs[ch]) stack.push(pairs[ch])
      else if (Object.values(pairs).includes(ch)) {
        if (stack.pop() !== ch) return { level: 'warn', text: '⚠ 括号可能不平衡' }
      }
    }
    if (inS) return { level: 'warn', text: '⚠ 引号未闭合' }
    if (stack.length) return { level: 'warn', text: '⚠ 括号可能不平衡' }
    return null
  }
  if (kind === 'js') {
    try { new Function(txt); return null }
    catch (e) { return { level: 'warn', text: `⚠ JS 语法可疑：${String(e.message).slice(0, 60)}` } }
  }
  return null
})

async function copyAll() {
  try { await navigator.clipboard.writeText(content.value); ElMessage.success(`已复制 ${content.value.length} 字符`) }
  catch { ElMessage.error('复制失败（浏览器剪贴板权限）') }
}

async function save() {
  if (!dirty.value) { ElMessage.info('内容未修改，无需保存'); return }
  if (syntaxStatus.value?.level === 'bad' &&
      !window.confirm('当前内容存在语法错误，仍要保存吗？（可在版本历史回滚）')) return
  saving.value = true
  try {
    await saveSourceContent(id, { content: content.value, note: '在线编辑' })
    savedContent.value = content.value
    ElMessage.success('已保存')
    loadMeta()
  } catch (e) { ElMessage.error(e.message) }
  saving.value = false
}

async function rollback(v) {
  try {
    if (dirty.value && !window.confirm('有未保存的修改，回滚将覆盖编辑器内容，确定？')) return
    await rollbackSource(id, v.version)
    ElMessage.success(`已回滚到 v${v.version}`)
    load()
  } catch (e) { ElMessage.error(e.message) }
}

function formatJson() {
  try {
    content.value = JSON.stringify(JSON.parse(content.value), null, 2)
    ElMessage.success('已格式化')
  } catch (e) { ElMessage.error('不是合法 JSON，无法整理') }
}

const metaList = computed(() => {
  const m = info.value?.meta || {}
  return Object.entries(m).map(([k, v]) => ({ k, v: typeof v === 'object' ? JSON.stringify(v) : String(v) }))
})

onMounted(load)

onBeforeRouteLeave(() => {
  if (dirty.value && !window.confirm('有未保存的修改，确定离开？')) return false
})
</script>

<template>
  <div class="page" v-if="info">
    <div class="head">
      <el-button size="small" @click="$router.back()">← 返回</el-button>
      <h3 style="margin:0">{{ info.name }}</h3>
      <el-tag size="small">{{ info.kind.toUpperCase() }}</el-tag>
      <span class="sub">{{ info.filename }} · v{{ info.current_version }}</span>
      <el-tag v-if="dirty" size="small" type="warning">未保存</el-tag>
      <el-tag v-if="syntaxStatus" size="small" :type="syntaxStatus.level === 'bad' ? 'danger' : syntaxStatus.level === 'warn' ? 'warning' : 'success'">
        {{ syntaxStatus.text }}</el-tag>
    </div>

    <el-tabs v-model="tab">
      <el-tab-pane label="信息" name="info">
        <el-descriptions :column="1" border size="small" class="src-desc">
          <el-descriptions-item label="文件名">{{ info.filename }}</el-descriptions-item>
          <el-descriptions-item label="SHA256"><span class="sha-val">{{ info.sha256 }}</span></el-descriptions-item>
          <el-descriptions-item label="备注">{{ info.note || '—' }}</el-descriptions-item>
          <el-descriptions-item v-for="m in metaList" :key="m.k" :label="m.k">{{ m.v }}</el-descriptions-item>
        </el-descriptions>
        <h4>引用站点（{{ usages.length }}）</h4>
        <el-tag v-for="u in usages" :key="u.id" style="margin: 0 6px 6px 0">{{ u.name }}</el-tag>
        <el-empty v-if="!usages.length" description="无引用" :image-size="60" />
      </el-tab-pane>

      <el-tab-pane label="内容" name="content" v-if="isText">
        <el-input v-model="content" type="textarea" :rows="22" resize="vertical"
                  class="code-editor" />
        <div style="margin-top: 10px; text-align: right; display: flex; gap: 8px; justify-content: flex-end">
          <el-button @click="formatJson" v-if="info.filename.endsWith('.json')">整理 JSON</el-button>
          <el-button @click="copyAll">复制全文</el-button>
          <el-button type="primary" :loading="saving" :disabled="!dirty" @click="save">保存（生成新版本）</el-button>
        </div>
      </el-tab-pane>
      <el-tab-pane label="下载" name="download" v-else>
        <p>jar 文件不支持在线编辑</p>
        <el-button type="primary"><a :href="`/sources/${id}/raw`" style="color:#fff;text-decoration:none">下载文件</a></el-button>
      </el-tab-pane>

      <el-tab-pane label="版本历史" name="versions">
        <!-- 桌面表格 / 移动卡片双布局：el-table 470px 总宽在 390px 容器被 header-wrapper 裁剪 -->
        <div class="ver-cards" v-if="isMobile">
          <div class="ver-card" v-for="v in versions" :key="v.version">
            <div class="ver-card-head">
              <span class="ver-badge" :class="{ cur: v.version === info.current_version }">v{{ v.version }}</span>
              <el-button size="small" type="primary" plain :disabled="v.version === info.current_version" @click="rollback(v)">回滚到此版</el-button>
            </div>
            <div class="ver-note">{{ v.note || '—' }}</div>
            <div class="ver-ts">{{ fmtTs(v.created_at) }}</div>
          </div>
        </div>
        <el-table v-else :data="versions" size="small">
          <el-table-column prop="version" label="版本" width="70" />
          <el-table-column prop="note" label="说明" min-width="140" />
          <el-table-column prop="created_at" label="时间" min-width="160" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button size="small" :disabled="row.version === info.current_version" @click="rollback(row)">回滚</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.head { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; flex-wrap: wrap; }
.head h3 { font-size: 16px; word-break: break-all; }
.sub { color: #909399; font-size: 13px; word-break: break-all; }
.sha-val { word-break: break-all; font-family: monospace; font-size: 12px; }
.page { min-width: 0; }
.page :deep(.el-tabs__nav-wrap) { overflow-x: auto; }
.page :deep(.el-textarea__inner) { font-family: monospace; }
.page :deep(.el-table) { width: 100%; }
@media (max-width: 640px) {
  /* 信息 tab：强制 fixed 布局 + 长值换行，消除 467px 内容横滚（根因：methods/hosts 长 JSON 不换行） */
  .src-desc { width: 100%; }
  .src-desc :deep(.el-descriptions__table) { table-layout: fixed; width: 100% !important; }
  .src-desc :deep(.el-descriptions__label) { width: 88px; word-break: break-all; }
  .src-desc :deep(.el-descriptions__content) { word-break: break-all; overflow-wrap: anywhere; white-space: normal !important; }
  .src-desc :deep(.el-descriptions__body .el-descriptions__table) { display: table; }
  .src-desc :deep(.el-descriptions__cell) { display: table-cell; }
  .page :deep(.el-textarea__inner) { font-size: 12px; }
  .ver-time { display: block; }

  /* 版本历史移动卡片布局（替代表格，防裁剪溢出） */
  .ver-cards { display: flex; flex-direction: column; gap: 8px; }
  .ver-card { border: 1px solid #ebeef5; border-radius: 8px; padding: 10px 12px; background: #fff; }
  .ver-card-head { display: flex; justify-content: space-between; align-items: center; }
  .ver-badge { font-weight: 600; font-size: 14px; color: #409eff; }
  .ver-badge.cur { color: #67c23a; }
  .ver-badge.cur::after { content: ' · 当前'; font-size: 12px; font-weight: 400; }
  .ver-note { font-size: 13px; color: #606266; margin-top: 4px; word-break: break-all; }
  .ver-ts { font-size: 12px; color: #909399; margin-top: 4px; }
}
@media (min-width: 641px) { .ver-cards { display: none; } }
</style>
