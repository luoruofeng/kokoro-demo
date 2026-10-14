"""Kokoro-82M 多语言 TTS 播放效果 Demo —— Web 服务。

启动：  python server.py            （默认 http://127.0.0.1:8000）
        python server.py --port 8080 --open

启动流程（全自动，无需手动准备模型）：
    1. 检查 models/Kokoro-82M 下的 config / 权重 / 54 个音色；
    2. 缺什么就从 ModelScope（失败回退 HuggingFace）自动下载，进度推到前端；
    3. 下载完成立刻加载模型并预热，前端通过 /api/status 轮询进度。

不想自动下载（离线/已有本地模型）时加 --no-download。
"""
from __future__ import annotations

import argparse
import base64
import json
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kokoro_tts import get_engine
from languages import LANG_BY_CODE, LANG_NAMES, REPO_ID
from model_assets import Progress, default_model_dir, disk_usage, ensure_assets, human

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
OUTPUT_DIR = ROOT / "outputs"
INDEX_FILE = OUTPUT_DIR / "_index.json"

STATE_LOCK = threading.Lock()
STATE = {
    "state": "loading",  # loading | downloading | ready | error
    "message": "准备检查模型文件 ...",
    "error": None,
    "started": time.time(),
    "download": None,  # 自动下载时的进度详情，见 on_download()
}

# 由 main() 根据 --no-download 设置
AUTO_DOWNLOAD = True
DOWNLOAD_SOURCE = "auto"

HISTORY: List[dict] = []


# --------------------------------------------------------------------- 历史记录
def load_history() -> None:
    global HISTORY
    if INDEX_FILE.is_file():
        try:
            HISTORY = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            HISTORY = []
    for item in HISTORY:
        item["exists"] = (OUTPUT_DIR / item["file"]).is_file()
    HISTORY = [h for h in HISTORY if h.get("exists")]


