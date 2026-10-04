"""引用完整性死链扫描：全库扫描 site→source、config→site、global_fields→URL，报告死链。

只读扫描（网络检查仅对 config 1 的 lives 做可选 HEAD 探测，默认关闭）。
输出：site_orphans（source_id 悬空）、source_missing（磁盘文件缺失）、
site_dup_key、config_orphans（configsite 悬空）、gf_url_bad（lives/parses 非法 URL）。
"""
import json
import re
import sqlite3
from pathlib import Path

DB = Path('/opt/spider/tvbox/tvbox-manager/data/tvbox.db')
SOURCES_DIR = Path('/opt/spider/tvbox/tvbox-manager/data/sources')

con = sqlite3.connect(f'file:{DB}?mode=ro', uri=True)
con.row_factory = sqlite3.Row

report = {}

# 1. site.source_id 悬空（引用了不存在的源）
rows = con.execute("SELECT id, key, name, source_id FROM site WHERE source_id IS NOT NULL").fetchall()
src_ids = {r[0] for r in con.execute("SELECT id FROM source").fetchall()}
report['site_orphans'] = [
    {'id': r['id'], 'key': r['key'], 'name': r['name'], 'source_id': r['source_id']}
    for r in rows if r['source_id'] not in src_ids
]

# 2. source 磁盘文件缺失
missing = []
for r in con.execute("SELECT id, kind, filename FROM source").fetchall():
    p = SOURCES_DIR / r['kind'] / r['filename']
    if not p.exists():
        missing.append({'id': r['id'], 'kind': r['kind'], 'filename': r['filename']})
report['source_missing'] = missing

# 3. site key 重复
dups = con.execute(
    "SELECT key, COUNT(*) n FROM site GROUP BY key HAVING n > 1").fetchall()
report['site_dup_key'] = [{'key': r['key'], 'count': r['n']} for r in dups]

# 4. configsite 悬空（config/site 已删但关联还在）
co = con.execute("""
    SELECT cs.config_id, cs.site_id FROM configsite cs
    WHERE NOT EXISTS (SELECT 1 FROM config c WHERE c.id = cs.config_id)
       OR NOT EXISTS (SELECT 1 FROM site s WHERE s.id = cs.site_id)
""").fetchall()
report['config_orphans'] = [{'config_id': r['config_id'], 'site_id': r['site_id']} for r in co]

# 5. source.filename 与磁盘存在但不匹配 kind 的文件（错位）
misplaced = []
for r in con.execute("SELECT id, kind, filename FROM source").fetchall():
    # 同名文件在别的 kind 目录
    for other in ('py', 'js', 'jar'):
        if other != r['kind'] and (SOURCES_DIR / other / r['filename']).exists():
            misplaced.append({'id': r['id'], 'declared': r['kind'], 'found_in': other, 'filename': r['filename']})
report['source_misplaced'] = misplaced

# 6. site.api 相对路径形态 ./py/x.py 或 ./js/x.js 但源库没有该文件（不限 config 关联，全库扫）
bad_api = []
for r in con.execute("SELECT id, key, name, site_type, api FROM site").fetchall():
    api = (r['api'] or '').strip()
    m = re.match(r'^\./(py|js)/(.+)$', api)
    if m:
        kind, fn = m.group(1), m.group(2)
        if not (SOURCES_DIR / kind / fn).exists():
            bad_api.append({'id': r['id'], 'key': r['key'], 'api': api})
report['site_bad_api_path'] = bad_api

# 7. global_fields 里 lives/parses 的 URL 语法检查（不联网，只查非 http 前缀）
gf_bad = []
for r in con.execute("SELECT id, slug, global_fields FROM config").fetchall():
    try:
        gf = json.loads(r['global_fields'] or '{}')
    except Exception:
        gf_bad.append({'config_id': r['id'], 'slug': r['slug'], 'error': 'global_fields 非法 JSON'})
        continue
    for l in gf.get('lives', []):
        u = str(l.get('url') or '')
        if not u.startswith(('http://', 'https://')):
            gf_bad.append({'config_id': r['id'], 'slug': r['slug'], 'kind': 'life', 'name': l.get('name'), 'url': u[:80]})
    for p in gf.get('parses', []):
        u = str(p.get('url') or '')
        if not u.startswith(('http://', 'https://')):
            gf_bad.append({'config_id': r['id'], 'slug': r['slug'], 'kind': 'parse', 'name': p.get('name'), 'url': u[:80]})
report['gf_url_bad'] = gf_bad

# 8. site.ext JSON 合法性
ext_bad = []
for r in con.execute("SELECT id, key, ext FROM site WHERE ext IS NOT NULL AND ext != ''").fetchall():
    try:
        json.loads(r['ext'])
    except Exception:
        ext_bad.append({'id': r['id'], 'key': r['key'], 'ext': r['ext'][:60]})
report['site_ext_bad_json'] = ext_bad

con.close()
total = sum(len(v) if isinstance(v, list) else 0 for v in report.values())
print(json.dumps({**report, '_total_issues': total}, ensure_ascii=False, indent=1))
