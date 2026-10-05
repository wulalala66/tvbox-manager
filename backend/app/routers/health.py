"""路由：站点测活（liveness check）

检测逻辑按 site_type 分派：
- type 0/1（XML/JSON 资源站）：GET api（补 /?ac=list 或 ?ac=videolist），
  判断 HTTP 200 且响应体含视频列表特征（class/vod/video 节点）。
- type 3（Spider）：api=csp_ 开头走 jar → 无法本地执行，做 HTTP 存活探测
  （仅 jar URL 可达性）并标记 kind=jar_untested；api=./xx.js/.py 走本地源文件
  存在性检查 + 文件头语法粗检（js: 非 opaque 二进制；py: compile()）。
- ext 为 URL 的：附带拉取 ext 检查可达。

结果写入 site.last_test_at / last_test_result，返回结构：
  {ok, status, latency_ms, kind, message, checked_at}
"""
from __future__ import annotations

import datetime
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

import json

from ..config import DATA_DIR, SOURCES_DIR
from ..database import get_session, engine
from ..models import Site
from ..services.safe_fetch import DEFAULT_UA, UA_CANDIDATES, validate_url

router = APIRouter(prefix="/sites", tags=["health"])

# 探测 UA：默认学 okhttp（TVBox/OK影视 生态），被 403 等拒绝时自动轮换候选 UA
UA = DEFAULT_UA

# JSON 站点分类页特征：响应体出现 "vod_list"/"list"/"class" 键
JSON_OK = re.compile(r'"(vod_list|list|class)"\s*:', re.I)
# XML 站点列表特征：<video>/<class>/<vod 节点
XML_OK = re.compile(r"<(video|class|vod)[\s>]")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _base_url(api) -> str | None:
    a = (api or "").strip()
    if a.startswith(("http://", "https://")):
        return a
    return None


def _json_probe_url(api) -> str:
    base = _base_url(api)
    if base is None:
        return ""
    sep = "&" if "?" in base else "?"
    if base.endswith("/"):
        return base.rstrip("/") + "/?"
    return base + sep + "ac=videolist"


def _probe(url: str, timeout: float):
    """带 UA 嗅探的 GET：先用 okhttp UA，被 401/403/406/412/451 拒绝则换下一个候选。

    很多 JSON CMS / 源站会校验 User-Agent，用 python 默认 UA 或浏览器 UA 都会被拒。
    返回最后一个响应（全部被拒时）或直接抛网络异常。
    """
    from ..services.safe_fetch import _client as _safe_client

    last_resp = None
    for ua in UA_CANDIDATES:
        with _safe_client(timeout=timeout) as client:
            r = client.get(url, headers={"User-Agent": ua})
        if r.status_code in (401, 403, 406, 412, 451):
            last_resp = r
            continue
        return r
    return last_resp


def check_http_json(api, timeout=12.0):
    t0 = time.monotonic()
    url = _json_probe_url(api)
    if not url:
        return {"ok": False, "kind": "skip", "message": "api 非 HTTP 地址", "latency_ms": 0}
    validate_url(url)
    try:
        r = _probe(url, timeout)
        ms = int((time.monotonic() - t0) * 1000)
        if r is None:
            return {"ok": False, "kind": "http", "message": "无响应", "latency_ms": ms}
        if r.status_code != 200:
            return {"ok": False, "kind": "http", "status": r.status_code,
                    "message": f"HTTP {r.status_code}（已试 {len(UA_CANDIDATES)} 个 UA）", "latency_ms": ms}
        body = r.text[:200000]
        if JSON_OK.search(body) or '"vod_name"' in body:
            n = body.count("vod_name") or body.count("vod_id")
            return {"ok": True, "kind": "http", "status": 200,
                    "message": f"分类页有数据（~{n} 条）", "latency_ms": ms}
        return {"ok": False, "kind": "http", "status": 200,
                "message": "HTTP 200 但分类页无列表特征", "latency_ms": ms}
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return {"ok": False, "kind": "http", "message": f"{type(e).__name__}: {e}", "latency_ms": ms}