def add_history(entry: dict, keep: int = 60) -> None:
    HISTORY.insert(0, entry)
    del HISTORY[keep:]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(HISTORY, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------- 模型加载
def on_download(event: Progress) -> None:
    """把自动下载进度写进 STATE，前端轮询 /api/status 展示。"""
    with STATE_LOCK:
        if event.message:
            STATE["message"] = event.message
        if event.stage in ("check", "download"):
            STATE["state"] = "downloading"
        STATE["download"] = {
            "stage": event.stage,
            "text": event.text,
            "file": event.file,
            "files_done": event.file_index,
            "files_total": event.files_total,
            "percent": round(event.percent, 1),
            "overall_percent": round(event.overall_percent, 1),
            "bytes_done": event.bytes_done,
            "bytes_total": event.bytes_total,
            "bytes_written": event.bytes_written,
            "speed": round(event.speed, 1),
        }


def prepare_assets() -> None:
    """检查并按需自动下载模型文件；失败时抛出带排查建议的异常。"""
    model_dir = default_model_dir()
    report = ensure_assets(
        model_dir=model_dir,
        source=DOWNLOAD_SOURCE,
        allow_download=AUTO_DOWNLOAD,
        on_progress=on_download,
    )
    with STATE_LOCK:
        STATE["download"] = None
    if not report.verified:
        raise RuntimeError(report.error or f"模型文件不完整：{report.missing_after[:3]}")
    if report.needed_download:
        print(f"[模型] {report.summary()}", flush=True)


def load_engine_background() -> None:
    engine = get_engine()
    engine.on_stage = lambda message: STATE.update(message=message)
    try:
        prepare_assets()
        with STATE_LOCK:
            STATE.update(state="loading", message="模型文件就绪，正在加载引擎 ...")
        engine.load()
        STATE.update(state="loading", message="预热中，请稍候 ...")
        engine.warm_up()
        with STATE_LOCK:
            STATE.update(
                state="ready",
                message=f"引擎就绪（{len(LANG_BY_CODE)} 种语言）",
                download=None,
            )
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        if not AUTO_DOWNLOAD:
            message += "（当前以 --no-download 启动，已禁用自动下载）"
        with STATE_LOCK:
            STATE.update(state="error", message=message, error=message, download=None)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时准备输出目录、读取历史记录，并在后台线程加载模型。"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    load_history()
    threading.Thread(target=load_engine_background, name="kokoro-loader", daemon=True).start()
    yield


app = FastAPI(title="Kokoro-82M 多语言 TTS Demo", version="1.0", lifespan=lifespan)


# --------------------------------------------------------------------- 数据模型
class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    lang: str = "z"
    voice: Optional[str] = None
    speed: float = Field(1.0, ge=0.4, le=2.0)
    save: bool = True


class CompareRequest(BaseModel):
    sample_index: int = Field(0, ge=0, le=9)
    speed: float = Field(1.0, ge=0.4, le=2.0)
    langs: Optional[List[str]] = None
    text: Optional[str] = None  # 传入则所有语言都读这段文本


# --------------------------------------------------------------------- 接口
@app.get("/api/status")
def api_status():
    with STATE_LOCK:
        state = dict(STATE)
    engine = get_engine()
    state.update(
        {
            "stage": engine.stage,
            "load_seconds": round(engine.load_seconds, 2),
            "device": engine.device or "cpu",
            "model_dir": str(engine.model_dir),
            "auto_download": AUTO_DOWNLOAD,
        }
    )
    # 加载/下载期间顺带汇报磁盘上的模型文件情况，便于前端提示
    if state["state"] != "ready":
        usage = disk_usage(engine.model_dir)
        state["assets"] = {
            "files_present": usage["files_present"],
            "files_expected": usage["files_expected"],
            "voices_present": usage["voices_present"],
            "voices_expected": usage["voices_expected"],
            "human_size": human(usage["bytes"]),
            "missing": len(usage["missing"]),
        }
    return state


@app.get("/api/catalog")
def api_catalog():
    engine = get_engine()
    with STATE_LOCK:
        state = STATE["state"]
    return {
        "ready": state == "ready",
        "engine": engine.describe(),
        "repo_id": REPO_ID,
        "languages": engine.catalog(),
    }


@app.post("/api/tts")
def api_tts(req: TTSRequest):
    if req.lang not in LANG_BY_CODE:
        raise HTTPException(400, f"不支持的语言代码: {req.lang}")
    engine = get_engine()
    try:
        speech = engine.synthesize(req.text, req.lang, voice=req.voice, speed=req.speed)
    except FileNotFoundError as exc:
        raise HTTPException(500, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"合成失败: {exc}") from exc

    file_url = None
    if req.save:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"kokoro_{stamp}_{req.lang}_{speech.voice}.wav"
        speech.save(OUTPUT_DIR / name)
        file_url = f"/outputs/{name}"
        add_history(
            {
                "file": name,
                "url": file_url,
                "lang": req.lang,
                "lang_name": LANG_BY_CODE[req.lang]["name"],
                "flag": LANG_BY_CODE[req.lang]["flag"],
                "voice": speech.voice,
                "text": req.text,
                "seconds": round(speech.seconds, 2),
                "rtf": round(speech.rtf, 3),
                "speed": speech.speed,
                "created": stamp,
            }
        )

    wav = speech.to_wav_bytes()
    return {
        "ok": True,
        "audio": "data:audio/wav;base64," + base64.b64encode(wav).decode("ascii"),
        "url": file_url,
        "lang": req.lang,
        "lang_name": LANG_BY_CODE[req.lang]["name"],
        "voice": speech.voice,
        "speed": speech.speed,
        "seconds": round(speech.seconds, 2),
        "elapsed": round(speech.elapsed, 2),
        "rtf": round(speech.rtf, 3),
        "chunks": speech.chunks,
        "phonemes": speech.phonemes,
        "bytes": len(wav),
    }


@app.post("/api/compare")
def api_compare(req: CompareRequest):
    """用每种语言各自的示例文案合成，用于一次性对比所有语言的播放效果。"""
    engine = get_engine()
    langs = [c for c in (req.langs or list(LANG_BY_CODE)) if c in LANG_BY_CODE]
    results = []
    for code in langs:
        samples = LANG_BY_CODE[code]["samples"]
        text = (req.text or "").strip() or samples[min(req.sample_index, len(samples) - 1)]
        try:
            speech = engine.synthesize(text, code, speed=req.speed)
        except Exception as exc:  # noqa: BLE001
            results.append({"lang": code, "lang_name": LANG_BY_CODE[code]["name"], "ok": False, "error": str(exc)})
            continue
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"compare_{stamp}_{code}_{speech.voice}.wav"
        speech.save(OUTPUT_DIR / name)
        file_url = f"/outputs/{name}"
        add_history(
            {
                "file": name,
                "url": file_url,
                "lang": code,
                "lang_name": LANG_BY_CODE[code]["name"],
                "flag": LANG_BY_CODE[code]["flag"],
                "voice": speech.voice,
                "text": text,
                "seconds": round(speech.seconds, 2),
                "rtf": round(speech.rtf, 3),
                "speed": speech.speed,
                "created": stamp,
            }
        )
        results.append(
            {
                "ok": True,
                "lang": code,
                "lang_name": LANG_BY_CODE[code]["name"],
                "english": LANG_BY_CODE[code]["english"],
                "flag": LANG_BY_CODE[code]["flag"],
                "voice": speech.voice,
                "text": text,
                "url": file_url,
                "audio": "data:audio/wav;base64," + base64.b64encode(speech.to_wav_bytes()).decode("ascii"),
                "seconds": round(speech.seconds, 2),
                "elapsed": round(speech.elapsed, 2),
                "rtf": round(speech.rtf, 3),
            }
        )
    return {"ok": True, "count": len(results), "results": results}


@app.get("/api/history")
def api_history():
    for item in HISTORY:
        item["exists"] = (OUTPUT_DIR / item["file"]).is_file()
    return {"items": [h for h in HISTORY if h.get("exists")]}


@app.delete("/api/history")
def api_history_clear():
    for path in OUTPUT_DIR.glob("*.wav"):
        try:
            path.unlink()
        except OSError:
            pass
    HISTORY.clear()
    INDEX_FILE.write_text("[]", encoding="utf-8")
    return {"ok": True, "cleared": True}


@app.get("/api/languages")
def api_languages():
    return {"names": LANG_NAMES, "count": len(LANG_NAMES)}


# --------------------------------------------------------------------- 静态资源
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/outputs", StaticFiles(directory=str(OUTPUT_DIR)), name="outputs")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.ico")
def favicon():
    icon = STATIC_DIR / "favicon.svg"
    if icon.is_file():
        return FileResponse(icon, media_type="image/svg+xml")
    return JSONResponse({}, status_code=204)


