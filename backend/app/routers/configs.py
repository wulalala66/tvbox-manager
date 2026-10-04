"""路由：配置方案管理 + 发布导出 vod.json"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from ..config import CONFIGS_DIR
from ..database import get_session
from ..models import Config, ConfigSite, Site
from ..schemas import ConfigCreate, ConfigOut, ConfigUpdate

router = APIRouter(prefix="/configs", tags=["configs"])


def to_out(session: Session, c: Config) -> dict:
    links = session.exec(select(ConfigSite).where(
        ConfigSite.config_id == c.id).order_by(ConfigSite.order_num)).all()
    sites = []
    for cs in links:
        s = session.get(Site, cs.site_id)
        if s:
            sites.append({
                "id": s.id, "key": s.key, "name": s.name, "site_type": s.site_type,
                "enabled": s.enabled, "order_num": cs.order_num, "overrides": cs.overrides,
                # 测活摘要：ok / fail / untested（供方案页直接显示健康徽标）
                "health": ("ok" if s.last_test_result.get("ok")
                           else "fail" if s.last_test_result else "untested"),
                "health_msg": (s.last_test_result or {}).get("message", "")[:80],
            })
    return {
        "id": c.id, "name": c.name, "slug": c.slug,
        "global_spider": c.global_spider, "global_fields": c.global_fields,
        "encrypt": bool(c.encrypt), "encrypted": bool(c.encrypt), "enc_key_set": bool(c.enc_key),
        "share_token": c.share_token,
        "published_at": c.published_at.isoformat() if c.published_at else None,
        "sites": sites,
    }


def _get(session: Session, config_id: int) -> Config:
    c = session.get(Config, config_id)
    if not c:
        raise HTTPException(404, "配置方案不存在")
    return c


@router.get("")
def list_configs(page: int = None, page_size: int = 50, session: Session = Depends(get_session)):
    items = session.exec(select(Config).order_by(Config.id)).all()
    # M10：批量取 links + sites，避免每配置 1+N+N*M 次查询
    links = session.exec(select(ConfigSite).order_by(ConfigSite.order_num)).all()
    site_ids = {l.site_id for l in links}
    site_map = {}
    if site_ids:
        site_map = {s.id: s for s in session.exec(
            select(Site).where(Site.id.in_(site_ids))).all()}
    by_cfg: dict[int, list] = {}
    for l in links:
        by_cfg.setdefault(l.config_id, []).append(l)
    out = []
    for c in items:
        sites = []
        for l in by_cfg.get(c.id, []):
            s = site_map.get(l.site_id)
            if s:
                sites.append({"id": s.id, "key": s.key, "name": s.name,
                              "site_type": s.site_type, "enabled": s.enabled,
                              "order_num": l.order_num, "overrides": l.overrides})
        out.append({"id": c.id, "name": c.name, "slug": c.slug,
                    "global_spider": c.global_spider, "global_fields": c.global_fields,
                    "encrypt": bool(c.encrypt), "enc_key_set": bool(c.enc_key),
                    "share_token": c.share_token,
                    "published_at": c.published_at.isoformat() if c.published_at else None,
                    "sites": sites, "site_count": len(sites)})
    if page is None or page < 1:
        return out
    return {"items": out, "total": len(out), "page": page, "page_size": page_size}


@router.post("")
def create_config(body: ConfigCreate, session: Session = Depends(get_session)):
    if not _slug_ok(body.slug):
        raise HTTPException(400, f"slug 只允许字母数字下划线连字符: {body.slug}")
    if session.exec(select(Config).where(Config.slug == body.slug)).first():
        raise HTTPException(409, f"slug 已存在: {body.slug}")
    c = Config(**body.model_dump())
    session.add(c)
    session.commit()
    session.refresh(c)
    return to_out(session, c)


@router.get("/{config_id}")
def get_config(config_id: int, session: Session = Depends(get_session)):
    return to_out(session, _get(session, config_id))


@router.put("/{config_id}")
def update_config(config_id: int, body: ConfigUpdate, session: Session = Depends(get_session)):
    c = _get(session, config_id)
    data = body.model_dump(exclude_unset=True)
    if "slug" in data and data["slug"] != c.slug:
        if not _slug_ok(data["slug"]):
            raise HTTPException(400, f"slug 只允许字母数字下划线连字符: {data['slug']}")
        if session.exec(select(Config).where(Config.slug == data["slug"])).first():
            raise HTTPException(409, f"slug 已存在: {data['slug']}")
    for k, v in data.items():
        setattr(c, k, v)
    session.add(c)
    c.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(c)
    return to_out(session, c)


@router.delete("/{config_id}")
def delete_config(config_id: int, session: Session = Depends(get_session)):
    c = _get(session, config_id)
    # Core 层删除子行：SQLModel/SQLAlchemy unit-of-work 在无 relationship 的复合主键
    # 关联表场景下可能吞掉 DELETE FROM configsite，导致 FK 约束失败 500。
    session.exec(sa_delete(ConfigSite).where(ConfigSite.config_id == config_id))
    session.delete(c)
    session.commit()
    return {"ok": True}


@router.put("/{config_id}/sites")
def set_config_sites(config_id: int, body: dict, session: Session = Depends(get_session)):
    """body: {sites: [{site_id, order_num, overrides?}]} 全量替换方案站点列表"""
    c = _get(session, config_id)
    sites_in = body.get("sites", [])
    # 先整体校验再动手（Minor #2：避免删完才 400/500）
    seen = set()
    for item in sites_in:
        sid = item.get("site_id")
        if not sid or not session.get(Site, sid):
            raise HTTPException(400, f"站点不存在: {sid}")
        if sid in seen:
            raise HTTPException(400, f"重复站点: {sid}")
        seen.add(sid)
    for cs in session.exec(select(ConfigSite).where(ConfigSite.config_id == config_id)).all():
        session.delete(cs)
    for i, item in enumerate(sites_in):
        # overrides 归一化：仅接受 dict，其余（含 JSON null 误存字符串）一律置 NULL
        ov = item.get("overrides")
        if not isinstance(ov, dict):
            ov = None
        session.add(ConfigSite(
            config_id=config_id, site_id=item["site_id"],
            order_num=item.get("order_num", i),
            overrides=ov))
    session.commit()
    return to_out(session, c)


@router.post("/{config_id}/sites/batch-add")
def batch_add_sites(config_id: int, body: dict, session: Session = Depends(get_session)):
    """body: {site_ids: [...]} 批量把站点加入方案（已存在的跳过）"""
    c = _get(session, config_id)
    ids = body.get("site_ids") or []
    existing = {cs.site_id for cs in session.exec(
        select(ConfigSite).where(ConfigSite.config_id == config_id)).all()}
    max_order = max([cs.order_num for cs in session.exec(
        select(ConfigSite).where(ConfigSite.config_id == config_id)).all()] or [-1])
    added, skipped = [], []
    for sid in ids:
        if sid in existing:
            skipped.append(sid)
            continue
        if not session.get(Site, sid):
            skipped.append(sid)
            continue
        max_order += 1
        session.add(ConfigSite(config_id=config_id, site_id=sid, order_num=max_order))
        existing.add(sid)
        added.append(sid)
    session.commit()
    return {"ok": True, "added": added, "skipped": skipped, "config": to_out(session, c)}


@router.post("/{config_id}/sites/batch-remove")
def batch_remove_sites(config_id: int, body: dict, session: Session = Depends(get_session)):
    """body: {site_ids: [...]} 批量从方案移除"""
    ids = set(body.get("site_ids") or [])
    removed = []
    for cs in session.exec(select(ConfigSite).where(ConfigSite.config_id == config_id)).all():
        if cs.site_id in ids:
            session.delete(cs)
            removed.append(cs.site_id)
    session.commit()
    return {"ok": True, "removed": removed, "config": to_out(session, _get(session, config_id))}


@router.post("/{config_id}/sites/{site_id}")
def add_config_site(config_id: int, site_id: int, session: Session = Depends(get_session)):
    _get(session, config_id)
    if not session.get(Site, site_id):
        raise HTTPException(404, "站点不存在")
    exists = session.exec(select(ConfigSite).where(
        ConfigSite.config_id == config_id, ConfigSite.site_id == site_id)).first()
    if exists:
        raise HTTPException(409, "站点已在方案中")
    max_order = max([cs.order_num for cs in session.exec(
        select(ConfigSite).where(ConfigSite.config_id == config_id)).all()] or [-1])
    session.add(ConfigSite(config_id=config_id, site_id=site_id, order_num=max_order + 1))
    session.commit()
    return to_out(session, _get(session, config_id))


@router.post("/{config_id}/duplicate")
def duplicate_config(config_id: int, body: dict = None, session: Session = Depends(get_session)):
    """复制方案（站点列表+全局字段一起复制），body: {name?, slug?} 可选"""
    src = _get(session, config_id)
    body = body or {}
    name = body.get("name") or f"{src.name} 副本"
    slug = body.get("slug") or f"{src.slug}-copy{int(datetime.now().timestamp()) % 10000}"
    if session.exec(select(Config).where(Config.slug == slug)).first():
        raise HTTPException(409, f"slug 已存在: {slug}")
    nc = Config(
        name=name, slug=slug,
        global_spider=src.global_spider, global_fields=src.global_fields,
        encrypt=False, enc_key=None,
    )
    session.add(nc)
    session.flush()  # 拿 nc.id，不提交
    for cs in session.exec(select(ConfigSite).where(ConfigSite.config_id == config_id)
                           .order_by(ConfigSite.order_num)).all():
        session.add(ConfigSite(config_id=nc.id, site_id=cs.site_id,
                               order_num=cs.order_num, overrides=cs.overrides))
    # 原子提交（Minor #3：避免第二次 commit 失败留下半份副本）
    session.commit()
    session.refresh(nc)
    return to_out(session, nc)


@router.delete("/{config_id}/sites/{site_id}")
def remove_config_site(config_id: int, site_id: int, session: Session = Depends(get_session)):
    cs = session.exec(select(ConfigSite).where(
        ConfigSite.config_id == config_id, ConfigSite.site_id == site_id)).first()
    if not cs:
        raise HTTPException(404, "方案中无此站点")
    session.delete(cs)
    session.commit()
    return to_out(session, _get(session, config_id))


def _slug_ok(slug: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]+", slug))


def build_vod_json(session: Session, c: Config) -> dict:
    """把方案编译为 TVBox/FongMi 兼容 vod.json 结构"""
    out = {}
    gf = c.global_fields or {}
    out.update(gf)  # 顶层自定义字段（spider/lives/headers 等）
    if c.global_spider:
        out["spider"] = c.global_spider
    sites_out = []
    links = session.exec(select(ConfigSite).where(
        ConfigSite.config_id == c.id).order_by(ConfigSite.order_num)).all()
    for cs in links:
        s = session.get(Site, cs.site_id)
        if not s or not s.enabled:
            continue
        ov = cs.overrides or {}
        item = {
            "key": ov.get("key", s.key),
            "name": ov.get("name", s.name),
            "type": ov.get("type", s.site_type),
            "api": ov.get("api", s.api),
        }
        ext = ov.get("ext", s.ext)
        if ext is not None:
            item["ext"] = ext
        jar = ov.get("jar", s.jar)
        if jar:
            item["jar"] = jar
        # extra 里的其他官方字段（click/playUrl/hide/searchable/timeout/style...）
        for k, vv in (s.extra or {}).items():
            if k not in item:
                item[k] = vv
        for k, v in ov.items():
            item[k] = v
        sites_out.append(item)
    out["sites"] = sites_out
    return out


@router.post("/{config_id}/publish")
def publish(config_id: int, session: Session = Depends(get_session)):
    """编译方案 → configs/published/{slug}.json"""
    c = _get(session, config_id)
    if not _slug_ok(c.slug):
        raise HTTPException(400, f"slug 只允许字母数字下划线连字符: {c.slug}")
    data = build_vod_json(session, c)
    if not data.get("sites"):
        raise HTTPException(400, "方案中没有启用站点，无法发布")
    # 发布健康提示：方案内近次测活失败的站点（不阻断发布，仅提示）
    from ..models import Site
    _cfg_links = session.exec(select(ConfigSite).where(ConfigSite.config_id == c.id)).all()
    unhealthy = []
    for l in _cfg_links:
        row = session.get(Site, l.site_id)
        if row and row.enabled and row.last_test_result and not row.last_test_result.get("ok"):
            unhealthy.append({"key": row.key, "name": row.name,
                              "message": (row.last_test_result.get("message") or "")[:80]})
    plain = json.dumps(data, ensure_ascii=False, indent=2)
    pub_dir = CONFIGS_DIR / "published"
    pub_dir.mkdir(parents=True, exist_ok=True)
    path = pub_dir / f"{c.slug}.json"
    if c.encrypt:
        if not c.enc_key:
            # 加密开但 key 缺失：自动生成 16 位随机 key 并持久化（防"以为加密实际明文"）
            import secrets as _sk
            c.enc_key = _sk.token_hex(8)
            session.add(c)
        from ..services.crypto import fongmi_encode
        path.write_text(fongmi_encode(plain, c.enc_key), encoding="utf-8")
    else:
        path.write_text(plain, encoding="utf-8")
    if not c.share_token:
        import secrets
        c.share_token = secrets.token_urlsafe(16)
    c.published_at = datetime.now(timezone.utc)
    session.add(c)
    session.commit()
    session.refresh(c)
    return {"ok": True, "path": str(path), "site_count": len(data["sites"]),
            "encrypted": bool(c.encrypt and c.enc_key),
            "unhealthy": unhealthy,
            "share_token": c.share_token}


@router.get("/{config_id}/download")
def download(config_id: int, token: str = "", session: Session = Depends(get_session)):
    """需 token（方案发布时生成）才可下载，防扫描"""
    c = _get(session, config_id)
    import secrets as _secrets
    if not c.share_token or not _secrets.compare_digest(token, c.share_token):
        raise HTTPException(403, "无效的下载 token")
    path = (CONFIGS_DIR / "published" / f"{c.slug}.json").resolve()
    if not str(path).startswith(str((CONFIGS_DIR / "published").resolve()) + "/"):
        raise HTTPException(400, "非法 slug")
    if not path.exists():
        raise HTTPException(404, "尚未发布，请先 publish")
    return FileResponse(path, media_type="application/json",
                        headers={"Content-Disposition": f"attachment; filename={c.slug}.json",
                                 "Cache-Control": "no-store"})


@router.get("/{config_id}/preview")
def preview(config_id: int, session: Session = Depends(get_session)):
    c = _get(session, config_id)
    import json as _json
    # 返回美化后的文本，前端直接展示（用户要求：JSON 要有语法整理，不要一大坨）
    return Response(content=_json.dumps(build_vod_json(session, c), ensure_ascii=False, indent=2),
                    media_type="application/json")


@router.get("/{config_id}/preview/stats")
def preview_stats(config_id: int, session: Session = Depends(get_session)):
    """方案编译统计：站点数/类型分布/禁用数/加密态，供发布前 sanity check"""
    c = _get(session, config_id)
    data = build_vod_json(session, c)
    sites = data.get("sites", [])
    types = {}
    for s in sites:
        types[str(s.get("type"))] = types.get(str(s.get("type")), 0) + 1
    total_links = session.exec(select(ConfigSite).where(ConfigSite.config_id == c.id)).all()
    return {
        "sites": len(sites),
        "disabled": len(total_links) - len(sites),
        "types": types,
        "has_spider": bool(data.get("spider")),
        "encrypted": bool(c.encrypt),
    }


@router.post("/{config_id}/publish-verify")
def publish_verify(config_id: int, session: Session = Depends(get_session)):
    """发布自检：读取已发布产物 → 若加密则按 2423 格式解密 → 校验 JSON 与站点数，
    验证「发布→下载→TVBox 解密」整条链路真实可用。"""
    c = _get(session, config_id)
    path = (CONFIGS_DIR / "published" / f"{c.slug}.json").resolve()
    if not str(path).startswith(str((CONFIGS_DIR / "published").resolve()) + "/"):
        raise HTTPException(400, "非法 slug")
    if not path.exists():
        raise HTTPException(404, "尚未发布，请先发布")
    raw = path.read_text(encoding="utf-8")
    import json as _json
    from ..services.crypto import fongmi_decode
    if raw.startswith("2423"):
        if not c.enc_key:
            return {"ok": False, "encrypted": True, "error": "密文存在但方案缺少 enc_key"}
        try:
            plain = fongmi_decode(raw)
        except Exception as e:
            return {"ok": False, "encrypted": True, "error": f"解密失败: {type(e).__name__}: {e}"}
    else:
        plain = raw
    try:
        data = _json.loads(plain)
    except Exception as e:
        return {"ok": False, "encrypted": raw.startswith("2423"), "error": f"解密后非合法 JSON: {e}"}
    sites = data.get("sites", [])
    return {
        "ok": True,
        "encrypted": raw.startswith("2423"),
        "sites": len(sites),
        "has_spider": bool(data.get("spider")),
        "top_keys": list(data.keys()),
        "bytes": len(raw),
    }
