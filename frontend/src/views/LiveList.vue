<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { parseLive, fetchLive, listConfigs, updateConfig } from '../api'

const mode = ref('paste') // paste | url
const rawText = ref('')
const fetchUrl = ref('')
const busy = ref(false)
const result = ref(null) // { format, n_groups, n_channels, sample, groups }
const configs = ref([])
const targetConfig = ref(null)
const pushing = ref(false)

const fmtLabel = { txt: 'TXT（genre 分组）', m3u: 'M3U（group-title）', json: 'FongMi live JSON' }

async function loadConfigs() {
  try { configs.value = await listConfigs() } catch {}
}
onMounted(loadConfigs)

function pick(groups) {
  result.value = groups
}

async function doParse() {
  if (!rawText.value.trim()) return ElMessage.warning('请粘贴直播源内容')
  busy.value = true
  try {
    result.value = await parseLive({ text: rawText.value })
  } catch (e) { ElMessage.error(e.message) } finally { busy.value = false }
}

async function doFetch() {
  if (!fetchUrl.value.trim()) return ElMessage.warning('请填写直播源地址')
  busy.value = true
  try {
    result.value = await fetchLive({ url: fetchUrl.value.trim() })
  } catch (e) { ElMessage.error(e.message) } finally { busy.value = false }
}

// 把当前 url 以 lives 条目写入所选方案的 global_fields.lives（FongMi 结构）
async function pushToConfig() {
  if (!targetConfig.value) return ElMessage.warning('请选择目标配置方案')
  if (mode.value === 'url' && !fetchUrl.value.trim()) return ElMessage.warning('缺少直播源地址')
  pushing.value = true
  try {
    const cfg = configs.value.find(c => c.id === targetConfig.value)
    const gf = JSON.parse(JSON.stringify(cfg.global_fields || {}))
    const lives = Array.isArray(gf.lives) ? gf.lives : []
    const entry = mode.value === 'url'
      ? { name: result.value?.name || fetchUrl.value.split('/').pop() || '直播源', url: fetchUrl.value.trim() }
      : { name: '粘贴直播', ext: rawText.value }
    const i = lives.findIndex(l => l.name === entry.name)
    if (i >= 0) lives[i] = { ...lives[i], ...entry }
    else lives.push(entry)
    gf.lives = lives
    await updateConfig(cfg.id, {
      name: cfg.name, slug: cfg.slug,
      global_spider: cfg.global_spider || null,
      global_fields: gf, encrypt: cfg.encrypt,
    })
    ElMessage.success(`已写入方案「${cfg.name}」的 lives（共 ${lives.length} 条）`)
  } catch (e) { ElMessage.error(e.message) } finally { pushing.value = false }
}

const sampleAll = computed(() => result.value?.groups || [])
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>直播源</h1>
      <span class="sub">解析 TXT / M3U / FongMi live JSON，验证分组与频道，一键写入配置方案</span>
    </div>

    <el-card class="panel">
      <el-radio-group v-model="mode" style="margin-bottom:12px">
        <el-radio-button value="paste">粘贴内容</el-radio-button>
        <el-radio-button value="url">从地址抓取</el-radio-button>
      </el-radio-group>

      <el-input v-if="mode === 'paste'" v-model="rawText" type="textarea" :rows="10"
        placeholder="支持三种格式：&#10;① TXT：分组,#genre# 换行 频道名,url1#url2&#10;② M3U：#EXTINF group-title=…&#10;③ FongMi live JSON：{lives:[{group,channels:[{name,urls}]}]}" />
      <div v-else style="display:flex;gap:8px">
        <el-input v-model="fetchUrl" placeholder="直播列表地址（txt/m3u/json）" @keyup.enter="doFetch" />
        <el-button type="primary" :loading="busy" @click="doFetch">抓取</el-button>
      </div>

      <div v-if="mode === 'paste'" style="margin-top:10px">
        <el-button type="primary" :loading="busy" @click="doParse">解析</el-button>
      </div>
    </el-card>

    <el-card v-if="result" class="panel">
      <template #header>
        <div class="r-head">
          <span>解析结果：<el-tag size="small" type="success">{{ fmtLabel[result.format] || result.format }}</el-tag>
            {{ result.n_groups }} 组 · {{ result.n_channels }} 频道</span>
        </div>
      </template>

      <div class="push-row">
        <el-select v-model="targetConfig" placeholder="写入目标方案（可选）" clearable filterable style="width:240px">
          <el-option v-for="c in configs" :key="c.id" :label="`${c.id}. ${c.name}`" :value="c.id" />
        </el-select>
        <el-button type="success" plain :loading="pushing" @click="pushToConfig">写入方案 lives</el-button>
      </div>

      <div class="g-wrap">
        <div v-for="g in sampleAll" :key="g.name" class="g-card">
          <div class="g-title">📁 {{ g.name }} <span class="g-count">{{ g.channels.length }}</span></div>
          <div v-for="c in g.channels.slice(0, 8)" :key="c.name" class="g-ch">
            · {{ c.name }} <span class="g-urls">{{ c.urls.length }} 源</span>
          </div>
          <div v-if="g.channels.length > 8" class="g-more">…等 {{ g.channels.length }} 个频道</div>
        </div>
      </div>
    </el-card>

    <el-empty v-else description="粘贴或抓取直播源后点击解析" />
  </div>
</template>

<style scoped>
.page { padding: 16px; }
.page-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 14px; }
.page-head h1 { margin: 0; font-size: 20px; }
.sub { color: #909399; font-size: 13px; }
.panel { margin-bottom: 14px; }
.r-head { display: flex; justify-content: space-between; align-items: center; }
.push-row { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.g-wrap { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
.g-card { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px; }
.g-title { font-weight: 600; font-size: 13px; margin-bottom: 6px; }
.g-count { color: #909399; font-weight: 400; font-size: 12px; }
.g-ch { color: #606266; font-size: 12px; line-height: 1.8; }
.g-urls { color: #c0c4cc; font-size: 11px; }
.g-more { color: #c0c4cc; font-size: 11px; }
@media (max-width: 640px) {
  .page-head { flex-direction: column; gap: 4px; }
  .push-row .el-select { width: 100% !important; }
}
</style>
