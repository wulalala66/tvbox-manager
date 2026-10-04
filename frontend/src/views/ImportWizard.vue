<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { analyzeImport, commitImport } from '../api'

const router = useRouter()
const step = ref(0)  // 0 输入 1 确认 2 完成
const inputType = ref('text')
const text = ref('')
const url = ref('')
const analyzing = ref(false)
const analysis = ref(null)   // { top_keys, spider, candidates }
const selected = ref({})     // key -> bool
const commitResult = ref(null)
const committing = ref(false)

async function analyze() {
  analyzing.value = true
  try {
    const body = inputType.value === 'url' ? { type: 'url', url: url.value } : { type: 'text', content: text.value }
    analysis.value = await analyzeImport(body)
    if (!analysis.value.candidates?.length) {
      ElMessage.warning('未解析到站点')
    } else {
      analysis.value.candidates.forEach(c => { selected.value[c.key] = true })
      step.value = 1
    }
  } catch (e) { ElMessage.error(e.message) }
  analyzing.value = false
}

const chosen = () => (analysis.value?.candidates || []).filter(c => selected.value[c.key])

async function commit() {
  committing.value = true
  try {
    commitResult.value = await commitImport({
      candidates: chosen(),
      top_fields: keepTop.value ? (analysis.value.top_fields || {}) : {},
      spider: keepTop.value ? (analysis.value.spider || null) : null,
      config_id: keepTop.value ? targetConfig.value : null,
    })
    step.value = 2
  } catch (e) { ElMessage.error(e.message) }
  committing.value = false
}

function reset() {
  step.value = 0; analysis.value = null; selected.value = {}; commitResult.value = null
  text.value = ''; url.value = ''
}

const kindLabel = { js: 'JS', py: 'PY', jar: 'JAR' }
const configs = ref([])
const targetConfig = ref(null)
import { listConfigs } from '../api'
listConfigs().then(d => { configs.value = d }).catch(() => {})
const keepTop = ref(true)
</script>

<template>
  <div class="page">
    <el-steps :active="step" align-center style="margin-bottom: 20px">
      <el-step title="输入配置" />
      <el-step title="确认导入" />
      <el-step title="完成" />
    </el-steps>

    <!-- 步骤 0：输入 -->
    <el-card v-if="step === 0" shadow="never">
      <el-radio-group v-model="inputType" style="margin-bottom: 14px">
        <el-radio-button value="text">粘贴配置</el-radio-button>
        <el-radio-button value="url">配置 URL</el-radio-button>
      </el-radio-group>

      <el-input v-if="inputType === 'url'" v-model="url" placeholder="https://example.com/config.json" />
      <el-input v-else v-model="text" type="textarea" :rows="12" style="font-family: monospace"
                placeholder='粘贴 vod.json / TVBox 配置（支持明文 JSON、** Base64、2423 加密配置）' />

      <div style="margin-top: 14px; text-align: right">
        <el-button type="primary" :loading="analyzing" @click="analyze">解析</el-button>
      </div>
    </el-card>

    <!-- 步骤 1：确认 -->
    <el-card v-if="step === 1" shadow="never">
      <div class="ana-info" v-if="analysis">
        <el-tag v-if="analysis.spider" type="warning" style="margin-right: 8px">spider: {{ analysis.spider }}</el-tag>
        <span class="muted">顶层字段: {{ analysis.top_keys?.join(', ') || '—' }}</span>
      </div>
      <el-alert v-if="analysis.top_keys?.length && keepTop" type="info" :closable="false"
        title="将同时导入顶层字段（lives/parses/全局 spider 等）" style="margin-bottom: 10px" />
      <div class="cfg-row">
        <span class="muted">同时更新配置方案：</span>
        <el-select v-model="targetConfig" clearable placeholder="选择方案（可选）" style="width: 220px" size="small">
          <el-option v-for="c in configs" :key="c.id" :label="c.name" :value="c.id" />
        </el-select>
        <el-checkbox v-if="analysis.top_keys?.length" v-model="keepTop" size="small">导入顶层字段</el-checkbox>
      </div>
      <div class="cand-list">
        <div v-for="c in analysis.candidates" :key="c.key" class="cand">
          <el-checkbox v-model="selected[c.key]" />
          <div class="cand-body">
            <div class="cand-head">
              <b>{{ c.name || c.key }}</b>
              <el-tag size="small" :type="c.kind ? 'success' : 'info'">{{ kindLabel[c.kind] || (c.site_type === 0 ? 'XML' : c.site_type === 1 ? 'JSON' : c.site_type) }}</el-tag>
              <span class="muted">{{ c.key }}</span>
            </div>
            <div class="cand-api">{{ c.api }}</div>
            <div v-if="c.suggested_filename" class="muted">源文件: {{ c.suggested_filename }} <el-tag v-if="c.existing_source_id" size="small" type="success">复用已有源</el-tag></div>
            <el-alert v-for="(w, i) in c.warnings" :key="i" :title="w" type="warning" :closable="false" style="margin-top: 4px; padding: 4px 8px" />
          </div>
        </div>
      </div>
      <div class="foot">
        <el-button @click="step = 0">上一步</el-button>
        <el-button type="primary" :loading="committing" :disabled="!chosen().length" @click="commit">
          导入 {{ chosen().length }} 个站点
        </el-button>
      </div>
    </el-card>

    <!-- 步骤 2：完成 -->
    <el-card v-if="step === 2" shadow="never">
      <el-result icon="success" title="导入完成"
        :sub-title="`新增 ${commitResult.created.length} 个站点${commitResult.skipped.length ? '，跳过 ' + commitResult.skipped.length + ' 个' : ''}`">
        <template #extra>
          <el-button type="primary" @click="router.push('/sites')">查看站点</el-button>
          <el-button @click="reset">继续导入</el-button>
        </template>
      </el-result>
      <el-alert v-for="(s, i) in commitResult.skipped" :key="i" :title="`${s.key || '?'}: ${s.reason}`" type="warning" :closable="false" style="margin-bottom: 6px" />
    </el-card>
  </div>
</template>

<style scoped>
.ana-info { margin-bottom: 12px; }
.muted { color: #909399; font-size: 12px; }
.cand-list { max-height: 55vh; overflow-y: auto; }
.cand { display: flex; gap: 10px; padding: 10px 4px; border-bottom: 1px solid #f0f0f0; align-items: flex-start; }
.cand:last-child { border-bottom: none; }
.cand-body { flex: 1; min-width: 0; }
.cand-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cand-api { color: #606266; font-size: 12px; word-break: break-all; margin-top: 2px; }
.foot { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
.cfg-row { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
</style>
