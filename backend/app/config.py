"""系统配置"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # tvbox-manager/
DATA_DIR = Path(os.environ.get("TVBOX_DATA_DIR", BASE_DIR / "data"))
SOURCES_DIR = DATA_DIR / "sources"
CONFIGS_DIR = DATA_DIR / "configs"
IMPORTS_DIR = DATA_DIR / "imports"
LOGS_DIR = DATA_DIR / "logs"
DB_PATH = DATA_DIR / "tvbox.db"

UPLOAD_EXT = {".js": "js", ".py": "py", ".jar": "jar"}
MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100MB

for d in (DATA_DIR, SOURCES_DIR, SOURCES_DIR / "js", SOURCES_DIR / "py",
          SOURCES_DIR / "jar", CONFIGS_DIR, CONFIGS_DIR / "draft",
          CONFIGS_DIR / "published", IMPORTS_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)
