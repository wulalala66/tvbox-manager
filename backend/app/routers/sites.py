"""路由：站点管理"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timezone
from sqlalchemy import delete as sa_delete
from sqlmodel import Session, select

from ..database import get_session
from ..models import ConfigSite, Site
from ..schemas import SiteCreate, SiteOut, SiteUpdate

router = APIRouter(prefix="/sites", tags=["sites"])


def to_out(s: Site) -> dict:
    return {
        "id": s.id, "key": s.key, "name": s.name, "site_type": s.site_type,
        "api": s.api, "ext": s.ext, "jar": s.jar, "extra": s.extra,
        "source_id": s.source_id, "enabled": s.enabled, "order_num": s.order_num,
        "tags": s.tags, "last_test_at": s.last_test_at, "last_test_result": s.last_test_result,
    }


@router.get("")
def list_sites(q: str = None, tag: str = None, source_id: int = None,
               page: int = None, page_size: int = 50,
               session: Session = Depends(get_session)):
    """page 缺省返回全量列表（兼容旧前端）；page>=1 时返回 {items, total, page, page_size}"""
    items = session.exec(select(Site).order_by(Site.order_num, Site.id)).all()
    if q:
        ql = q.lower()
        items = [s for s in items if ql in s.key.lower() or ql in s.name.lower()]
    if tag:
        items = [s for s in items if tag in (s.tags or [])]
    if source_id is not None:
        items = [s for s in items if s.source_id == source_id]
    if page is None or page < 1:
        return [to_out(s) for s in items]
    total = len(items)
    start = (page - 1) * page_size
    return {"items": [to_out(s) for s in items[start:start + page_size]],
            "total": total, "page": page, "page_size": page_size}


@router.post("")
def create_site(body: SiteCreate, session: Session = Depends(get_session)):
    if session.exec(select(Site).where(Site.key == body.key)).first():
        raise HTTPException(409, f"站点 key 已存在: {body.key}")
    s = Site(**body.model_dump())
    session.add(s)
    session.commit()
    session.refresh(s)
    return to_out(s)


@router.get("/{site_id}")
def get_site(site_id: int, session: Session = Depends(get_session)):
    s = session.get(Site, site_id)
    if not s:
        raise HTTPException(404)
    return to_out(s)


@router.put("/{site_id}")
def update_site(site_id: int, body: SiteUpdate, session: Session = Depends(get_session)):
    s = session.get(Site, site_id)
    if not s:
        raise HTTPException(404)
    data = body.model_dump(exclude_unset=True)
    if "key" in data and data["key"] != s.key:
        if session.exec(select(Site).where(Site.key == data["key"])).first():
            raise HTTPException(409, f"站点 key 已存在: {data['key']}")
    for k, v in data.items():
        setattr(s, k, v)
    session.add(s)
    s.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(s)
    return to_out(s)


@router.delete("/{site_id}")
def delete_site(site_id: int, session: Session = Depends(get_session)):
    s = session.get(Site, site_id)
    if not s:
        raise HTTPException(404)
    # 同步删除配置关联（Core 层 delete：unit-of-work 在无 relationship
    # 的复合主键关联表场景下可能吞掉 DELETE FROM configsite → FK 500）
    session.exec(sa_delete(ConfigSite).where(ConfigSite.site_id == site_id))
    session.delete(s)
    session.commit()
    return {"ok": True}


@router.post("/reorder")
def reorder(body: dict, session: Session = Depends(get_session)):
    """body: {order: [site_id,...]} 按数组顺序写 order_num"""
    order = body.get("order", [])
    for i, sid in enumerate(order):
        s = session.get(Site, sid)
        if s:
            s.order_num = i
            session.add(s)
    session.commit()
    return {"ok": True}


@router.post("/batch-delete")
def batch_delete(body: dict, session: Session = Depends(get_session)):
    """body: {ids: [site_id,...]} 批量删除站点（连带清理方案关联）"""
    ids = body.get("ids") or []
    deleted, missing = [], []
    for sid in ids:
        s = session.get(Site, sid)
        if not s:
            missing.append(sid)
            continue
        session.exec(sa_delete(ConfigSite).where(ConfigSite.site_id == sid))
        session.delete(s)
        deleted.append(sid)
    session.commit()
    return {"ok": True, "deleted": deleted, "missing": missing}


@router.post("/batch-enabled")
def batch_enabled(body: dict, session: Session = Depends(get_session)):
    """body: {ids: [...], enabled: true/false} 批量启停"""
    ids = body.get("ids") or []
    enabled = bool(body.get("enabled", True))
    n = 0
    for sid in ids:
        s = session.get(Site, sid)
        if s:
            s.enabled = enabled
            session.add(s)
            n += 1
    session.commit()
    return {"ok": True, "updated": n}


@router.post("/batch-tag")
def batch_tag(body: dict, session: Session = Depends(get_session)):
    """body: {ids: [...], add_tags: [...], remove_tags: [...]} 批量打/去标签"""
    ids = body.get("ids") or []
    add = body.get("add_tags") or []
    remove = body.get("remove_tags") or []
    n = 0
    for sid in ids:
        s = session.get(Site, sid)
        if not s:
            continue
        tags = list(s.tags or [])
        tags += [t for t in add if t not in tags]
        tags = [t for t in tags if t not in remove]
        s.tags = tags
        session.add(s)
        n += 1
    session.commit()
    return {"ok": True, "updated": n}
