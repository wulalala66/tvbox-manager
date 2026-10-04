import http from './http'

// 源库
export const importSites = (body) => http.post('/sites/import', body)
export const exportSites = (ids) => http.get('/sites/export', { params: ids ? { ids: ids.join(',') } : {} })
export const listSources = (params) => http.get('/sources', { params })
export const uploadSources = (formData, overwrite = false) =>
  http.post('/sources/upload' + (overwrite ? '?overwrite=true' : ''), formData)
export const importSourceUrl = (url, name) => http.post('/sources/import-url', null, { params: { url, name } })
export const getSource = (id) => http.get(`/sources/${id}`)
export const getSourceContent = (id) => http.get(`/sources/${id}/content`)
export const saveSourceContent = (id, body) => http.put(`/sources/${id}/content`, body)
export const getSourceVersions = (id) => http.get(`/sources/${id}/versions`)
export const rollbackSource = (id, v) => http.post(`/sources/${id}/rollback/${v}`)
export const getSourceUsages = (id) => http.get(`/sources/${id}/usages`)
export const updateSource = (id, body) => http.put(`/sources/${id}`, body)
export const deleteSource = (id, force) => http.delete(`/sources/${id}`, { params: { force } })
export const sourceRawUrl = (id) => `/sources/${id}/raw`

// 站点
export const listSites = (params) => http.get('/sites', { params })
export const createSite = (body) => http.post('/sites', body)
export const getSite = (id) => http.get(`/sites/${id}`)
export const updateSite = (id, body) => http.put(`/sites/${id}`, body)
export const deleteSite = (id) => http.delete(`/sites/${id}`)
export const reorderSites = (order) => http.post('/sites/reorder', { order })

// 配置方案
export const listConfigs = () => http.get('/configs')
export const createConfig = (body) => http.post('/configs', body)
export const getConfig = (id) => http.get(`/configs/${id}`)
export const updateConfig = (id, body) => http.put(`/configs/${id}`, body)
export const deleteConfig = (id) => http.delete(`/configs/${id}`)
export const setConfigSites = (id, sites) => http.put(`/configs/${id}/sites`, { sites })
export const addConfigSite = (id, siteId) => http.post(`/configs/${id}/sites/${siteId}`)
export const removeConfigSite = (id, siteId) => http.delete(`/configs/${id}/sites/${siteId}`)
export const publishConfig = (id) => http.post(`/configs/${id}/publish`)
export const publishVerify = (id) => http.post(`/configs/${id}/publish-verify`)
export const publishHistory = (id) => http.get(`/configs/${id}/publish-history`)
export const publishRollback = (id, file) => http.post(`/configs/${id}/publish-rollback`, { file })
export const diagnoseConfig = (id) => http.get(`/configs/${id}/diagnose`)
export const previewLive = (id, url) => http.post(`/configs/${id}/live-preview`, { url })
export const getConfigKey = (id) => http.get(`/configs/${id}/key`)
export const previewConfig = (id) => http.get(`/configs/${id}/preview`)
export const previewConfigStats = (id) => http.get(`/configs/${id}/preview/stats`)
export const downloadConfigUrl = (id) => `/configs/${id}/download`

// 导入向导
export const analyzeImport = (body) => http.post('/import/analyze', body)
export const commitImport = (body) => http.post('/import/commit', body)

// 测活
export const checkSite = (id) => http.post(`/sites/${id}/check`)
export const checkAllSites = (body) => http.post('/sites/check-all', body)
export const healthSummary = () => http.get('/health/summary')
export const healthHistory = () => http.get('/health/history')

// 批量操作
export const batchDeleteSites = (ids) => http.post('/sites/batch-delete', { ids })
export const batchEnableSites = (ids, enabled) => http.post('/sites/batch-enabled', { ids, enabled })
export const batchTagSites = (body) => http.post('/sites/batch-tag', body)
export const batchAddConfigSites = (configId, siteIds) => http.post(`/configs/${configId}/sites/batch-add`, { site_ids: siteIds })
export const batchRemoveConfigSites = (configId, siteIds) => http.post(`/configs/${configId}/sites/batch-remove`, { site_ids: siteIds })
export const duplicateConfig = (id, body) => http.post(`/configs/${id}/duplicate`, body || {})
export const checkProgress = () => http.get('/health/check-progress')
export const scanOrphans = () => http.get('/sources/orphans/scan')
export const cleanupOrphans = (body) => http.post('/sources/orphans/cleanup', body)
