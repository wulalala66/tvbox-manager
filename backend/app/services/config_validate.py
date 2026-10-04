"""发布前配置校验器：FongMi 配置语义校验（比 diagnose 更贴近"这份配置在 TVBox 里能不能跑"）。

校验规则（对照 FongMi CONFIG.md）：
1. site key 唯一性（同一方案内重复 key 会导致站点互相覆盖）。
2. lives[].epg 占位符合法性（只允许 {id} {name} {epg} 变量）。
3. catchup.source 必须非空且含占位或完整 URL；catchup.type 取值 append/default。
4. type=4 站点 ext 必须是合法 base64。
5. style.ratio 取值 0.75/1/1.33/1.78/1.0（数字或字符串）。
6. parses[].type 取值 0-4。
7. danmaku URL 占位符检查（{name}/{episode} 至少一个）。
返回 {ok, errors[], warnings[]}：errors 会影响播放，warnings 提示。
"""
import base64
import json
import re

EPG_OK_VARS = {"{id}", "{name}", "{epg}"}
STYLES_RATIOS = {"0.75", "1", "1.0", "1.33", "1.78"}


def _site_map(doc):
    sites = doc.get("sites", [])
    return sites if isinstance(sites, list) else []


def validate(doc: dict, enc_enabled: bool = False, enc_key: str = "") -> dict:
    errors, warnings = [], []

    # ---- 1. 站点 key 唯一 ----
    seen = {}
    for i, s in enumerate(_site_map(doc)):
        k = str(s.get("key") or "")
        if not k:
            errors.append(f"sites[{i}] 缺少 key")
            continue
        if k in seen:
            errors.append(f"站点 key 重复: {k}（第 {seen[k] + 1} 与第 {i + 1} 项）——TVBox 中后加载的会覆盖前者")
        else:
            seen[k] = i

    # ---- 2/3. lives epg + catchup ----
    lives = doc.get("lives", [])
    if isinstance(lives, list):
        for i, l in enumerate(lives):
            if not isinstance(l, dict):
                errors.append(f"lives[{i}] 不是对象")
                continue
            epg = str(l.get("epg") or "")
            if epg:
                for var in re.findall(r"\{[a-zA-Z]+\}", epg):
                    if var not in EPG_OK_VARS:
                        warnings.append(f"lives[{i}].epg 含未知占位符 {var}（合法: {{id}}/{{name}}/{{epg}}）")
            cu = l.get("catchup")
            if isinstance(cu, dict):
                ctype = cu.get("type", "append")
                if ctype not in ("append", "default"):
                    errors.append(f"lives[{i}].catchup.type={ctype!r} 非法（append/default）")
                src = str(cu.get("source") or "")
                if not src:
                    errors.append(f"lives[{i}].catchup.source 为空——时移回看将无法拼 URL")
                elif "{" not in src and not src.startswith(("http", "rtp", "udp")):
                    warnings.append(f"lives[{i}].catchup.source 无占位符也非标准协议前缀: {src[:50]}")

    # ---- 4. type=4 ext base64 ----
    for i, s in enumerate(_site_map(doc)):
        st = s.get("type")
        ext = s.get("ext")
        if st == 4 and ext is not None:
            if not isinstance(ext, str):
                errors.append(f"站点 {s.get('key')}（type=4）ext 必须是 base64 字符串")
                continue
            try:
                base64.b64decode(ext, validate=True)
            except Exception:
                errors.append(f"站点 {s.get('key')}（type=4）ext 不是合法 base64")

    # ---- 5. style.ratio ----
    for i, s in enumerate(_site_map(doc)):
        style = s.get("style")
        if isinstance(style, dict) and "ratio" in style:
            if str(style["ratio"]) not in STYLES_RATIOS:
                warnings.append(f"站点 {s.get('key')}.style.ratio={style['ratio']!r} 非 FongMi 常用值（0.75/1/1.33/1.78）")

    # ---- 6. parses type 0-4 ----
    parses = doc.get("parses", [])
    if isinstance(parses, list):
        for i, p in enumerate(parses):
            if not isinstance(p, dict):
                errors.append(f"parses[{i}] 不是对象")
                continue
            pt = p.get("type", 0)
            if not isinstance(pt, int) or not (0 <= pt <= 4):
                errors.append(f"parses[{i}].type={pt!r} 非法（0 嗅探/1 JSON/2 JSON扩展/3 聚合/4 超级）")
            if not str(p.get("url") or "").strip():
                errors.append(f"parses[{i}]（{p.get('name', '?')}）缺少 url")

    # ---- 7. danmaku 占位符 ----
    dan = doc.get("danmaku")
    if isinstance(dan, str) and dan.strip() and "{" not in dan:
        warnings.append("danmaku URL 不含 {name}/{episode} 占位符——FongMi 无法代入节目名匹配弹幕")

    # ---- 8. 加密一致性 ----
    # encrypt=True 且 enc_key 为空不算 error：publish() 会自动生成 key（configs.py:336-339）。
    # 仅当从未发布且未发布过（无法验证链路）时给 warning 提示。
    if enc_enabled and not enc_key:
        warnings.append("方案已启用加密但尚未生成密钥——发布时将自动生成（记得从「链接+密钥」获取）")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
