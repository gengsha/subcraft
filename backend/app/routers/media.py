"""媒体相关：视频探测、带 Range 的视频流播放、字体枚举。"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from ..models import MediaInfo
from ..services import ffmpeg_tool, fonts

router = APIRouter(prefix="/api/media", tags=["media"])


@router.post("/probe", response_model=MediaInfo)
def probe(body: dict) -> MediaInfo:
    path = body.get("path", "")
    if not path or not Path(path).exists():
        raise HTTPException(404, "文件不存在")
    return ffmpeg_tool.probe(path)


@router.get("/stream")
def stream(request: Request, path: str = Query(...)):
    """支持 Range 的视频流，供 <video> 播放与拖动。"""
    file = Path(path)
    if not file.exists():
        raise HTTPException(404, "文件不存在")
    file_size = file.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(file)

    # 解析 "bytes=start-end"
    try:
        unit, rng = range_header.split("=")
        start_s, end_s = rng.split("-")
        start = int(start_s) if start_s else 0
        end = int(end_s) if end_s else file_size - 1
    except ValueError:
        raise HTTPException(416, "Range 无效")
    end = min(end, file_size - 1)
    length = end - start + 1

    def iter_file():
        with open(file, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(1 << 20, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    suffix = file.suffix.lower()
    mime = {
        ".mp4": "video/mp4", ".mkv": "video/x-matroska", ".webm": "video/webm",
        ".mov": "video/quicktime", ".avi": "video/x-msvideo", ".ts": "video/mp2t",
    }.get(suffix, "application/octet-stream")
    return StreamingResponse(
        iter_file(),
        status_code=206,
        media_type=mime,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(length),
        },
    )


@router.get("/fonts")
def get_fonts() -> dict[str, str]:
    return fonts.list_fonts()


@router.get("/fonts/file")
def get_font_file(family: str = Query(...)):
    p = fonts.font_file(family)
    if not p:
        raise HTTPException(404, "字体不存在")
    return FileResponse(p)
