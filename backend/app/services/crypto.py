"""FongMi TV 2423 加密格式编解码。

格式（data 为纯 hex 文本串）:
    data = "2423" + hex(key_utf8) + "2324" + ct_hex + hex(iv13_text)

Java 端 Decoder.cbc 解密逻辑 (FongMi-TV/app/.../api/Decoder.java:56):
    decode = new String(hex2byte(data), UTF_8).toLowerCase()   # 注意整体小写
    key    = padEnd(decode[indexOf("$#")+2 : indexOf("#$")])   # 右补 '0' 到 16 字节
    iv     = padEnd(decode[decode.length()-13:])               # 右补 '0' 到 16 字节
    ct     = hex2byte(data[indexOf("2324")+4 : data.length()-26])
    -> AES-128-CBC / PKCS5Padding

要点:
- Java 把 dec 全部 toLowerCase，因此实际 AES key = key文本.lower()；
  iv13 必须由小写 hex 字符组成（os.urandom().hex() 天然满足）。
- 约束: "2423"+hex(key) 前缀内不得出现 "2324"（含边界重叠，即 hex(key)
  不得含 "2324"、不得以 "23" 结尾、PREFIX+keyhex 不得含 "2324"），
  否则 Java 的 indexOf("2324") 会命中错误位置。
- key 文本不得包含 "$#" 或 "#$"（会让 indexOf("#$") 提前命中）。
- ct 尾部与 iv13 之间无歧义：iv13 为 ASCII hex 文本，UTF-8 自同步。
"""
from __future__ import annotations

import os

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

PREFIX = "2423"  # hex("$#")
SEP = "2324"     # hex("#$")


def _pad_end(s: str) -> bytes:
    """按字节右补 '0' 到 16 字节（Java padEnd 是字符级但 key<=16字节时等价；
    这里按字节处理以正确支持多字节 key 字符）。"""
    b = s.encode("utf-8")
    if len(b) > 16:
        raise ValueError("key/iv 超过 16 字节")
    return b + b"0" * (16 - len(b))


def validate_key(key: str) -> bytes:
    """校验 key 并返回实际参与 AES 的小写 key 字节。"""
    eff = key.lower()
    kb = eff.encode("utf-8")
    if not 1 <= len(kb) <= 16:
        raise ValueError("key 小写后必须 1~16 字节（UTF-8）")
    if "$#" in eff or "#$" in eff:
        raise ValueError('key 文本不得包含 "$#" 或 "#$" 分隔符序列')
    header = PREFIX + kb.hex()
    if SEP in header or (header + SEP[0]).count(SEP) > 0 or header.endswith("23"):
        raise ValueError('key 的 hex 表示与分隔符边界冲突（含 "2324" 或以 "23" 结尾），请换 key')
    return kb


def fongmi_encode(doc_text: str, key: str) -> str:
    """将明文 JSON 加密为 2423 格式 hex 文本。"""
    kb = validate_key(key)
    iv13 = os.urandom(6).hex() + "0"  # 13 个小写 hex 字符
    cipher = AES.new(_pad_end(kb.decode("utf-8")), AES.MODE_CBC, _pad_end(iv13))
    ct = cipher.encrypt(pad(doc_text.encode("utf-8"), 16))
    return PREFIX + kb.hex().upper() + SEP + ct.hex().upper() + iv13.encode().hex().upper()


def fongmi_decode(data: str) -> str:
    """按 Java Decoder.cbc 的切片逻辑解密 2423 格式文本（镜像实现）。"""
    data = "".join(data.split())  # 去所有空白
    if not data.startswith(PREFIX):
        raise ValueError("不是 2423 格式")
    raw = bytes.fromhex(data)
    dec = raw.decode("utf-8", errors="replace").lower()
    sep_pos = dec.find("#$")
    if sep_pos < 0:
        raise ValueError("缺少 #$ 分隔符")
    key = _pad_end(dec[2:sep_pos]).decode("utf-8")
    iv13 = dec[-13:]
    ct = bytes.fromhex(data[data.find(SEP) + 4: len(data) - 26])
    pt = unpad(AES.new(key.encode("utf-8"), AES.MODE_CBC, _pad_end(iv13)).decrypt(ct), 16)
    return pt.decode("utf-8")


def fongmi_roundtrip_ok(doc_text: str, key: str) -> bool:
    try:
        return fongmi_decode(fongmi_encode(doc_text, key)) == doc_text
    except Exception:
        return False
