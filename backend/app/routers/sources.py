"""路由：源文件管理"""
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from datetime import datetime, timezone
from sqlmodel import Session, select

from ..config import MAX_UPLOAD_SIZE, SOURCES_DIR, UPLOAD_EXT
from ..database import get_session
from ..models import Site, Source, SourceVersion
from ..services import source_store

router = APIRouter(prefix="/sources", tags=["sources"])


def to_out(session: Session, s: Source, ref_count: int | None = None) -> dict:
    if ref_count is None:
        ref_count = source_store.ref_count(session, s.id)
    return {
        "id": s.id, "name": s.name, "filename": s.filename, "kind": s.kind,
        "size": s.size, "sha256": s.sha256[:16], "meta": s.meta, "status": s.status,
        "note": s.note, "current_version": s.current_version,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        "ref_count": ref_count,
    }


def _ref_counts(session: Session) -> dict[int, int]:
    """一次 GROUP BY 拿全部源引用数（M10 N+1 修复）"""
    from sqlalchemy import func
    rows = session.exec(
        select(Site.source_id, func.count(Site.id))
        .where(Site.source_id != None)  # noqa: E711
        .group_by(Site.source_id)).all()
    return {sid: n for sid, n in rows}


def _get(session: Session, source_id: int) -> Source:
    s = session.get(Source, source_id)
    if not s:
        raise HTTPException(404, "源不存在")
    return s


@router.get("")
def list_sources(kind: str = None, q: str = None, page: int = None, page_size: int = 50,
                 session: Session = Depends(get_session)):
    items = session.exec(select(Source).order_by(Source.updated_at.desc())).all()
    if kind:
        items = [s for s in items if s.kind == kind]
    if q:
        ql = q.lower()
        items = [s for s in items if ql in s.name.lower() or ql in s.filename.lower()]
    counts = _ref_counts(session)
    if page is None or page < 1:
        return [to_out(session, s, counts.get(s.id, 0)) for s in items]
    total = len(items)
    start = (page - 1) * page_size
    return {"items": [to_out(session, s, counts.get(s.id, 0)) for s in items[start:start + page_size]],
            "total": total, "page": page, "page_size": page_size}


@router.post("/upload")
async def upload(files: list[UploadFile] = File(...), overwrite: bool = False,
                 session: Session = Depends(get_session)):
    out = []
    for f in files:
        kind = source_store.detect_kind(f.filename)
        if not kind:
            raise HTTPException(400, f"不支持的文件类型: {f.filename}（仅 {list(UPLOAD_EXT)}）")
        data = await f.read()
        if not data.strip():
            raise HTTPException(400, f"{f.filename} 内容为空")
        if len(data) > MAX_UPLOAD_SIZE:
            raise HTTPException(400, f"{f.filename} 超过大小限制")
        if overwrite:
            # 覆盖上传：同文件名（同类型）的已有源 → 生成新版本；否则新建
            target = session.exec(select(Source).where(
                Source.kind == kind,
                Source.filename == source_store.slugify_filename(f.filename, kind))).first()
            if target:
                ver = source_store.new_version(session, target, data, note=f"overwrite upload: {f.filename}")
                out.append({**to_out(session, target), "created": False, "overwritten": True,
                            "version": ver.version})
                continue
        src, created = source_store.create_source(
            session, filename_hint=f.filename, kind=kind, data=data,
            note=f"upload: {f.filename}")
        out.append({**to_out(session, src), "created": created})
    return out


@router.post("/import-url")
async def import_url(url: str, name: str = None, session: Session = Depends(get_session)):
    fn = Path(urlparse(url).path).name or "source"
    kind = source_store.detect_kind(fn)
    if not kind:
        raise HTTPException(400, f"URL 无可识别扩展名: {url}")
    from ..services.safe_fetch import safe_get
    try:
        data = safe_get(url)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"下载失败: {e}")
    src, created = source_store.create_source(
        session, filename_hint=fn, kind=kind, data=data,
        note=f"url: {url}", name=name)
    return {**to_out(session, src), "created": created}


