"""直播源预览服务：抓取 url 解析 txt/m3u/json 格式，返回分组/频道统计+样例"""
import json
import os
import re

from ..services.safe_fetch import safe_get, validate_url


def _parse_txt(text: str) -> list:
    """TVBox txt 格式：分组名,#genre# 换行 频道名,url#线路"""
    groups, cur = [], None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '#genre#' in line:
            cur = {'name': line.split(',')[0].replace('#genre#', '').strip(), 'channels': []}
            if cur['name']:
                groups.append(cur)
            continue
        if cur is None:
            cur = {'name': '未分组', 'channels': []}
            groups.append(cur)
        if ',' in line:
            name, _, urls = line.partition(',')
            ch = {'name': name.strip(), 'urls': [u for u in urls.split('#') if u.strip().startswith('http')]}
            if ch['name'] and ch['urls']:
                cur['channels'].append(ch)
    return groups


def _parse_m3u(text: str) -> list:
    """M3U 格式：#EXTINF:-1 tvg-name group-title="分组",频道名 换行 url"""
    groups: dict = {}
    pending = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('#EXTINF'):
            gname = '未分组'
            m = re.search(r'group-title="([^"]*)"', line)
            if m and m.group(1).strip():
                gname = m.group(1).strip()
            name = line.split(',', 1)[1].strip() if ',' in line else ''
            pending = (gname, name)
        elif line and not line.startswith('#') and pending:
            gname, name = pending
            groups.setdefault(gname, []).append({'name': name or gname, 'urls': [line]})
            pending = None
    return [{'name': g, 'channels': chs} for g, chs in groups.items()]


def _parse_json(text: str) -> list:
    """FongMi live json：[{group:"分组",channels:[{name,urls:[]}]}]"""
    doc = json.loads(text)
    out = []
    for g in doc:
        chs = []
        for ch in g.get('channels') or []:
            urls = ch.get('urls') or []
            if ch.get('name') and urls:
                chs.append({'name': ch['name'], 'urls': urls[:5]})
        if chs:
            out.append({'name': g.get('group') or '未分组', 'channels': chs})
    return out


def preview_live(url: str, _allow_loopback: bool = False) -> dict:
    """抓取直播源并解析。返回 {format, groups, n_groups, n_channels, sample}"""
    if _allow_loopback:
        # 本机测试放行环回：临时移除 127.0.0.0/8 与 ::1 拦截（仅 validate_url 层面）
        import ipaddress as _ipa
        from ..services import safe_fetch as _sf
        saved = _sf.BLOCKED_NETS[:]
        _sf.BLOCKED_NETS[:] = [n for n in _sf.BLOCKED_NETS
                               if n not in (_ipa.ip_network('127.0.0.0/8'), _ipa.ip_network('::1/128'))]
        try:
            return _do_preview(url)
        finally:
            _sf.BLOCKED_NETS[:] = saved
    return _do_preview(url)


def _do_preview(url: str) -> dict:
    raw = safe_get(url, timeout=15.0)
    text = raw.decode('utf-8', errors='replace')
    fmt = 'unknown'
    if url.lower().endswith('.json') or text.lstrip().startswith(('[', '{')):
        fmt = 'json'
    elif text.lstrip().startswith('#EXTM3U'):
        fmt = 'm3u'
    elif '#genre#' in text:
        fmt = 'txt'
    if fmt == 'json':
        try:
            groups = _parse_json(text)
        except Exception:
            groups = _parse_txt(text)
    elif fmt == 'm3u':
        groups = _parse_m3u(text)
    else:
        groups = _parse_txt(text)
    n_ch = sum(len(g['channels']) for g in groups)
    sample = []
    for g in groups[:3]:
        sample.append({'group': g['name'], 'count': len(g['channels']),
                       'channels': [c['name'] for c in g['channels'][:4]]})
    return {'format': fmt, 'n_groups': len(groups), 'n_channels': n_ch, 'sample': sample}