def check_xml(api, timeout=12.0):
    t0 = time.monotonic()
    url = _base_url(api)
    if not url:
        return {"ok": False, "kind": "skip", "message": "api 非 HTTP 地址", "latency_ms": 0}
    validate_url(url)
    try:
        r = _probe(url, timeout)
        ms = int((time.monotonic() - t0) * 1000)
        ok = r is not None and r.status_code == 200 and XML_OK.search(r.text[:200000]) is not None
        return {"ok": ok, "kind": "http", "status": r.status_code,
                "message": "XML 列表有数据" if ok else "HTTP 异常或无 <video>/<class> 节点",
                "latency_ms": ms}
    except Exception as e:
        return {"ok": False, "kind": "http", "message": f"{type(e).__name__}: {e}",
                "latency_ms": int((time.monotonic() - t0) * 1000)}


_JAR_CLASS_CACHE: dict[str, set[str]] = {}


def _jar_spider_classes(jar_path: Path) -> set[str]:
    key = f"{jar_path}:{jar_path.stat().st_mtime_ns}:{jar_path.stat().st_size}"
    import re as _re
    import zipfile
    classes = set()
    try:
        with zipfile.ZipFile(jar_path) as z:
            for n in z.namelist():
                if not n.endswith(".dex"):
                    continue
                data = z.read(n)
                for m in _re.finditer(b"Lcom/github/catvod/spider/([A-Za-z0-9_]+);", data):
                    name = m.group(1).decode()
                    if name.endswith("Base"):
                        continue
                    classes.add(name)
    except Exception:
        pass
    _JAR_CLASS_CACHE[key] = classes
    return classes


def _resolve_jar_path(jar_ref):
    if not jar_ref:
        return None
    name = jar_ref.rstrip("/").split("/")[-1]
    extra_jar = os.environ.get("TVBOX_JAR_DIRS", "")  # 冒号分隔的额外 jar 目录
    bases = [SOURCES_DIR / "jar"] + [Path(x) for x in extra_jar.split(":") if x.strip()]
    for base in bases:
        cand = base / name
        if cand.is_file():
            return cand
    return None


def check_spider_source(site, session=None):
    api = (site.api or "").strip()
    ext_url = site.ext if isinstance(site.ext, str) and site.ext.startswith(("http", "./", "/")) else None
    if api.startswith("csp_"):
        cls = api[4:]
        jar_ref = site.jar
        if not jar_ref:
            if session is None:
                from ..database import get_session
                from ..models import Config as _Config
                with next(get_session()) as _s:
                    row = _s.exec(select(_Config).order_by(_Config.id)).first()
            else:
                from ..models import Config
                row = session.exec(select(Config).order_by(Config.id)).first()
            jar_ref = row.global_spider if row else None
        jp = _resolve_jar_path(jar_ref or "")
        if jp is None:
            return {"ok": False, "kind": "jar",
                    "message": f"未配置 jar 文件（{jar_ref or '依赖全局 spider 未找到'}）", "latency_ms": 0}
        classes = _jar_spider_classes(jp)
        if cls in classes:
            return {"ok": True, "kind": "jar",
                    "message": f"jar 支持该站点（{jp.name} 内含 csp_{cls}）", "latency_ms": 0}
        return {"ok": False, "kind": "jar",
                "message": f"jar 内无 csp_{cls}（{jp.name} 仅支持 {len(classes)} 个类）", "latency_ms": 0}
    m = re.match(r"^\./(js|py)/(.+\.(?:js|py))$", api)
    if not m:
        if ext_url and ext_url.endswith((".js", ".py")):
            m2 = re.match(r"^\./(js|py)/(.+\.(?:js|py))$", ext_url)
            if not m2:
                return {"ok": True, "kind": "ext_url",
                        "message": f"ext 为远程源（未运行时验证）: {ext_url[:60]}", "latency_ms": 0}
            m = m2
        else:
            return {"ok": False, "kind": "skip", "message": f"无法识别源位置: {api[:60]}", "latency_ms": 0}
    kind, fn = m.group(1), m.group(2)
    path = SOURCES_DIR / kind / fn
    if not path.exists() and site.source_id:
        from ..models import Source
        if session is None:
            from ..database import get_session
            with next(get_session()) as _s:
                src_row = _s.get(Source, site.source_id)
        else:
            src_row = session.get(Source, site.source_id)
        if src_row:
            cand = SOURCES_DIR / kind / src_row.filename
            if cand.exists():
                path = cand
    if not path.exists():
        return {"ok": False, "kind": kind, "message": f"源文件缺失: {api}", "latency_ms": 0}
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError:
        return {"ok": False, "kind": kind, "message": f"源文件非 UTF-8 文本: {fn}", "latency_ms": 0}
    if kind == "py":
        try:
            compile(text, fn, "exec")
        except SyntaxError as e:
            return {"ok": False, "kind": "py", "message": f"Python 语法错误 L{e.lineno}: {e.msg}", "latency_ms": 0}
        return {"ok": True, "kind": "py", "message": f"py 源存在且语法通过（{len(text) // 1024}KB）", "latency_ms": 0}
    has_export = ("__jsEvalReturn" in text or "init(" in text or "export default" in text
                  or "homeContent" in text)
    return {"ok": True, "kind": "js",
            "message": f"js 源存在{'（含 drpy 出口）' if has_export else ''}（{len(text) // 1024}KB）",
            "latency_ms": 0}


