"""应用入口：路由组装 + 管理端登录鉴权 + SPA 托管 + TVBox 静态源托管"""
import mimetypes
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import DATA_DIR, SOURCES_DIR
from .database import init_db
from .routers import configs, health, importer, lives, sites, sources
from .security import (ADMIN_USER, _audit, _clear_login_failures,
                       _rate_limit_login, _record_login_failure, create_session,
                       drop_session, require_auth, set_password, verify_credentials)

app = FastAPI(title="TVBox Manager", version="0.2.0")

# 前后端同源（同一个 FastAPI 服务），CORS 收紧为本机
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """全局鉴权 + 安全响应头：除公开路径外一律要求有效会话。"""
    try:
        require_auth(request)
    except HTTPException as e:
        return JSONResponse({"detail": e.detail}, status_code=e.status_code,
                            headers=_SEC_HEADERS)
    resp = await call_next(request)
    for k, v in _SEC_HEADERS.items():
        resp.headers[k] = v
    return resp


_SEC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@app.on_event("startup")
def startup():
    init_db()
    # 后台定时自动测活（每 6 小时一轮，结果进站点 last_test_result 与健康历史）
    from .routers.health import start_auto_check_thread
    start_auto_check_thread()


# ---- 登录 / 登出 ----
class LoginIn(BaseModel):
    username: str
    password: str


@app.post("/login")
def login(body: LoginIn, request: Request):
    _rate_limit_login(request)
    if not verify_credentials(body.username, body.password):
        _record_login_failure(request)
        _audit(request, "login_fail", f"user={body.username!r}")
        raise HTTPException(401, "账号或密码错误")
    _clear_login_failures(request)
    token = create_session()
    _audit(request, "login_ok", f"user={body.username}")
    resp = JSONResponse({"ok": True, "token": token, "username": ADMIN_USER})
    # cookie 供浏览器直接打开页面（前端 API 仍用 Authorization header）
    resp.set_cookie("tvbox_session", token, max_age=7 * 24 * 3600,
                    httponly=True, samesite="lax", path="/")
    return resp


@app.post("/logout")
def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.cookies.get("tvbox_session", "")
    if token:
        drop_session(token)
    _audit(request, "logout")
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("tvbox_session", path="/")
    return resp


# ---- 修改密码（需登录态；成功后全部会话吊销需重新登录）----
class ChangePwIn(BaseModel):
    old_password: str
    new_password: str


@app.post("/change-password")
def change_password(body: ChangePwIn, request: Request):
    set_password(body.old_password, body.new_password)
    _audit(request, "password_change")
    # 走到这里 set_password 已清空全部会话；当前请求的 token 也已失效
    resp = JSONResponse({"ok": True, "message": "密码已修改，请重新登录"})
    resp.delete_cookie("tvbox_session", path="/")
    return resp


@app.get("/api/health")
def health_endpoint():
    return {"ok": True, "app": "tvbox-manager"}


@app.get("/audit-logs/export")
def audit_logs_export():
    """导出审计日志为 CSV（需登录；中间件已保护）。带 BOM，Excel 打开不乱码。"""
    import csv
    import io
    from fastapi import Response
    from .config import DATA_DIR
    log_path = DATA_DIR / "audit.log"
    lines = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            lines = []
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time", "ip", "event", "detail"])
    for raw in lines:
        raw = raw.rstrip("\n")
        if not raw:
            continue
        parts = [s.strip() for s in raw.split("|", 3)]
        if len(parts) >= 3:
            w.writerow([parts[0], parts[1], parts[2], parts[3] if len(parts) == 4 else ""])
        else:
            w.writerow(["", "", raw, ""])
    content = "\ufeff" + buf.getvalue()
    import datetime as _dt
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="audit_{stamp}.csv"',
                 "Cache-Control": "no-store"},
    )


# ---- 数据备份：整包导出 DB + 源文件 + 配置（需登录；中间件已保护）----
@app.get("/backup")
def backup_download(request: Request):
    """打包 data/ 全量（SQLite + 源文件 + 配置 + 历史/日志）为 zip 供下载。"""
    import io
    import zipfile
    import datetime as _dt
    from fastapi import Response
    from .config import DATA_DIR

    _audit(request, "backup_download")

    buf = io.BytesIO()
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    skip_suffixes = {"-shm", "-wal"}  # WAL 事务中文件，不进备份（DB 文件本体即可恢复）
    # 凭据/会话/审计是运行时状态：不进备份（恢复不应回滚密码与会话，审计流水不随快照走）
    skip_names = {"admin.creds", "sessions.json", "audit.log"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(DATA_DIR.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(DATA_DIR)
            if any(rel.suffixes and str(rel).endswith(s) for s in skip_suffixes):
                continue
            if rel.parts[0] == "backups" or rel.parts[0] == "logs" or p.name in skip_names:
                continue
            try:
                zf.write(p, arcname=str(rel))
            except OSError:
                continue
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tvbox_backup_{stamp}.zip"',
                 "Cache-Control": "no-store"},
    )


