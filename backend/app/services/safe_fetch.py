"""安全远程拉取工具：SSRF 防护 + 大小限制（审查项 M11）"""
import ipaddress
import socket
import ssl
from urllib.parse import urlparse

import httpx

MAX_FETCH_SIZE = 100 * 1024 * 1024  # 100MB，与 upload 一致

# TVBox / OK影视 生态常用 UA：不少源站/接口会校验 UA，
# httpx 默认的 python-httpx UA 会被 403，因此默认伪装 okhttp，并支持自动嗅探回退。
DEFAULT_UA = "okhttp/3.12.13"
UA_CANDIDATES = [
    "okhttp/3.12.13",
    "okhttp/3.12.0",
    "okhttp/4.12.0",
    "okhttp/4.9.3",
    "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Mobile Safari/537.36",
    "TVBox",
]
# 这些状态码可能是「UA 不对」导致，值得换 UA 重试
_SNIFF_STATUS = {401, 403, 406, 412, 451}

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


def _client(*, timeout: float, verify: bool = True) -> httpx.Client:
    """带重定向逐跳校验的 httpx 客户端：每一跳目标都必须通过 validate_url，
    防 302 跳转内网（redirect SSRF bypass）。"""
    client = httpx.Client(follow_redirects=True, timeout=timeout, verify=verify)
    orig = client._send_handling_redirects

    def _guarded(request, **kw):
        validate_url(str(request.url))
        return orig(request, **kw)

    client._send_handling_redirects = _guarded
    return client


def _get_once(url: str, timeout: float, headers: dict, verify: bool = True) -> bytes:
    with _client(timeout=timeout, verify=verify) as client:
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


def _is_cert_error(e: BaseException) -> bool:
    """证书校验类错误（自签/过期/链不全），用于决定是否降级重试"""
    seen = f"{type(e).__name__}: {e}"
    if "CERTIFICATE_VERIFY_FAILED" in seen or "SSLCertVerificationError" in seen:
        return True
    cause = getattr(e, "__cause__", None)
    return isinstance(cause, ssl.SSLCertVerificationError) or (
        cause is not None and "CERTIFICATE_VERIFY_FAILED" in str(cause))


def _get_with_tls_fallback(url: str, timeout: float, headers: dict) -> bytes:
    """证书校验失败时降级为不校验证书重试一次。

    理由：TVBox/OK影视 客户端的 catvod OkHttp 就是 trustAll（hostnameVerifier 恒真 +
    trustAllCertificates），源站自签/过期证书极常见。后端预览若不降级，会把
    「手机端其实能正常播放」的源误报为不可达。网络类错误（连不上/超时）不降级。
    """
    try:
        return _get_once(url, timeout, headers, verify=True)
    except Exception as e:
        if _is_cert_error(e):
            return _get_once(url, timeout, headers, verify=False)
        raise


def safe_get(url: str, timeout: float = 30.0, headers: dict | None = None,
             sniff_ua: bool = True) -> bytes:
    """SSRF 防护的远程拉取：校验目标 → 流式下载限长。超限抛 ValueError。

    默认带 okhttp UA；若被 401/403/406/412/451 拒绝或返回空，则依次换候选 UA 重试
    （部分源站/接口会校验 User-Agent）。调用方显式传 User-Agent 或 sniff_ua=False
    时不嗅探，完全按调用方给的来。
    """
    validate_url(url)
    base = dict(headers or {})
    explicit = any(k.lower() == "user-agent" for k in base)
    if explicit or not sniff_ua:
        return _get_with_tls_fallback(url, timeout, base)

    last: Exception | None = None
    for i, ua in enumerate(UA_CANDIDATES):
        h = dict(base)
        h["User-Agent"] = ua
        try:
            data = _get_with_tls_fallback(url, timeout, h)
        except httpx.HTTPStatusError as e:
            last = e
            if e.response.status_code not in _SNIFF_STATUS:
                raise
            continue
        if data:
            return data
        last = ValueError(f"拉取为空（UA={ua}）")
    assert last is not None
    raise last
