"""数据模型：Source(源文件) / Site(站点) / Config(配置方案) / ConfigSite(关联) / SourceVersion(版本)"""
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import JSON as SAJSON
from sqlmodel import JSON, Column, Field, Relationship, SQLModel


def now() -> datetime:
    return datetime.now(timezone.utc)


class Source(SQLModel, table=True):
    """源文件：js / py / jar"""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)                  # 展示名
    filename: str = Field(index=True, unique=True)  # 存储文件名（含扩展名）
    kind: str = Field(index=True)                  # js / py / jar
    size: int = 0
    sha256: str = Field(index=True, default="")
    meta: dict = Field(default={}, sa_column=Column(SAJSON(none_as_null=True)))  # 解析出的元数据
    status: str = "active"                         # active / disabled / broken
    note: str = ""
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
    current_version: int = 1

    versions: list["SourceVersion"] = Relationship(back_populates="source")

    @property
    def ref_count(self) -> int:
        # 由路由层填充，不落库
        return getattr(self, "_ref_count", 0)


class SourceVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="source.id", index=True)
    version: int
    filename: str
    sha256: str
    note: str = ""
    created_at: datetime = Field(default_factory=now)

    source: Source = Relationship(back_populates="versions")


class Site(SQLModel, table=True):
    """站点条目 = 最终 vod.json sites[] 的一项"""

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(index=True, unique=True)
    name: str
    site_type: int = 3                             # 0/1/3/4
    api: str = ""
    ext: Any = Field(default=None, sa_column=Column(JSON(none_as_null=True)))   # object / string / array / None
    jar: Optional[str] = None
    extra: dict = Field(default={}, sa_column=Column(SAJSON(none_as_null=True)))  # 其余全部字段（click/playUrl/hide/...）
    source_id: Optional[int] = Field(default=None, foreign_key="source.id")
    enabled: bool = True
    order_num: int = 0
    tags: list = Field(default=[], sa_column=Column(SAJSON(none_as_null=True)))
    last_test_at: Optional[datetime] = None
    last_test_result: Optional[dict] = Field(default=None, sa_column=Column(SAJSON(none_as_null=True)))
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class Config(SQLModel, table=True):
    """配置方案"""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    slug: str = Field(index=True, unique=True)
    global_spider: Optional[str] = None            # 全局 spider jar
    global_fields: dict = Field(default={}, sa_column=Column(SAJSON(none_as_null=True)))  # sites 外顶层字段
    encrypt: bool = False                          # 发布是否 2423 加密
    enc_key: Optional[str] = None                  # 加密 key（仅 encrypt=True 使用）
    share_token: Optional[str] = None              # 公开下载 token（防扫描）
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class ConfigSite(SQLModel, table=True):
    """方案 ↔ 站点 多对多，含方案级覆写"""

    config_id: int = Field(foreign_key="config.id", primary_key=True)
    site_id: int = Field(foreign_key="site.id", primary_key=True)
    order_num: int = 0
    # SAJSON(none_as_null=True)：Python None 必须落库为 SQL NULL（否则 JSON 序列化成字符串 'null'）
    overrides: Optional[dict] = Field(
        default=None, sa_column=Column(SAJSON(none_as_null=True)))  # 该方案内的字段覆写