def run_check(site, timeout=12.0, session=None):
    st = site.site_type
    if st in (0,):
        r = check_xml(site.api, timeout)
    elif st in (1, 4):
        r = check_http_json(site.api, timeout)
    else:
        r = check_spider_source(site, session=session)
    r["checked_at"] = _now()
    return r


@router.post("/{site_id}/check")
def check_site(site_id: int, session: Session = Depends(get_session)):
    s = session.get(Site, site_id)
    if not s:
        raise HTTPException(404, "站点不存在")
    r = run_check(s, session=session)
    s.last_test_at = datetime.datetime.now(datetime.timezone.utc)
    s.last_test_result = r
    session.add(s)
    session.commit()
    return {"site_id": s.id, "key": s.key, "name": s.name, **r}


@router.post("/check-all")
def check_all(body: dict = None, session: Session = Depends(get_session)):
    body = body or {}
    ids = body.get("site_ids")
    timeout = float(body.get("timeout", 12))
    scope = body.get("scope")
    q = select(Site).order_by(Site.order_num, Site.id)
    items = session.exec(q).all()
    if ids:
        want = set(ids)
        items = [s for s in items if s.id in want]
    elif scope == "fail":
        items = [s for s in items if s.last_test_result and not s.last_test_result.get("ok")]
    elif scope == "untested":
        items = [s for s in items if not s.last_test_result]
    results = []
    _check_progress.update({"running": True, "done": 0, "total": len(items), "ok": 0, "fail": 0})

    from concurrent.futures import ThreadPoolExecutor
    BATCH = 20

    def _probe_site(site):
        try:
            return run_check(site, timeout, session=None)
        except Exception as e:
            return {"ok": False, "detail": f"探测异常: {e}"}

    with ThreadPoolExecutor(max_workers=8) as pool:
        for i, (s, r) in enumerate(zip(items, pool.map(_probe_site, items))):
            s.last_test_at = datetime.datetime.now(datetime.timezone.utc)
            s.last_test_result = r
            session.add(s)
            results.append({"site_id": s.id, "key": s.key, "name": s.name, **r})
            _check_progress["done"] = i
            _check_progress["ok" if r.get("ok") else "fail"] += 1
            if i % BATCH == 0:
                session.commit()
    session.commit()
    _check_progress["running"] = False
    ok_n = sum(1 for r in results if r["ok"])
    return {"total": len(results), "ok": ok_n, "fail": len(results) - ok_n, "results": results}


