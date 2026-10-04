"""路由：导入向导——两段式（analyze 预览 → commit 确认落库）

支持三种配置编码：明文 JSON / ** 前缀 Base64 / 2423 开头 FongMi AES-CBC。
analyze 返回顶层完整字段 top_fields（spider/lives/parses/rules/... 全保留），
commit 时随 config_id 写入 Config.global_fields（spider 单独入 global_spider）。
站点条目除核心列（key/name/type/api/ext/jar）外全部字段进 Site.extra，不丢任何字段。
URL 导入时自动拉取 ./py/xx.py、./js/xx.js 相对路径的远端源文件入源库。
"""
import base64
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..database import get_session
from ..models import Config, Site, Source
from ..schemas import ImportAnalyzeIn, ImportCandidate
from ..services.crypto import fongmi_decode

router = APIRouter(prefix="/import", tags=["import"])

UA = {"User-Agent": "Mozilla/5.0 (Android 13) Mobile"}


def _fetch_text(url: str) -> str:
    # SSRF 防护 M11：主配置拉取与源文件拉取统一走 safe_get（内网/环回/云元数据拦截 + 限长）
    from ..services.safe_fetch import safe_get
    try:
        data = safe_get(url, headers=UA)
        # 编码探测：UTF-8 优先；失败回退 GBK（老源站常见），再失败按 latin-1 兜底（不丢字节）
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            pass
        try:
            return data.decode("gb18030")
        except UnicodeDecodeError:
            return data.decode("latin-1", errors="replace")
    except Exception as e:
        raise HTTPException(400, f"拉取配置失败: {e}")


def _fetch_bytes(url: str) -> bytes | None:
    """拉取远端源文件（py/js/jar），失败返回 None 不中断导入（SSRF 防护 M11）"""
    from ..services.safe_fetch import safe_get
    try:
        return safe_get(url, headers=UA)
    except Exception:
        return None


def _resolve_asset_url(api: str, config_url: str | None) -> str | None:
    """把 ./py/xx.py 相对路径解析成远端绝对 URL"""
    if not config_url:
        return None
    if api.startswith(("http://", "https://")):
        return api
    if api.startswith(("./", "../", "/")):
        from urllib.parse import urljoin
        return urljoin(config_url, api)
    return None


def _get_config_text(body: ImportAnalyzeIn) -> str:
    if body.type == "url":
        if not body.url:
            raise HTTPException(400, "type=url 需要 url 字段")
        try:
            return _fetch_text(body.url)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(400, f"拉取配置失败: {e}")
    return body.content or ""


def _decode_config(text: str) -> str:
    """明文 / ** Base64 / 2423 AES → 明文 JSON 文本"""
    t = text.strip()
    if t.startswith("2423"):
        try:
            return fongmi_decode(t)
        except Exception as e:
            raise HTTPException(400, f"2423 加密配置解密失败: {e}")
    if t.startswith("**"):
        try:
            return base64.b64decode(t[2:]).decode("utf-8")
        except Exception as e:
            raise HTTPException(400, f"** Base64 解码失败: {e}")
    if t and not t.startswith("{"):
        try:
            decoded = base64.b64decode(t + "=" * (-len(t) % 4)).decode("utf-8")
            if decoded.strip().startswith("{"):
                return decoded
        except Exception:
            pass
    return t


def _kind_of_api(api: str):
    if not api:
        return None
    a = api.strip()
    if a.endswith(".py"):
        return "py"
    if a.endswith(".js"):
        return "js"
    if a.startswith("csp_"):
        return "jar"
    return None


# 核心列：Site 表有独立字段的；其余全部进 extra（不丢字段）
CORE_SITE_KEYS = {"key", "name", "type", "api", "ext", "jar"}


def _analyze_sites(doc: dict) -> list:
    out = []
    for raw in doc.get("sites", []):
        if not isinstance(raw, dict):
            continue
        api = raw.get("api", "") or ""
        kind = _kind_of_api(api)
        warnings = []
        stype = raw.get("type", 0)
        extra = {k: v for k, v in raw.items() if k not in CORE_SITE_KEYS}
        if stype == 3 and kind is None:
            warnings.append("type=3 但 api 既非 csp_ 也非 .py/.js 结尾")
        if stype in (0, 1) and not api.startswith(("http", "./", "../", "/")):
            warnings.append("HTTP 站点 api 建议为完整 URL")
        ext = raw.get("ext")
        out.append(ImportCandidate(
            key=str(raw.get("key", "")),
            name=str(raw.get("name", "")),
            site_type=int(stype),
            api=api,
            ext=ext,
            jar=raw.get("jar"),
            kind=kind,
            filename=None,
            content_b64=None,
            source_url=None,
            extra=extra,
            meta={"ext_is_url": isinstance(ext, str) and ext.startswith(("http", "./", "../")),
                  "extra_keys": list(extra.keys())},
            warnings=warnings,
        ))
    return out


