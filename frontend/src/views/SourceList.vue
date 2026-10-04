<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listSources, deleteSource, uploadSources, importSourceUrl, getSourceUsages } from '../api'

const loading = ref(false)
const items = ref([])
const q = ref('')
const kind = ref('')
const fileRef = ref()
const urlDialog = ref(false)
const urlForm = ref({ url: '', name: '' })
const urlLoading = ref(false)

// 本地分页（与 SiteList 一致，30/页）：源量增长后桌面/移动视图都不至于一屏塞满
const page = ref(1)
const pageSize = ref(30)
const total = computed(() => items.value.length)
const pagedSources = computed(() =>
  items.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value)
)
function onPageChange(p) { page.value = p }

let loadSeq = 0
async function load() {
  const seq = ++loadSeq
  loading.value = true
  try {
    const params = {}
    if (q.value) params.q = q.value
    if (kind.value) params.kind = kind.value
    items.value = await listSources(params)
  } catch (e) { ElMessage.error(e.message) }
  if (seq !== loadSeq) return
  loading.value = false
}

let searchTimer = null
function onSearchInput() {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(load, 300)
}

function pickFiles() { fileRef.value.click() }
function pickOverwriteFiles() { overwriteMode.value = true; fileRef.value.click() }

// 上传模式：false=新建（重名自动改名） true=覆盖（同名同类型源生成新版本）
const overwriteMode = ref(false)

async function onFiles(e) {
  const files = [...e.target.files]
  e.target.value = ''
  const ow = overwriteMode.value
  overwriteMode.value = false
  if (!files.length) return
  const fd = new FormData()
  files.forEach(f => fd.append('files', f))
  try {
    const res = await uploadSources(fd, ow)
    const created = res.filter(r => r.created).length
    const overwritten = res.filter(r => r.overwritten).length
    const dup = res.length - created - overwritten
    ElMessage.success(
      `上传完成：新建 ${created} 个` +
      (overwritten ? `，覆盖 ${overwritten} 个（生成新版本）` : '') +
      (dup ? `，重复跳过 ${dup} 个` : '')
    )
    load()
  } catch (e) { ElMessage.error(e.message) }
}

async function doImportUrl() {
  if (!urlForm.value.url) return ElMessage.warning('请输入 URL')
  urlLoading.value = true
  try {
    const r = await importSourceUrl(urlForm.value.url, urlForm.value.name || undefined)
    ElMessage.success(r.created ? '导入成功' : '已存在相同内容源')
    urlDialog.value = false
    urlForm.value = { url: '', name: '' }
    load()
  } catch (e) { ElMessage.error(e.message) }
  urlLoading.value = false
}

const usageLoading = ref(false)
const usageItems = ref([])
async function loadUsages(row) {
  usageLoading.value = true
  usageItems.value = []
  try {
    const d = await getSourceUsages(row.id)
    usageItems.value = d.data ?? d
  } catch { usageItems.value = [] }
  usageLoading.value = false
}
async function remove(s) {
  const cited = s.ref_count > 0
  try {
    await ElMessageBox.confirm(
      cited
        ? `源「${s.name}」正被 ${s.ref_count} 个站点引用。继续将断开这些引用（站点保留），确认强制删除？`
        : `确认删除源「${s.name}」？`,
      '删除', { type: 'warning' })
  } catch { return }
  if (cited) {
    // 二次显式确认：列出具体引用站点
    let names = []
    try {
      const usages = await getSourceUsages(s.id)
      names = usages.map(u => `#${u.id} ${u.name || u.key}`)
    } catch { names = [`${s.ref_count} 个站点`] }
    try {
      await ElMessageBox.confirm(
        `最终确认：强制删除源「${s.name}」？将断开引用：${names.join('、')}`,
        '强制删除', { type: 'error', confirmButtonText: '强制删除' })
    } catch { return }
  }
  try {
    await deleteSource(s.id, cited)
    ElMessage.success('已删除')
    load()
  } catch (e) { ElMessage.error(e.message) }
}

const kindLabel = { js: 'JS', py: 'Python', jar: 'JAR' }
const kindColor = { js: 'warning', py: 'success', jar: 'danger' }

