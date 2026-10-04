"""源文件解析器：提取 js/py/jar 元数据"""
import re
import zipfile
from pathlib import Path


def parse_js(path: Path, text: str = None) -> dict:
    """JS 源 meta：方法清单、drpy 检测、import 依赖、疑似站点域名"""
    if text is None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        except Exception:
            text = ""
    meta = {}
    methods = sorted(set(re.findall(r"^\s{2,4}(async\s+)?([a-zA-Z_$][\w$]*)\s*\(", text, re.M)
                      ))
    KNOWN = {"init", "home", "homeVod", "homeContent", "homeVideoContent", "category",
             "categoryContent", "detail", "detailContent", "search", "searchContent",
             "play", "playerContent", "live", "liveContent", "proxy", "action",
             "sniffer", "manualVideoCheck", "isVideo", "isVideoFormat", "destroy"}
    meta["methods"] = [m for m in methods if m in KNOWN]
    meta["drpy"] = "__jsEvalReturn" in text
    meta["imports"] = sorted(set(re.findall(
        r"import\s+[^;]*?from\s+['\"]([^'\"]+)['\"]", text)))[:20]
    # 疑似 host（url 常量）
    hosts = re.findall(r"https?://([\w.-]+)", text)
    from collections import Counter
    meta["hosts"] = [h for h, _ in Counter(hosts).most_common(5)]
    # 标题
    m = re.search(r"(?:title|siteName|name)\s*[:=]\s*['\"]([^'\"]{1,30})['\"]", text)
    if m:
        meta["title"] = m.group(1)
    return meta


def parse_py(path: Path, text: str = None) -> dict:
    """Python 源 meta：类定义、getDependence 依赖、host"""
    if text is None:
        try:
            text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        except Exception:
            text = ""
    meta = {}
    meta["has_spider_class"] = bool(re.search(r"class\s+Spider\s*\(", text))
    meta["extends_base"] = "base.spider" in text or "from base" in text
    # getDependence 依赖
    m = re.search(r"def\s+getDependence\s*\(self[^)]*\)\s*[:\s]*return\s*\[(.*?)\]", text, re.S)
    if m:
        meta["dependencies"] = re.findall(r"['\"]([^'\"]+)['\"]", m.group(1))
    methods = re.findall(r"def\s+([a-zA-Z_]\w*)\s*\(self", text)
    KNOWN = {"init", "homeContent", "homeVideoContent", "categoryContent", "detailContent",
             "searchContent", "playerContent", "liveContent", "localProxy", "action",
             "isVideoFormat", "manualVideoCheck", "destroy", "getDependence"}
    meta["methods"] = [m for m in methods if m in KNOWN]
    from collections import Counter
    hosts = re.findall(r"https?://([\w.-]+)", text)
    meta["hosts"] = [h for h, _ in Counter(hosts).most_common(5)]
    m = re.search(r"self\.name\s*=\s*['\"]([^'\"]{1,30})['\"]", text)
    if m:
        meta["title"] = m.group(1)
    return meta


def parse_jar(path: Path) -> dict:
    """jar meta：zip 校验、dex 存在、csp_ 类名字符串扫描"""
    meta = {}
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            meta["valid_zip"] = True
            meta["has_dex"] = any(n.endswith(".dex") for n in names)
            meta["entries"] = len(names)
            classes = set()
            for n in names:
                if n.endswith(".dex"):
                    data = z.read(n)
                    classes.update(re.findall(rb"com[/\\]github[/\\]catvod[/\\]spider[/\\]([A-Za-z0-9_$]+)", data))
            meta["csp_classes"] = sorted(c.decode() for c in classes)[:50]
    except zipfile.BadZipFile:
        meta["valid_zip"] = False
    return meta


def parse_source(kind: str, path: Path, text: str = None) -> dict:
    if kind == "js":
        return parse_js(path, text)
    if kind == "py":
        return parse_py(path, text)
    if kind == "jar":
        return parse_jar(path)
    return {}
