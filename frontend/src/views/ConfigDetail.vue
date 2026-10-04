<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getConfig, updateConfig, setConfigSites, addConfigSite, removeConfigSite,
  listSites, publishConfig, publishVerify, previewConfig, batchAddConfigSites, previewConfigStats,
} from '../api'

const route = useRoute()
const id = route.params.id
const cfg = ref(null)
const allSites = ref([])
const selectedSites = ref([])
const preview = ref(null)
const saving = ref(false)
const editForm = ref({ name: '', slug: '', global_spider: '', global_fields: '{}',
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
      encrypt: !!cfg.value.encrypt, enc_key: '', enc_key_set: !!cfg.value.enc_key_set,
    }
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

onMounted(load)
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
        <el-form-item label="全局 spider"><el-input v-model="editForm.global_spider" placeholder="./jar/spider.jar" /></el-form-item>
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
      <template #header>方案站点（{{ cfg.sites.length }}）</template>
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
.ov-tip { color: #909399; font-size: 12px; margin-bottom: 8px; }
.ov-tip code { background: #f5f7fa; padding: 1px 4px; border-radius: 3px; }
.preview-json {
  background: #282c34; color: #abb2bf; padding: 12px; border-radius: 6px;
  font-size: 12px; overflow: auto; max-height: 480px; margin: 0;
}
</style>