function fmtSize(n) {
  if (n < 1024) return n + ' B'
  if (n < 1048576) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1048576).toFixed(1) + ' MB'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <input ref="fileRef" type="file" multiple accept=".js,.py,.jar" style="display:none" @change="onFiles" />
    <div class="toolbar">
      <el-input v-model="q" placeholder="搜索名称/文件名" clearable style="width: 200px" @input="onSearchInput" @keyup.enter="load" @clear="load" />
      <el-select v-model="kind" placeholder="类型" clearable style="width: 110px" @change="load">
        <el-option label="JS" value="js" />
        <el-option label="Python" value="py" />
        <el-option label="JAR" value="jar" />
      </el-select>
      <el-button @click="load">筛选</el-button>
      <div style="flex:1"></div>
      <el-button type="primary" @click="pickFiles">上传文件</el-button>
      <el-button type="warning" plain @click="pickOverwriteFiles">覆盖上传</el-button>
      <el-button @click="urlDialog = true">URL 导入</el-button>
    </div>

    <div class="mobile-list">
      <el-card v-for="s in pagedSources" :key="s.id" class="m-card" shadow="never" @click="$router.push(`/sources/${s.id}`)">
        <div class="m-head">
          <el-tag :type="kindColor[s.kind]" size="small">{{ kindLabel[s.kind] }}</el-tag>
          <span class="m-name">{{ s.name }}</span>
        </div>
        <div class="m-file">{{ s.filename }} · {{ fmtSize(s.size) }} · v{{ s.current_version }}</div>
        <div class="m-foot">
          <span class="m-ref">{{ s.ref_count ? `${s.ref_count} 个站点引用` : '未引用' }}</span>
          <div style="flex:1"></div>
          <el-button v-if="s.kind !== 'jar'" size="small" type="primary" plain @click.stop="$router.push(`/sources/${s.id}`)">编辑</el-button>
          <el-button size="small" type="danger" plain @click.stop="remove(s)">删除</el-button>
        </div>
      </el-card>
    </div>

    <el-table :data="pagedSources" v-loading="loading" class="desktop-table" stripe>
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag :type="kindColor[row.kind]" size="small">{{ kindLabel[row.kind] }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column prop="filename" label="文件名" min-width="160" show-overflow-tooltip />
      <el-table-column label="大小" width="90">
        <template #default="{ row }">{{ fmtSize(row.size) }}</template>
      </el-table-column>
      <el-table-column prop="current_version" label="版本" width="70" />
      <el-table-column label="引用" width="80">
        <template #default="{ row }">
          <el-popover v-if="row.ref_count" placement="left" width="260" trigger="click" @show="loadUsages(row)">
            <template #reference>
              <span class="ref-link">{{ row.ref_count }}</span>
            </template>
            <div v-loading="usageLoading" class="usage-list">
              <div v-if="!usageLoading && !usageItems.length" class="usage-empty">无引用站点</div>
              <div v-for="u in usageItems" :key="u.id" class="usage-item" @click="$router.push(`/sites`)">
                <span class="usage-name">{{ u.name }}</span>
                <span class="usage-key">{{ u.key }}</span>
              </div>
            </div>
          </el-popover>
          <span v-else style="color: #c0c4cc">0</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="$router.push(`/sources/${row.id}`)">详情</el-button>
          <el-button size="small" type="primary" plain v-if="row.kind !== 'jar'"
                     @click="$router.push(`/sources/${row.id}`)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager-row" v-if="total > pageSize">
      <el-pagination
        layout="total, prev, pager, next"
        :total="total"
        :page-size="pageSize"
        :current-page="page"
        @current-change="onPageChange"
      />
    </div>

    <el-dialog v-model="urlDialog" title="从 URL 导入源" width="94%">
      <el-form label-width="70px">
        <el-form-item label="URL">
          <el-input v-model="urlForm.url" placeholder="https://.../spider.js" />
        </el-form-item>
        <el-form-item label="名称">
          <el-input v-model="urlForm.name" placeholder="留空自动取文件名" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="urlDialog = false">取消</el-button>
        <el-button type="primary" :loading="urlLoading" @click="doImportUrl">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.desktop-table { display: block; }
.mobile-list { display: none; }
.ref-link { color: #409eff; cursor: pointer; text-decoration: underline dotted; }
.usage-item { display: flex; justify-content: space-between; padding: 4px 0; cursor: pointer; border-bottom: 1px solid #ebeef5; font-size: 13px; }
.usage-item:last-child { border-bottom: none; }
.usage-name { color: #303133; }
.usage-key { color: #909399; font-size: 12px; }
.usage-empty { color: #909399; font-size: 12px; text-align: center; padding: 8px 0; }
.m-card { margin-bottom: 10px; cursor: pointer; }
.m-head { display: flex; align-items: center; gap: 8px; }
.m-name { font-weight: 600; }
.m-file { color: #909399; font-size: 12px; margin-top: 4px; }
.m-foot { display: flex; align-items: center; margin-top: 8px; }
.m-ref { color: #909399; font-size: 12px; }
.pager-row { display: flex; justify-content: flex-end; margin-top: 12px; }
@media (max-width: 768px) {
  .desktop-table { display: none; }
  .mobile-list { display: block; }
  .pager-row { justify-content: center; }
  .toolbar { flex-wrap: wrap; gap: 8px; }
  .toolbar .el-input, .toolbar .el-select { width: 100% !important; }
}
</style>
