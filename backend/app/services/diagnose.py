"""配置诊断服务：发布前全面体检，输出问题清单"""
import json
import re

from ..config import SOURCES_DIR
from .safe_fetch import DEFAULT_UA, safe_get, validate_url


def _check_url(label: str, url: str, results: list, timeout: float = 8.0):
    """可达性检查（SSRF 安全），结果 append 到 results"""
    try:
        validate_url(url)
    except ValueError as e:
        results.append({"level": "error", "item": label, "msg": f"URL 不允许：{e}"})
        return
    try:
        safe_get(url, timeout=timeout)  # 默认 okhttp UA + 自动嗅探回退
    except Exception as e:
        results.append({"level": "error", "item": label, "msg": f"不可达：{type(e).__name__}: {e}"[:200]})
        return
    results.append({"level": "ok", "item": label, "msg": "可达"})


def diagnose(session, c, live_preview_fn=None) -> dict:
    from sqlmodel import select
    from ..models import ConfigSite, Site

    issues = []
    warnings = []

    # 1. spider jar 引用检查（本地文件存在性 / 远程 URL 可达性）
    spider = (c.global_spider or "").strip()
    if spider:
        if spider.startswith("http"):
            _check_url("全局 spider", spider, warnings)
        else:
            m = re.search(r"([\w\-./]+\.jar)", spider)
            fn = m.group(1).split("/")[-1] if m else None
            if fn and not (SOURCES_DIR / "jar" / fn).exists():
                issues.append({"level": "warn", "item": "全局 spider", "msg": f"引用本地 jar {fn} 在源库中不存在"})
            elif not fn:
                warnings.append({"level": "ok", "item": "全局 spider", "msg": spider[:80]})
            else:
                warnings.append({"level": "ok", "item": "全局 spider", "msg": f"本地 jar {fn} 存在"})

    # 2. 关联站点逐一检查
    rows = session.exec(select(ConfigSite).where(ConfigSite.config_id == c.id)).all()
    sites = []
    for r in rows:
        s = session.get(Site, r.site_id)
        if s:
            sites.append(s)
    for s in sites:
        if not s.enabled:
            warnings.append({"level": "info", "item": f"站点 {s.name}", "msg": "已禁用，不进配置"})
            continue
        api = (s.api or "").strip()
        if s.site_type == 3:
            if api.startswith("./py/") or api.startswith("./js/"):
                # 相对路径源文件形态：源库中必须存在
                kind = "py" if api.startswith("./py/") else "js"
                fn = api.split("/")[-1]
                from ..models import Source
                src = session.exec(select(Source).where(Source.kind == kind, Source.filename == fn)).first()
                if not src:
                    issues.append({"level": "error", "item": f"站点 {s.name}", "msg": f"{api} 在源库中不存在"})
                elif s.source_id and s.source_id != src.id:
                    warnings.append({"level": "info", "item": f"站点 {s.name}", "msg": f"api 指向 {fn} 但关联源是 id={s.source_id}"})
                else:
                    warnings.append({"level": "ok", "item": f"站点 {s.name}", "msg": f"源文件 {kind}/{fn} 存在"})
            elif api.startswith("csp_"):
                if not s.source_id:
                    warnings.append({"level": "info", "item": f"站点 {s.name}", "msg": "csp_ 类名形态且未关联源（类名需在 jar 中）"})
                else:
                    from ..models import Source
                    src = session.get(Source, s.source_id)
                    if not src:
                        issues.append({"level": "error", "item": f"站点 {s.name}", "msg": f"关联源 id={s.source_id} 已不存在"})
                    elif not (SOURCES_DIR / src.kind / src.filename).exists():
                        issues.append({"level": "error", "item": f"站点 {s.name}", "msg": f"关联源文件缺失：{src.kind}/{src.filename}"})
                    else:
                        warnings.append({"level": "ok", "item": f"站点 {s.name}", "msg": f"关联源 {src.kind}/{src.filename} 存在"})
            elif api.startswith("http"):
                _check_url(f"站点 {s.name}", api, warnings)
            else:
                issues.append({"level": "error", "item": f"站点 {s.name}", "msg": f"type=3 但 api={api!r} 既非 csp_/./py//./js/ 也非 http"})
        elif s.site_type in (0, 1) and not api.startswith("http"):
            issues.append({"level": "error", "item": f"站点 {s.name}", "msg": f"type={s.site_type} 但 api={s.api!r} 非 http 地址"})
        elif s.site_type in (0, 1):
            _check_url(f"站点 {s.name}", s.api, warnings)

    # 源库关联存在性（csp_ 站点：source_id 指向的源文件必须存在）——已并入上面 type=3 分支

    # 3. lives / parses 检查
    gf = {}
    try:
        gf = json.loads(c.global_fields or "{}")
    except Exception:
        issues.append({"level": "error", "item": "全局字段", "msg": "global_fields 不是合法 JSON"})

    for l in gf.get("lives", []):
        if not l.get("name") or not l.get("url"):
            issues.append({"level": "error", "item": "直播源", "msg": f"name/url 缺失：{json.dumps(l, ensure_ascii=False)[:80]}"})
        elif not l["url"].startswith("http"):
            issues.append({"level": "error", "item": f"直播源 {l['name']}", "msg": f"url 非 http：{l['url'][:60]}"})

    for p in gf.get("parses", []):
        if not p.get("name") or not p.get("url"):
            issues.append({"level": "error", "item": "解析", "msg": f"name/url 缺失：{json.dumps(p, ensure_ascii=False)[:80]}"})
        elif p.get("type", 1) in (0, 1) and not p["url"].startswith("http"):
            issues.append({"level": "error", "item": f"解析 {p['name']}", "msg": f"type={p.get('type')} 的 url 应为 http 接口：{p['url'][:60]}"})

    # 4. 密文可解性（若已启用加密且有 enc_key）
    if c.encrypt and not c.enc_key:
        issues.append({"level": "warn", "item": "加密", "msg": "已启用加密但未设置密钥，发布时会自动生成——记下发布返回的 key"})
    if not sites:
        issues.append({"level": "warn", "item": "站点", "msg": "方案内没有任何站点，发布产物为空配置"})

    return {"ok": True, "issues": issues, "warnings": warnings,
            "counts": {"errors": len(issues), "warnings": len([w for w in warnings if w["level"] == 'warn']),
                       "sites": len(sites)}}