@app.get("/backup/info")
def backup_info():
    """备份内容概览：文件数、总大小、各目录条数（供 UI 展示）。"""
    from .config import DATA_DIR
    import os
    total_files, total_size = 0, 0
    parts = {}
    for p in DATA_DIR.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(DATA_DIR)
        if rel.parts[0] == "backups":
            continue
        total_files += 1
        try:
            total_size += p.stat().st_size
        except OSError:
            pass
        top = rel.parts[0] if len(rel.parts) > 1 else "(root)"
        parts[top] = parts.get(top, 0) + 1
    return {"files": total_files, "size": total_size,
            "parts": parts, "db_tables": None}


@app.post("/backup/restore")
async def backup_restore(request: Request, file: UploadFile = File(...)):
    """备份恢复：上传 /backup 导出的 zip，原子还原 data/（DB+源文件+配置）。"""
    from .config import DATA_DIR, DB_PATH
    from .database import engine
    import io
    import os
    import shutil
    import sqlite3
    import zipfile
    import datetime as _dt

    content = await file.read()
    ALLOWED_TOP = {"tvbox.db", "sources", "configs", "imports", "logs", "health_history.json"}
    MAX_FILE = 64 * 1024 * 1024
    MAX_TOTAL = 256 * 1024 * 1024

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise HTTPException(400, "不是有效的 zip 备份文件")

    entries = zf.infolist()
    if not any(i.filename == "tvbox.db" for i in entries):
        raise HTTPException(400, "缺少 tvbox.db，不是本系统的备份包")

    # 1) 校验全部条目路径安全 + 大小（zip-slip 防护）
    total = 0
    cleaned = []  # (zipinfo, safe_rel)
    for info in entries:
        name = info.filename
        if name.endswith("/"):
            continue
        rel = os.path.normpath(name).lstrip("/\\")
        if rel.startswith("..") or os.path.isabs(name):
            raise HTTPException(400, f"备份包含非法路径: {name}")
        top = rel.replace("\\", "/").split("/", 1)[0]
        if top not in ALLOWED_TOP:
            raise HTTPException(400, f"备份包含未知顶层条目: {name}")
        if info.file_size > MAX_FILE:
            raise HTTPException(400, f"条目过大: {name}")
        total += info.file_size
        if total > MAX_TOTAL:
            raise HTTPException(400, "备份包解压总量超限")
        if rel.endswith("-shm") or rel.endswith("-wal"):
            continue
        cleaned.append((info, rel))

    # 2) 还原前安全快照（当前 data/ 打包留存到 data/backups/pre_restore_*，可人工回退）
    #    顺带清理 7 天前的旧快照，防止无限堆积
    cutoff = _dt.datetime.now() - _dt.timedelta(days=7)
    for old in (DATA_DIR / "backups").glob("pre_restore_*"):
        try:
            if _dt.datetime.strptime(old.name, "pre_restore_%Y%m%d_%H%M%S") < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except ValueError:
            pass
    snap_dir = DATA_DIR / "backups" / f"pre_restore_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    snap_dir.mkdir(parents=True, exist_ok=True)
    for p in DATA_DIR.rglob("*"):
        if not p.is_file() or p.relative_to(DATA_DIR).parts[0] == "backups":
            continue
        if p.name.endswith("-shm") or p.name.endswith("-wal"):
            continue
        dst = snap_dir / p.relative_to(DATA_DIR)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(p, dst)
        except OSError:
            pass

    # 3) DB 校验 + 原子替换
    db_bytes = zf.read([i for i, r in cleaned if r == "tvbox.db"][0])
    if db_bytes[:15] != b"SQLite format 3":
        raise HTTPException(400, "tvbox.db 不是有效的 SQLite 数据库")
    tmp_db = DB_PATH.with_suffix(".restore-tmp")
    tmp_db.write_bytes(db_bytes)
    conn = sqlite3.connect(str(tmp_db))
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        need = {"site", "source", "config", "sourceversion", "configsite"}
        if not need.issubset(tables):
            raise HTTPException(400, f"备份 DB 缺少必需表: {sorted(need - tables)}")
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in sorted(need)}
    finally:
        conn.close()
    engine.dispose()  # 释放旧 DB 文件句柄
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(str(DB_PATH) + suffix)
        except FileNotFoundError:
            pass
    os.replace(str(tmp_db), str(DB_PATH))

    # 4) 文件类条目还原 + 清无主残留（目录内不存在于备份包的文件删除）
    restored_files = 0
    for info, rel in cleaned:
        if rel == "tvbox.db":
            continue
        dest = DATA_DIR / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(zf.read(info))
        restored_files += 1
    backup_tops = {r.split("/", 1)[0] for _, r in cleaned if "/" in r}
    for top in backup_tops:
        target_dir = DATA_DIR / top
        in_backup = {r[len(top) + 1:] for _, r in cleaned if r.startswith(top + "/")}
        if target_dir.exists():
            for p in target_dir.rglob("*"):
                if p.is_file() and p.relative_to(target_dir).as_posix() not in in_backup:
                    try:
                        p.unlink()
                    except OSError:
                        pass

    _audit(request, "restore", f"files={restored_files} counts={counts}")
    return {"ok": True, "message": "恢复完成，请刷新页面", "counts": counts, "restored_files": restored_files}