@router.post("/analyze")
def analyze(body: ImportAnalyzeIn, session: Session = Depends(get_session)):
    """第一段：解析配置文本/URL，返回顶层字段 + 候选站点列表（不落库）"""
    text = _get_config_text(body)
    doc_text = _decode_config(text)
    try:
        doc = json.loads(doc_text)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"配置不是合法 JSON: {e}")
    if not isinstance(doc, dict):
        raise HTTPException(400, "配置顶层必须是 JSON 对象")
    existing = {s.filename: s.id for s in session.exec(select(Source)).all()}
    result = []
    for c in _analyze_sites(doc):
        d = c.model_dump()
        d["existing_source_id"] = None
        if c.api.endswith((".js", ".py")):
            fn = c.api.rsplit("/", 1)[-1]
            d["suggested_filename"] = fn
            d["existing_source_id"] = existing.get(fn)
        elif isinstance(c.ext, str) and c.ext.endswith((".js", ".py")):
            fn = c.ext.rsplit("/", 1)[-1]
            d["suggested_filename"] = fn
            d["existing_source_id"] = existing.get(fn)
        result.append(d)
    # 顶层字段全保留（除 sites），spider 单列
    top_fields = {k: v for k, v in doc.items() if k != "sites"}
    spider = top_fields.pop("spider", None)
    return {"top_fields": top_fields, "spider": spider,
            "top_keys": list(top_fields.keys()),
            "candidates": result}


def _safe_int(v, default=3):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


@router.post("/commit")
def commit(body: dict, session: Session = Depends(get_session)):
    """第二段：body.candidates = 选中的 candidate 数组；body.config_id 可选——
    存在时把 body.top_fields / body.spider 写入该方案的 global_fields / global_spider。
    body.config_url 为 URL 导入时的原始配置地址（用于解析 ./py/xx.py 相对路径）。"""
    created_sites, skipped = [], []
    fetched_assets, failed_assets = [], []

    # 顶层字段入方案
    config_id = body.get("config_id")
    if config_id:
        cfg = session.get(Config, config_id)
        if not cfg:
            raise HTTPException(404, f"配置方案不存在: {config_id}")
        top = body.get("top_fields") or {}
        spider = body.get("spider")
        merged = dict(cfg.global_fields or {})
        merged.update(top)  # 导入的顶层覆盖方案现有值（用户确认过的意图）
        cfg.global_fields = merged
        if spider:
            cfg.global_spider = spider
        session.add(cfg)

    existing_src = {s.filename: s.id for s in session.exec(select(Source)).all()}
    for c in body.get("candidates", []):
        key = c.get("key")
        if not key:
            skipped.append({"key": None, "reason": "缺 key"})
            continue
        if session.exec(select(Site).where(Site.key == key)).first():
            skipped.append({"key": key, "reason": "key 已存在"})
            continue
        source_id = None
        content_b64 = c.get("content_b64")
        filename = c.get("filename") or c.get("suggested_filename")
        kind = c.get("kind")

        # 远端源文件自动拉取：URL 导入时把 ./py/xx.py 之类相对路径拉回源库
        asset_url = _resolve_asset_url(c.get("api", ""), body.get("config_url"))
        if not content_b64 and kind in ("js", "py") and asset_url:
            data = _fetch_bytes(asset_url)
            if data:
                from ..services import source_store
                src, created = source_store.create_source(
                    session, filename_hint=filename or asset_url.rsplit("/", 1)[-1],
                    kind=kind, data=data,
                    note=f"import-remote: {asset_url}", name=c.get("name"))
                source_id = src.id
                fetched_assets.append({"key": key, "url": asset_url, "created": created})
            else:
                failed_assets.append({"key": key, "url": asset_url})

        if content_b64 and filename and kind in ("js", "py"):
            data = base64.b64decode(content_b64)
            from ..services import source_store
            src, _created = source_store.create_source(
                session, filename_hint=filename, kind=kind, data=data,
                note=f"import: {c.get('source_url') or 'paste'}", name=c.get("name"))
            source_id = src.id
        elif c.get("existing_source_id"):
            source_id = c["existing_source_id"]
        elif filename and filename in existing_src:
            source_id = existing_src[filename]
        site = Site(
            key=key, name=c.get("name") or key,
            site_type=_safe_int(c.get("site_type"), 3),
            api=c.get("api", ""), ext=c.get("ext"),
            jar=c.get("jar"), extra=c.get("extra") or {},
            source_id=source_id, enabled=True,
            order_num=len(created_sites), tags=["imported"],
        )
        session.add(site)
        session.flush()  # 拿 id，不提交（单事务，M6）
        created_sites.append({"id": site.id, "key": site.key, "name": site.name})
    session.commit()  # 整批一次提交
    # 新站点同步加入所选方案（体验：用户在向导里选了"同时更新配置方案"即预期新站直接进方案）
    if config_id and created_sites:
        from ..models import ConfigSite
        next_order = len(session.exec(
            select(ConfigSite).where(ConfigSite.config_id == config_id)).all())
        for i, s in enumerate(created_sites):
            session.add(ConfigSite(config_id=config_id, site_id=s["id"],
                                   order_num=next_order + i))
        session.commit()
    return {"created": created_sites, "skipped": skipped,
            "fetched_assets": fetched_assets, "failed_assets": failed_assets,
            "config_updated": bool(config_id)}
