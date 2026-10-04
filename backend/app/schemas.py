"""Pydantic DTO"""
from typing import Any, Optional

from pydantic import BaseModel


class SourceOut(BaseModel):
    id: int
    name: str
    filename: str
    kind: str
    size: int
    sha256: str
    meta: dict
    status: str
    note: str
    current_version: int
    ref_count: int = 0


class SiteBase(BaseModel):
    key: str
    name: str
    site_type: int = 3
    api: str = ""
    ext: Any = None
    jar: Optional[str] = None
    extra: dict = {}
    source_id: Optional[int] = None
    enabled: bool = True
    order_num: int = 0
    tags: list = []


class SiteCreate(SiteBase):
    pass


class SiteUpdate(BaseModel):
    """部分字段更新：None 跳过"""

    key: Optional[str] = None
    name: Optional[str] = None
    site_type: Optional[int] = None
    api: Optional[str] = None
    ext: Any = None
    jar: Optional[str] = None
    extra: Optional[dict] = None
    source_id: Optional[int] = None
    enabled: Optional[bool] = None
    order_num: Optional[int] = None
    tags: Optional[list] = None


class SiteOut(SiteBase):
    id: int
    last_test_at: Optional[str] = None
    last_test_result: Optional[dict] = None
    source_name: Optional[str] = None


class ConfigBase(BaseModel):
    name: str
    slug: str = ""
    global_spider: Optional[str] = None
    global_fields: dict = {}
    encrypt: bool = False
    enc_key: Optional[str] = None


class ConfigCreate(ConfigBase):
    pass


class ConfigUpdate(BaseModel):
    name: Optional[str] = None
    slug: Optional[str] = None
    global_spider: Optional[str] = None
    global_fields: Optional[dict] = None
    encrypt: Optional[bool] = None
    enc_key: Optional[str] = None


class ConfigOut(ConfigBase):
    id: int
    published_at: Optional[str] = None
    site_count: int = 0


class ImportAnalyzeIn(BaseModel):
    type: str  # text / url / config_url / config_text
    content: Optional[str] = None
    url: Optional[str] = None
    kind_hint: Optional[str] = None  # js / py / jar / config


class ImportCandidate(BaseModel):
    """一个待确认的导入条目：可能同时产生 source + site"""

    key: str
    name: str
    site_type: int = 3
    api: str = ""
    ext: Any = None
    jar: Optional[str] = None
    kind: Optional[str] = None       # js/py/jar —— 若附带源文件
    filename: Optional[str] = None   # 源文件建议名
    content_b64: Optional[str] = None  # 内嵌源码（text 输入时）
    source_url: Optional[str] = None   # 远程源文件地址
    meta: dict = {}
    warnings: list = []
    extra: dict = {}   # 除核心列外的全部站点字段（不丢字段）
