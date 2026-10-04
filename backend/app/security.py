"""认证与安全：管理员登录、会话 token、API 鉴权依赖"""
import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request

from .config import DATA_DIR

# ---- 管理员凭据 ----
ADMIN_USER = "admin"
# C1：密码不再硬编码。首启从 TVBOX_ADMIN_PASSWORD 环境变量读取（缺省为用户指定的初始密码），
# PBKDF2 哈希落盘 admin.creds 后源码中的明文即不再参与任何校验，可用 /login 改密覆盖。
import os as _os
ADMIN_PASSWORD = _os.environ.get("TVBOX_ADMIN_PASSWORD", <REDACTED>)

# 密码存储：PBKDF2-SHA256（首次启动生成盐并落盘，之后校验走哈希）
_CREDS_FILE = DATA_DIR / "admin.creds"


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()


def _init_creds():
    if not _CREDS_FILE.exists():
        salt = secrets.token_bytes(16)
        _CREDS_FILE.write_text(f"{salt.hex()}:{_hash_password(ADMIN_PASSWORD, salt)}")
        _CREDS_FILE.chmod(0o600)


_init_creds()


def verify_credentials(username: str, password: str) -> bool:
    if (username or "admin") != ADMIN_USER:  # 单用户部署：空用户名视为 admin
        return False
    try:
        salt_hex, stored = _CREDS_FILE.read_text().strip().split(":", 1)
        calc = _hash_password(password, bytes.fromhex(salt_hex))
        return hmac.compare_digest(calc, stored)
    except Exception:
        return False


def set_password(old_password: str, new_password: str) -> None:
    """修改管理员密码：校验旧密码 → 新盐重哈希落盘 → 吊销全部会话。"""
    if not verify_credentials(ADMIN_USER, old_password):
        raise HTTPException(400, "旧密码错误")
    if not new_password or len(new_password) < 8:
        raise HTTPException(400, "新密码至少 8 位")
    if len(new_password.encode()) > 72:
        raise HTTPException(400, "新密码过长")
    salt = secrets.token_bytes(16)
    _CREDS_FILE.write_text(f"{salt.hex()}:{_hash_password(new_password, salt)}")
    _CREDS_FILE.chmod(0o600)
    # 密码变更后吊销全部活跃会话（防旧 token 继续有效）
    _load_sessions()
    _sessions.clear()
    _save_sessions()


# ---- 会话 token ----
# 服务端随机 token，TTL 7 天；持久化到磁盘（重启不掉线，体验优化）
import json as _json
from pathlib import Path as _Path
_SESSION_TTL = 7 * 24 * 3600
_MAX_SESSIONS = 50  # 活跃会话上限，超出淘汰最早过期的 token
_SESSION_FILE = _Path(__file__).resolve().parents[2] / "data" / "sessions.json"
_sessions: dict[str, float] = {}  # token -> expires_at


_sessions_loaded = False


def _load_sessions():
    global _sessions_loaded
    if _sessions_loaded:
        return
    _sessions_loaded = True
    if not _SESSION_FILE.exists():
        return
    try:
        data = _json.loads(_SESSION_FILE.read_text())
        now = time.time()
        _sessions.update({t: e for t, e in data.items() if e > now})
    except Exception:
        pass  # 损坏文件当空会话


def _save_sessions():
    try:
        _SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SESSION_FILE.write_text(_json.dumps(_sessions))
        _SESSION_FILE.chmod(0o600)  # 含活跃 token，仅 root/服务用户可读
    except Exception:
        pass  # 持久化失败不阻断登录


def create_session() -> str:
    _load_sessions()
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + _SESSION_TTL
    # 顺手清理过期
    now = time.time()
    for t in [t for t, e in _sessions.items() if e < now]:
        del _sessions[t]
    # 限制最大活跃会话数（防反复登录无限堆积）：超出时淘汰最早过期的
    if len(_sessions) > _MAX_SESSIONS:
        overflow = sorted(_sessions.items(), key=lambda kv: kv[1])[:len(_sessions) - _MAX_SESSIONS]
        for t, _e in overflow:
            del _sessions[t]
    _save_sessions()
    return token


def drop_session(token: str):
    _sessions.pop(token, None)
    _save_sessions()


# ---- 审计日志（轻量：登录成败/登出追加到 data/audit.log）----
_AUDIT_FILE = DATA_DIR / "audit.log"


def _audit(request, event: str, detail: str = ""):
    try:
        ip = request.client.host if request.client else "unknown"
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(_AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {ip:<15} | {event} | {detail}\n")
    except Exception:
        pass  # 审计失败不阻断主流程


# ---- 登录防爆破 ----
_login_failures: dict[str, list[float]] = {}  # ip -> 失败时间戳（审查项 M8：按 IP 分桶只计失败）
_LOGIN_WINDOW = 300
_LOGIN_MAX_FAILS = 10


def _client_ip(request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limit_login(request=None):
    """登录限流：按 IP 统计失败次数，成功登录清零。"""
    now = time.time()
    ip = _client_ip(request) if request else "unknown"
    fails = [t for t in _login_failures.get(ip, []) if now - t < _LOGIN_WINDOW]
    _login_failures[ip] = fails
    if len(fails) >= _LOGIN_MAX_FAILS:
        raise HTTPException(429, "尝试过于频繁，请 5 分钟后再试")


def _record_login_failure(request):
    ip = _client_ip(request) if request else "unknown"
    _login_failures.setdefault(ip, []).append(time.time())


def _clear_login_failures(request):
    ip = _client_ip(request) if request else "unknown"
    _login_failures.pop(ip, None)


# ---- 请求鉴权 ----
# 允许匿名访问的路径前缀（公开静态资源 + TVBox 订阅下载）
PUBLIC_PREFIXES = (
    "/login", "/logout",
    "/assets/",
)


def _is_public(path: str) -> bool:
    if path in ("/", "/index.html", "/api/health"):
        return True
    if path.startswith(PUBLIC_PREFIXES):
        return True
    # TVBox 订阅：仅放行 download（凭 token，路由内校验）与静态资源兜底
    # /configs/{id}/download?token=...  /configs/{id}/{py|js|jar|live|theme}/{file}
    import re
    if re.fullmatch(r"/configs/\d+/download", path):
        return True
    if re.fullmatch(r"/configs/\d+/(?:py|js|jar|live|theme)/[^/]+", path):
        return True
    return False


def require_auth(request: Request) -> None:
    """全局鉴权入口（在 middleware 中调用）。"""
    if _is_public(request.url.path):
        return
    auth = request.headers.get("Authorization", "")
    _load_sessions()  # 惰性加载（重启后首次请求从磁盘恢复）
    if auth.startswith("Bearer "):
        token = auth[7:]
        exp = _sessions.get(token)
        if exp and exp > time.time():
            _sessions[token] = time.time() + _SESSION_TTL  # 滑动续期
            _save_sessions()
            return
    # 浏览器页面请求：接受 cookie（用于直接打开页面）
    cookie_token = request.cookies.get("tvbox_session")
    if cookie_token:
        exp = _sessions.get(cookie_token)
        if exp and exp > time.time():
            _sessions[cookie_token] = time.time() + _SESSION_TTL
            return
    raise HTTPException(401, "未登录或会话已过期")
