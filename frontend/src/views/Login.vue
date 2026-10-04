<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import http from '../api/http'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function doLogin() {
  if (!password.value) { error.value = '请输入密码'; return }
  loading.value = true
  error.value = ''
  try {
    const r = await http.post('/login', { username: username.value, password: password.value })
    localStorage.setItem('tvbox_token', r.token)
    let redirect = sessionStorage.getItem('tvbox_redirect') || ''
    sessionStorage.removeItem('tvbox_redirect')
    redirect = redirect.replace(/^#/, '')  // 归一化（守卫/http 拦截都带 # 前缀）
    router.push(redirect || '/sites')
  } catch (e) {
    error.value = e.message || '登录失败'
  }
  loading.value = false
}
</script>

<template>
  <div class="login-wrap">
    <div class="login-card">
      <div class="logo">📦 TVBox 管理器</div>
      <div class="sub">请登录以继续</div>
      <el-form @submit.prevent="doLogin">
        <el-form-item>
          <el-input v-model="username" placeholder="账号" size="large" autofocus>
            <template #prefix>👤</template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-input v-model="password" type="password" placeholder="密码" size="large" show-password @keyup.enter="doLogin">
            <template #prefix>🔑</template>
          </el-input>
        </el-form-item>
        <div v-if="error" class="err">{{ error }}</div>
        <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="doLogin">
          登 录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.login-wrap {
  /* 固定视口，禁止整页滚动（用户反馈：登录窗口能上下滑动） */
  position: fixed; inset: 0; overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #1d2b3a 0%, #24344a 100%);
}
.login-card {
  width: 360px; max-width: 92vw; background: #fff; border-radius: 12px;
  padding: 36px 32px 28px; box-shadow: 0 8px 32px rgba(0,0,0,.25);
}
.logo { font-size: 20px; font-weight: 700; text-align: center; color: #1d2b3a; }
.sub { text-align: center; color: #909399; font-size: 13px; margin: 6px 0 22px; }
.err { color: #f56c6c; font-size: 13px; margin-bottom: 10px; text-align: center; }
</style>