@app.get("/audit-logs")
def audit_logs(limit: int = 200):
    """审计日志尾部（需登录；中间件已保护）。返回最近 limit 条，倒序（最新在前）。"""
    limit = max(1, min(limit, 1000))
    from .config import DATA_DIR
    log_path = DATA_DIR / "audit.log"
    lines = []
    if log_path.exists():
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except OSError:
            lines = []
    items = []
    for raw in lines[-limit:][::-1]:
        raw = raw.rstrip("\n")
        if not raw:
            continue
        # 格式: 2026-10-04 00:47:50 | 127.0.0.1       | event | detail
        parts = [s.strip() for s in raw.split("|", 3)]
        if len(parts) >= 3:
            items.append({
                "time": parts[0],
                "ip": parts[1],
                "event": parts[2],
                "detail": parts[3] if len(parts) == 4 else "",
            })
        else:
            items.append({"time": "", "ip": "", "event": raw, "detail": ""})
    return {"items": items, "total_shown": len(items)}


app.include_router(sources.router)
app.include_router(sites.router)
app.include_router(health.router)
app.include_router(health.summary_router)
app.include_router(configs.router)
app.include_router(importer.router)
app.include_router(lives.router)


# ---- TVBox 静态源托管：配置里 ./py/x.py ./jar/x.jar 等相对路径必须能直接下载 ----
# TVBox 解析相对路径 = 订阅地址目录 + 相对路径；/configs/{id}/ 前缀由下方专属路由兜底。
# mount 必须在 SPA catch-all 之前，否则被 catch-all 吞掉返回 index.html。
# 额外静态源目录（本地已有的 tvbox 源文件），环境变量 TVBOX_SRC_DIR 可覆盖；
# 不设置则仅托管 data/sources 下入库的源。目录不存在时自动跳过。
TVBOX_SRC = Path(os.environ.get("TVBOX_SRC_DIR", str(DATA_DIR.parent / "extra-sources")))

_STATIC_DIRS = {
    "py": [SOURCES_DIR / "py", TVBOX_SRC / "py"],
    "js": [SOURCES_DIR / "js", TVBOX_SRC / "js"],
    "jar": [TVBOX_SRC / "jar", SOURCES_DIR / "jar"],
    "live": [TVBOX_SRC / "live"],
    "theme": [TVBOX_SRC / "theme"],
}

for _prefix, _dirs in _STATIC_DIRS.items():
    _valid = [d for d in _dirs if d.is_dir()]
    if _valid:
        app.mount(f"/{_prefix}", StaticFiles(directory=_valid[0]), name=f"static-{_prefix}")


class _MultiStatic:
    """按顺序在多个目录里查找文件；拒绝路径穿越"""

    def __init__(self, dirs):
        self.dirs = [Path(d) for d in dirs]

    def resolve(self, name: str):
        if not name or "/" in name or ".." in name or name.startswith("."):
            return None
        for d in self.dirs:
            f = d / name
            if f.is_file():
                return f
        return None


_multi = {p: _MultiStatic(ds) for p, ds in _STATIC_DIRS.items()}


@app.get("/configs/{config_id}/{prefix}/{fname}")
def config_relative_asset(config_id: int, prefix: str, fname: str):
    """TVBox 把订阅地址当配置根：./py/x.py → /configs/{id}/py/x.py（公开：TVBox 设备无登录态）"""
    ms = _multi.get(prefix)
    if ms:
        f = ms.resolve(fname)
        if f:
            mt = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
            return FileResponse(f, media_type=mt)
    raise HTTPException(404, "资源不存在")


# ---- SPA 托管（必须在所有 API / 静态 mount 之后）----
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    _DIST_RESOLVED = DIST.resolve()

    @app.get("/{path:path}")
    def spa(path: str):
        """SPA catch-all，带路径穿越防护（审查项 M2）"""
        if not path or ".." in path or path.startswith("/"):
            return FileResponse(DIST / "index.html")
        target = (DIST / path).resolve()
        if target.is_file() and target.is_relative_to(_DIST_RESOLVED):
            return FileResponse(target)
        return FileResponse(DIST / "index.html")
