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

const dirty = computed(() => contentLoaded.value && content.value !== savedContent.value)

async function save() {
  if (!dirty.value) { ElMessage.info('内容未修改，无需保存'); return }
  saving.value = true
  try {
    await saveSourceContent(id, { content: content.value, note: '在线编辑' })
    savedContent.value = content.value
    ElMessage.success('已保存')
    load()
  } catch (e) { ElMessage.error(e.message) }
  saving.value = false
}

async function rollback(v) {
  try {
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
          <el-button type="primary" :loading="saving" :disabled="!dirty" @click="save">保存（生成新版本）</el-button>
        </div>
      </el-tab-pane>
      <el-tab-pane label="下载" name="download" v-else>
        <p>jar 文件不支持在线编辑</p>
        <el-button type="primary"><a :href="`/sources/${id}/raw`" style="color:#fff;text-decoration:none">下载文件</a></el-button>
      </el-tab-pane>

      <el-tab-pane label="版本历史" name="versions">
        <el-table :data="versions" size="small">
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
  .src-desc { overflow-x: auto; }
  .src-desc :deep(.el-descriptions__table) { table-layout: fixed; width: 100%; }
  .src-desc :deep(.el-descriptions__label) { width: 76px; }
  .page :deep(.el-table__body) { width: 100% !important; }
  .page :deep(.el-table__header) { width: 100% !important; }
  .page :deep(.el-table__colgroup) { width: auto !important; }
  .page :deep(.el-textarea__inner) { font-size: 12px; }
  .ver-time { display: block; }
}
</style>
