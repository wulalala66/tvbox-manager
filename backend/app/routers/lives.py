"""路由：直播源管理——FongMi live.json 解析/抓取 + 分组频道预览

能力：
- POST /lives/parse：解析粘贴的 live 文本（txt/m3u/FongMi json 三格式），返回分组结构（不落库）
- POST /lives/fetch：从 url 拉取并解析（SSRF 防护走 safe_get）
- 解析结果可直接在方案页 lives 结构化编辑中引用 url，发布时并入 global_fields.lives
"""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.live_preview import _parse_txt, _parse_m3u, _parse_json

router = APIRouter(prefix="/lives", tags=["lives"])


class LiveTextIn(BaseModel):
    text: str


class LiveUrlIn(BaseModel):
    url: str


def _stats(groups: list) -> dict:
    n_ch = sum(len(g["channels"]) for g in groups)
    sample = [{"group": g["name"], "count": len(g["channels"]),
               "channels": [c["name"] for c in g["channels"][:4]]} for g in groups[:3]]
    return {"ok": True, "n_groups": len(groups), "n_channels": n_ch, "sample": sample}


@router.post("/parse")
def parse_live_text(body: LiveTextIn):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "内容为空")
    fmt, groups = None, None
    errs = []
    for fn, fmt_name in ((_parse_json, "json"), (_parse_m3u, "m3u"), (_parse_txt, "txt")):
        try:
            g = fn(text)
            if g:
                fmt, groups = fmt_name, g
                break
        except Exception as e:
            errs.append(f"{fmt_name}: {type(e).__name__}")
    if groups is None:
        raise HTTPException(400, "无法识别格式（尝试过 json/m3u/txt）：" + "; ".join(errs))
    return {"format": fmt, **_stats(groups), "groups": groups}


@router.post("/fetch")
def fetch_live(body: LiveUrlIn):
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(400, "缺少 url")
    from ..services.live_preview import preview_live
    try:
        import os
        allow_lb = os.environ.get("DSH_ALLOW_LOOPBACK_PREVIEW") == "1"
        r = preview_live(url, _allow_loopback=allow_lb)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"{type(e).__name__}: {e}")
    r["groups"] = r.pop("groups", [])
    return r
