"""安全远程拉取工具：SSRF 防护 + 大小限制（审查项 M11）"""
import ipaddress
import socket
from urllib.parse import urlparse

import httpx

MAX_FETCH_SIZE = 100 * 1024 * 1024  # 100MB，与 upload 一致
BLOCKED_NETS = [
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
              "169.254.0.0/16", "0.0.0.0/8", "100.64.0.0/10", "::1/128",
              "fc00::/7", "fe80::/10")
]


def _check_host(host: str):
    """拒绝私网/环回/链路本地地址（云元数据 169.254.169.254 一并拦截）"""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError(f"域名无法解析: {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        for net in BLOCKED_NETS:
            if ip in net:
                raise ValueError(f"禁止访问内网地址: {ip}")


def validate_url(url: str) -> str:
    """校验目标 URL：仅 http(s)、拒绝内网。返回规范 url，不合法抛 ValueError。"""
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("仅支持 http/https")
    if not u.hostname:
        raise ValueError("URL 缺少主机名")
    _check_host(u.hostname)
    return url


def _client(*, timeout: float) -> httpx.Client:
    """带重定向逐跳校验的 httpx 客户端：每一跳目标都必须通过 validate_url，
    防 302 跳转内网（redirect SSRF bypass）。"""
    client = httpx.Client(follow_redirects=True, timeout=timeout)
    orig = client._send_handling_redirects

    def _guarded(request, **kw):
        validate_url(str(request.url))
        return orig(request, **kw)

    client._send_handling_redirects = _guarded
    return client


def safe_get(url: str, timeout: float = 30.0, headers: dict | None = None) -> bytes:
    """SSRF 防护的远程拉取：校验目标 → 流式下载限长。超限抛 ValueError。"""
    validate_url(url)
    with _client(timeout=timeout) as client:
        with client.stream("GET", url, headers=headers) as resp:
            resp.raise_for_status()
            chunks = []
            total = 0
            for chunk in resp.iter_bytes(65536):
                total += len(chunk)
                if total > MAX_FETCH_SIZE:
                    raise ValueError(f"文件超过大小限制 {MAX_FETCH_SIZE // (1024*1024)}MB")
                chunks.append(chunk)
            return b"".join(chunks)