@router.get("/{source_id}")
def get_source(source_id: int, session: Session = Depends(get_session)):
    return to_out(session, _get(session, source_id))


@router.get("/{source_id}/raw")
def raw(source_id: int, download: bool = False, session: Session = Depends(get_session)):
    s = _get(session, source_id)
    path = SOURCES_DIR / s.kind / s.filename
    if not path.exists():
        raise HTTPException(404, "文件丢失")
    headers = {"Content-Disposition": f"attachment; filename={s.filename}"} if download else {}
    return FileResponse(path, headers=headers)


@router.get("/{source_id}/content")
def get_content(source_id: int, session: Session = Depends(get_session)):
    """文本源在线编辑读取（js/py），jar 不允许"""
    s = _get(session, source_id)
    if s.kind == "jar":
        raise HTTPException(400, "jar 不支持在线编辑")
    path = SOURCES_DIR / s.kind / s.filename
    if not path.exists():
        raise HTTPException(404, "文件丢失")
    return {"content": path.read_text(encoding="utf-8", errors="replace")}


@router.put("/{source_id}/content")
def save_content(source_id: int, body: dict, session: Session = Depends(get_session)):
    s = _get(session, source_id)
    if s.kind == "jar":
        raise HTTPException(400, "jar 不支持在线编辑")
    content = body.get("content", "")
    if not content or not content.strip():
        raise HTTPException(400, "内容不能为空")
    note = body.get("note", "在线编辑")
    source_store.snapshot_current(session, s)
    source_store.new_version(session, s, content.encode("utf-8"), note=note)
    return to_out(session, s)


@router.get("/{source_id}/versions")
def versions(source_id: int, session: Session = Depends(get_session)):
    _get(session, source_id)
    vs = session.exec(select(SourceVersion).where(
        SourceVersion.source_id == source_id).order_by(SourceVersion.version.desc())).all()
    return [{"version": v.version, "sha256": v.sha256[:16], "note": v.note,
             "created_at": v.created_at.isoformat()} for v in vs]


@router.post("/{source_id}/rollback/{version}")
def rollback(source_id: int, version: int, session: Session = Depends(get_session)):
    s = _get(session, source_id)
    try:
        source_store.rollback(session, s, version)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return to_out(session, s)


@router.get("/{source_id}/usages")
def usages(source_id: int, session: Session = Depends(get_session)):
    _get(session, source_id)
    sites = session.exec(select(Site).where(Site.source_id == source_id)).all()
    return [{"id": st.id, "key": st.key, "name": st.name, "api": st.api} for st in sites]


@router.put("/{source_id}")
def update_source(source_id: int, body: dict, session: Session = Depends(get_session)):
    s = _get(session, source_id)
    if "name" in body and body["name"]:
        s.name = body["name"]
    if "note" in body:
        s.note = body["note"]
    if "status" in body:
        s.status = body["status"]
    # 重命名 → 同步引用站点的 api/jar
    if "filename" in body and body["filename"] and body["filename"] != s.filename:
        old_filename = s.filename
        new_fn = source_store.unique_filename(
            session, source_store.slugify_filename(body["filename"], s.kind), s.id)
        old_path = SOURCES_DIR / s.kind / s.filename
        s.filename = new_fn
        old_path.rename(SOURCES_DIR / s.kind / new_fn)
        old_stem = Path(old_filename).stem
        new_stem = Path(new_fn).stem
        # M5：同步重命名历史版本快照，否则 rollback 全部 404
        vdir = SOURCES_DIR / s.kind / f".versions/{s.id}"
        if vdir.is_dir():
            for vf in vdir.iterdir():
                if vf.name.endswith(old_filename):
                    vf.rename(vdir / (vf.name[:-len(old_filename)] + new_fn))
        # M5：api 替换按文件名边界（.py/.js 前的完整 stem），避免子串误伤
        for site in session.exec(select(Site).where(Site.source_id == s.id)).all():
            if site.api:
                for tok_old, tok_new in ((old_filename, new_fn), (old_stem + ".", new_stem + ".")):
                    if tok_old in site.api:
                        site.api = site.api.replace(tok_old, tok_new)
                        session.add(site)
            if site.jar and old_filename in site.jar:
                site.jar = site.jar.replace(old_filename, new_fn)
                session.add(site)
    session.add(s)
    s.updated_at = datetime.now(timezone.utc)
    session.commit()
    session.refresh(s)
    return to_out(session, s)