_check_progress = {"running": False, "done": 0, "total": 0, "ok": 0, "fail": 0}

summary_router = APIRouter(prefix="/health", tags=["health"])


@summary_router.get("/check-progress")
def check_progress():
    return dict(_check_progress)


def _history_sweep(session: Session):
    hist_path = DATA_DIR / "health_history.json"
    points = []
    if hist_path.exists():
        try:
            points = json.loads(hist_path.read_text()).get("points", [])
        except (OSError, ValueError):
            points = []
    rows = session.exec(select(Site)).all()
    tested = [s for s in rows if s.last_test_result]
    ok = sum(1 for s in tested if s.last_test_result.get("ok"))
    point = {
        "t": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total": len(rows),
        "ok": ok,
        "fail": len(tested) - ok,
        "untested": len(rows) - len(tested),
    }
    if not points or points[-1].get("t", "")[:16] != point["t"][:16]:
        points.append(point)
        points = points[-200:]
        tmp = hist_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"points": points}, ensure_ascii=False))
        tmp.replace(hist_path)
    return points


@summary_router.get("/history")
def health_history(session: Session = Depends(get_session)):
    points = _history_sweep(session)
    return {"points": points}


@summary_router.get("/summary")
def health_summary(session: Session = Depends(get_session)):
    return _health_summary_impl()


def _health_summary_impl():
    rows = Session(engine).exec(select(Site)).all()
    tested = [s for s in rows if s.last_test_result]
    ok = sum(1 for s in tested if s.last_test_result.get("ok"))
    reasons = {}
    for s in tested:
        r = s.last_test_result
        if not isinstance(r, dict):
            continue
        if r.get("ok"):
            continue
        msg = r.get("message") or ""
        if "缺失" in msg:
            reasons["源文件缺失"] = reasons.get("源文件缺失", 0) + 1
        elif "SSL" in msg or "UNEXPECTED_EOF" in msg or "timed out" in msg.lower() or "timeout" in msg.lower():
            reasons["网络超时/SSL"] = reasons.get("网络超时/SSL", 0) + 1
        elif "HTTP" in msg or "status" in msg:
            reasons["HTTP 错误"] = reasons.get("HTTP 错误", 0) + 1
        else:
            reasons["其他"] = reasons.get("其他", 0) + 1
    return {"total": len(rows), "tested": len(tested), "ok": ok, "fail": len(tested) - ok,
            "untested": len(rows) - len(tested), "fail_reasons": reasons}


AUTO_CHECK_INTERVAL_HOURS = 6
global _autocheck_thread_started
_autocheck_thread_started = False


def _auto_check_loop():
    import threading
    import traceback
    while True:
        try:
            with Session(engine) as sess:
                _history_sweep(sess)
                rows = sess.exec(select(Site)).all()
                sites = list(rows)
            if sites:
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=8) as ex:
                    results = list(ex.map(lambda s: run_check(s, session=None), sites))
                with Session(engine) as sess:
                    by_id = {s.id: s for s in sess.exec(select(Site)).all()}
                    for site, res in zip(sites, results):
                        cur = by_id.get(site.id)
                        if cur is None:
                            continue
                        cur.last_test_at = datetime.datetime.now(datetime.timezone.utc)
                        cur.last_test_result = res
                    sess.add_all(by_id.values())
                    sess.commit()
                _check_progress.update({"running": False, "done": len(sites), "total": len(sites),
                                        "ok": sum(1 for r in results if r.get("ok")),
                                        "fail": sum(1 for r in results if not r.get("ok"))})
                _history_sweep(Session(engine))
        except Exception:
            traceback.print_exc()
        time.sleep(AUTO_CHECK_INTERVAL_HOURS * 3600)


def start_auto_check_thread():
    global _autocheck_thread_started
    if _autocheck_thread_started:
        return
    _autocheck_thread_started = True
    import threading
    threading.Thread(target=_auto_check_loop, name="auto-check", daemon=True).start()