def main() -> None:
    global AUTO_DOWNLOAD, DOWNLOAD_SOURCE

    parser = argparse.ArgumentParser(description="Kokoro-82M 多语言 TTS Demo")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="缺少模型文件时不自动下载（离线使用或已有本地模型）",
    )
    parser.add_argument(
        "--source",
        choices=("auto", "modelscope", "hf"),
        default="auto",
        help="模型下载源，默认 auto（ModelScope 优先，失败回退 HuggingFace）",
    )
    args = parser.parse_args()

    AUTO_DOWNLOAD = not args.no_download
    DOWNLOAD_SOURCE = args.source

    usage = disk_usage()
    if usage["ready"]:
        print(f"[模型] 已就绪：{usage['files_present']} 个文件，{human(usage['bytes'])}", flush=True)
    elif AUTO_DOWNLOAD:
        print(
            f"[模型] 缺少 {len(usage['missing'])} 个文件，启动后自动下载（源：{args.source}）",
            flush=True,
        )
    else:
        print(
            f"[模型] 缺少 {len(usage['missing'])} 个文件，且已禁用自动下载；"
            "请先运行 python scripts/download_model.py",
            flush=True,
        )

    if args.open:
        threading.Timer(1.2, lambda: webbrowser.open(f"http://{args.host}:{args.port}")).start()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
