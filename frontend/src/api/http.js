import axios from 'axios'

const http = axios.create({ timeout: 60000 })

// 请求拦截：附带会话 token（localStorage）
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('tvbox_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

http.interceptors.response.use(
  (r) => r.data,
  (err) => {
    const d = err.response?.data
    let msg = typeof d === 'string' ? d : (d?.detail || err.message)
    if (typeof msg === 'object') {
      if (Array.isArray(msg.detail)) msg = msg.detail.map(x => x.msg || JSON.stringify(x)).join('; ')
      else msg = msg.detail || JSON.stringify(msg)
    }
    // 401：清会话并跳登录（非登录页时）
    if (err.response?.status === 401 && !location.hash.startsWith('#/login')) {
      localStorage.removeItem('tvbox_token')
      // 记住来源页，登录后跳回（体验优化）
      sessionStorage.setItem('tvbox_redirect', location.hash)
      location.hash = '#/login'
    }
    return Promise.reject(new Error(msg))
  }
)
export default http
