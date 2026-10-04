"""源文件管理服务：存储、去重、版本"""
import base64
import hashlib
import re
import shutil
import unicodedata
from pathlib import Path

from sqlmodel import Session, select

from ..config import SOURCES_DIR, UPLOAD_EXT
from ..models import Source, SourceVersion
from .source_parser import parse_source


def slugify_filename(name: str, kind: str) -> str:
    """规范化文件名：安全字符 + kind 后缀"""
    base = Path(name).stem
    base = unicodedata.normalize("NFKC", base)
    base = re.sub(r"[^\w\-一-龥]+", "_", base).strip("_") or "source"
    return f"{base}.{kind}"


def unique_filename(session: Session, filename: str, self_id: int = None) -> str:
    """同名不同内容时自动 v2/v3…"""
    stmt = select(Source)
    existing = {s.filename: s.id for s in session.exec(stmt)}
    if filename not in existing or existing[filename] == self_id:
        return filename
    stem, ext = Path(filename).stem, Path(filename).suffix
    i = 2
    while f"{stem}_v{i}{ext}" in existing and existing[f"{stem}_v{i}{ext}"] != self_id:
        i += 1
    return f"{stem}_v{i}{ext}"


def content_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_exists(session: Session, sha: str) -> Source | None:
    return session.exec(select(Source).where(Source.sha256 == sha)).first()


def store_file(filename: str, kind: str, data: bytes, overwrite: bool = False) -> Path:
    d = SOURCES_DIR / kind
    d.mkdir(parents=True, exist_ok=True)
    p = d / filename
    # overwrite=True：主文件原位覆盖（覆盖上传/回滚语义）；否则 O_EXCL 排他写防并发同名覆盖
    if overwrite and p.exists():
        p.write_bytes(data)
        return p
    # Minor #12：O_EXCL 排他写防并发同名覆盖；已存在则换 v2/v3 名重试
    import os as _os
    target = p
    for _ in range(20):
        try:
            fd = _os.open(target, _os.O_WRONLY | _os.O_CREAT | _os.O_EXCL, 0o644)
            with _os.fdopen(fd, "wb") as fh:
                fh.write(data)
            break
        except FileExistsError:
            stem, ext = target.stem, target.suffix
            i = 2
            while (target.parent / f"{stem}_v{i}{ext}").exists():
                i += 1
            target = target.parent / f"{stem}_v{i}{ext}"
    else:
        raise RuntimeError("无法写入源文件（重试 20 次仍冲突）")
    return target


def detect_kind(filename: str) -> str | None:
    return UPLOAD_EXT.get(Path(filename).suffix.lower())


def create_source(session: Session, *, filename_hint: str, kind: str, data: bytes,
                  note: str = "", name: str | None = None) -> tuple[Source, bool]:
    """创建源（自动去重）。返回 (source, created)"""
    if not data or not data.strip():
        raise ValueError("源文件内容不能为空")
    sha = content_sha256(data)
    dup = sha_exists(session, sha)
    if dup:
        return dup, False
    filename = unique_filename(session, slugify_filename(filename_hint, kind))
    path = store_file(filename, kind, data)
    # Minor #12：并发冲突换名后，以实际写入名为准（DB/磁盘一致）
    if path.name != filename:
        filename = path.name
    meta = parse_source(kind, path)
    src = Source(name=name or meta.get("title") or Path(filename).stem,
                 filename=filename, kind=kind, size=len(data), sha256=sha,
                 meta=meta, note=note)
    session.add(src)
    session.commit()
    session.refresh(src)
    ver = SourceVersion(source_id=src.id, version=1, filename=filename,
                        sha256=sha, note="initial")
    session.add(ver)
    session.commit()
    # M4：v1 快照落盘，保证任意源都能 rollback v1
    vdir = SOURCES_DIR / kind / f".versions/{src.id}"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / f"v1_{filename}").write_bytes(data)
    return src, True


def create_source_from_b64(session: Session, filename: str, kind: str, b64: str, **kw):
    return create_source(session, filename_hint=filename, kind=kind,
                         data=base64.b64decode(b64), **kw)


def new_version(session: Session, src: Source, data: bytes, note: str = "") -> SourceVersion:
    """覆盖保存 → 新版本（显式先快照当前主文件，消除调用方隐式契约）"""
    snapshot_current(session, src)  # 幂等：主文件不变则覆盖同一快照
    sha = content_sha256(data)
    path = store_file(src.filename, src.kind, data, overwrite=True)
    ver = SourceVersion(source_id=src.id, version=src.current_version + 1,
                        filename=src.filename, sha256=sha, note=note)
    src.size = len(data)
    src.sha256 = sha
    src.current_version += 1
    src.meta = parse_source(src.kind, path)
    src.updated_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    session.add(ver)
    session.add(src)
    session.commit()
    session.refresh(src)
    return ver


def version_file(session: Session, src: Source, version: int) -> Path:
    """某版本的文件路径（版本目录缓存）"""
    d = SOURCES_DIR / src.kind / f".versions/{src.id}"
    d.mkdir(parents=True, exist_ok=True)
    ver = session.exec(select(SourceVersion).where(
        SourceVersion.source_id == src.id, SourceVersion.version == version)).first()
    if not ver:
        raise FileNotFoundError(f"version {version} not found")
    f = d / f"v{version}_{src.filename}"
    if not f.exists():
        # 当前版本内容从主文件拷贝，历史版本仅在新版本时快照
        raise FileNotFoundError(f"version {version} file missing")
    return f


def snapshot_current(session: Session, src: Source):
    """覆盖保存前快照当前主文件到版本目录"""
    d = SOURCES_DIR / src.kind / f".versions/{src.id}"
    d.mkdir(parents=True, exist_ok=True)
    src_path = SOURCES_DIR / src.kind / src.filename
    if src_path.exists():
        shutil.copy2(src_path, d / f"v{src.current_version}_{src.filename}")


def rollback(session: Session, src: Source, version: int):
    ver = session.exec(select(SourceVersion).where(
        SourceVersion.source_id == src.id, SourceVersion.version == version)).first()
    if not ver:
        raise FileNotFoundError(f"version {version} not found")
    f = SOURCES_DIR / src.kind / f".versions/{src.id}/v{version}_{src.filename}"
    if not f.exists():
        raise FileNotFoundError(f"version {version} file missing")
    data = f.read_bytes()
    snapshot_current(session, src)
    new_version(session, src, data, note=f"rollback to v{version}")


def ref_count(session: Session, source_id: int) -> int:
    from ..models import Site
    return len(session.exec(select(Site).where(Site.source_id == source_id)).all())
