<script setup>
import { ref, computed, onMounted } from 'vue'
import http from '../api/http'
import { ElMessage } from 'element-plus'

const items = ref([])
const loading = ref(false)
const eventFilter = ref('')

const EVENT_TYPES = ['login_ok', 'login_fail', 'logout', 'password_change']

function exportCsv() {
  fetch('/audit-logs/export', { headers: { Authorization: 'Bearer ' + localStorage.getItem('tvbox_token') } })
    .then(r => { if (!r.ok) throw new Error('导出失败 ' + r.status); return r.blob() })
    .then(b => {
      const url = URL.createObjectURL(b)
      const a = document.createElement('a')
      a.href = url
      a.download = 'audit_export.csv'
      a.click()
      URL.revokeObjectURL(url)
      ElMessage.success('已导出')
    })
    .catch(e => ElMessage.error(e.message))
}
async function load() {
  loading.value = true
  try {
    const r = await http.get('/audit-logs', { params: { limit: 500 } })
    items.value = (r && r.items) || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const filtered = computed(() =>
  eventFilter.value ? items.value.filter(i => i.event === eventFilter.value) : items.value
)

function eventTagType(ev) {
  if (ev === 'login_fail') return 'danger'
  if (ev === 'password_change') return 'warning'
  if (ev === 'login_ok') return 'success'
  return 'info'
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h2>📋 审计日志</h2>
      <div class="actions">
        <el-select v-model="eventFilter" placeholder="全部事件" clearable style="width: 160px">
          <el-option v-for="ev in EVENT_TYPES" :key="ev" :label="ev" :value="ev" />
        </el-select>
        <el-button @click="load" :loading="loading">刷新</el-button>
        <el-button type="primary" plain @click="exportCsv">导出 CSV</el-button>
      </div>
    </div>

    <div class="table-wrap">
      <el-table :data="filtered" v-loading="loading" size="small" stripe>
        <el-table-column prop="time" label="时间" width="150" />
        <el-table-column prop="ip" label="IP" width="110" />
        <el-table-column label="事件" width="110">
          <template #default="{ row }">
            <el-tag :type="eventTagType(row.event)" size="small">{{ row.event }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="详情" min-width="120" />
      </el-table>
    </div>
    <div v-if="!loading && !filtered.length" class="empty">暂无日志</div>
  </div>
</template>

<style scoped>
.page-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; flex-wrap: wrap; gap: 8px; }
@media (max-width: 640px) { .page-head .actions { width: 100%; justify-content: flex-start; } }
.actions { display: flex; gap: 8px; }
.table-wrap { overflow-x: auto; }
.empty { text-align: center; color: #7a8ba0; padding: 24px 0; }
</style>