@router.delete("/{source_id}")
def delete_source(source_id: int, force: bool = False, session: Session = Depends(get_session)):
    s = _get(session, source_id)
    refs = session.exec(select(Site).where(Site.source_id == source_id)).all()
    if refs and not force:
        raise HTTPException(409, {"detail": "存在引用站点", "refs": [
            {"id": r.id, "key": r.key, "name": r.name} for r in refs]})
    if refs and force:
        # 强制删除前先断开引用（置 NULL），否则 FK 约束 500
        for r in refs:
            r.source_id = None
            session.add(r)
    for v in session.exec(select(SourceVersion).where(
            SourceVersion.source_id == s.id)).all():
        session.delete(v)
    session.delete(s)
    session.commit()
    # DB 提交成功后再删文件（Minor #4：避免 commit 失败产生 DB 悬空引用）
    path = SOURCES_DIR / s.kind / s.filename
    if path.exists():
        path.unlink(missing_ok=True)
    vdir = SOURCES_DIR / s.kind / ".versions" / str(source_id)
    import shutil
    if vdir.is_dir():
        shutil.rmtree(vdir, ignore_errors=True)
    return {"ok": True}


@router.get("/orphans/scan")
def scan_orphans(session: Session = Depends(get_session)):
    """孤儿源体检：磁盘上存在但 DB 无登记、或 DB 登记但文件缺失、或 0 引用的源。"""
    from pathlib import Path as _Path
    db_files: dict[str, dict] = {}
    for s in session.exec(select(Source)).all():
        db_files[f"{s.kind}/{s.filename}"] = {
            "id": s.id, "name": s.name, "kind": s.kind, "filename": s.filename,
            "size": s.size, "ref_count": source_store.ref_count(session, s.id),
            "issue": "missing_file" if not (SOURCES_DIR / s.kind / s.filename).exists() else None,
        }
    disk_files = []
    for kind in ("js", "py", "jar"):
        d = SOURCES_DIR / kind
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if not p.is_file() or p.name.startswith("."):
                continue
            key = f"{kind}/{p.name}"
            if key not in db_files:
                disk_files.append({
                    "path": key, "kind": kind, "filename": p.name,
                    "size": p.stat().st_size,
                })
    registered = [v for v in db_files.values()]
    unreferenced = [v for v in registered if v["ref_count"] == 0 and v["issue"] is None]
    missing = [v for v in registered if v["issue"] == "missing_file"]
    return {
        "total_db": len(registered),
        "total_disk": len(disk_files) + len([v for v in registered if v["issue"] is None]),
        "not_in_db": disk_files,       # 磁盘有、DB 无（上传中断/手动放置）
        "missing_file": missing,       # DB 有、文件丢
        "unreferenced": unreferenced,  # 0 站点引用
    }


@router.post("/orphans/cleanup")
def cleanup_orphans(body: dict = None, session: Session = Depends(get_session)):
    """清理孤儿源：删除 not_in_db 的磁盘文件（可选）；DB 缺文件的记录（可选）。"""
    body = body or {}
    removed_files = []
    removed_rows = []
    if body.get("remove_not_in_db"):
        for item in body.get("not_in_db", []):
            p = SOURCES_DIR / item["path"]
            if p.exists() and p.is_file():
                p.unlink()
                removed_files.append(item["path"])
    if body.get("remove_missing_rows"):
        for item in body.get("missing_rows", []):
            s = session.get(Source, item["id"])
            if s:
                for v in session.exec(select(SourceVersion).where(
                        SourceVersion.source_id == s.id)).all():
                    session.delete(v)
                session.delete(s)
                removed_rows.append({"id": item["id"], "name": item["name"]})
    session.commit()
    return {"ok": True, "removed_files": removed_files, "removed_rows": removed_rows}
