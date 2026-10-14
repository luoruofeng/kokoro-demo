"""Kokoro-82M 多语言 TTS 引擎。

模型与音色全部来自项目内的 models/Kokoro-82M 目录，推理过程完全离线：
KModel 直接从本地 config.json / kokoro-v1_0.pth 加载，音色直接读本地 voices/*.pt，
不会触发 huggingface_hub 下载。

对外只暴露一个 KokoroTTS 类：
    tts = KokoroTTS()
    tts.load()                       # 加载权重（约 3~6 秒）
    speech = tts.synthesize("你好", "z", voice="zf_xiaoxiao", speed=1.0)
    speech.audio                     # np.float32, 24kHz 单声道
"""
from __future__ import annotations

import io
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from languages import DEFAULT_VOICE, LANG_BY_CODE, LANG_NAMES, REPO_ID
from model_assets import CONFIG_NAME, WEIGHTS_NAME, default_model_dir
from model_assets import missing_assets as missing_assets_in

ROOT = Path(__file__).resolve().parent
MODEL_DIR = default_model_dir()
VOICE_DIR = MODEL_DIR / "voices"

SAMPLE_RATE = 24_000

# 分块拼接时插入的静音时长（秒）
CHUNK_GAP = 0.12


@dataclass
class Speech:
    """一次合成的结果。"""

    audio: np.ndarray
    sample_rate: int = SAMPLE_RATE
    phonemes: str = ""
    text: str = ""
    lang_code: str = "a"
    voice: str = ""
    speed: float = 1.0
    chunks: int = 0
    elapsed: float = 0.0
    phonemes_by_chunk: List[str] = field(default_factory=list)

    @property
    def seconds(self) -> float:
        return len(self.audio) / self.sample_rate

    @property
    def rtf(self) -> float:
        """实时率：合成 1 秒音频所需的秒数，越小越快。"""
        return self.elapsed / self.seconds if self.seconds else 0.0

    def to_wav_bytes(self, subtype: str = "PCM_16") -> bytes:
        import soundfile as sf

        buf = io.BytesIO()
        sf.write(buf, self.audio, self.sample_rate, format="WAV", subtype=subtype)
        return buf.getvalue()

    def save(self, path: str | Path) -> Path:
        import soundfile as sf

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(path, self.audio, self.sample_rate, subtype="PCM_16")
        return path


class KokoroTTS:
    """线程安全的 Kokoro-82M 推理封装（一个 KModel + 每种语言一个 KPipeline）。"""

    def __init__(self, model_dir: Path = MODEL_DIR, voice_dir: Path = VOICE_DIR, device: Optional[str] = None):
        self.model_dir = Path(model_dir)
        self.voice_dir = Path(voice_dir)
        self.device = device
        self._model = None
        self._pipelines: Dict[str, object] = {}
        self._lock = threading.RLock()
        self._load_lock = threading.Lock()
        self.loaded = False
        self.load_error: Optional[str] = None
        self.load_seconds: float = 0.0
        self.warmed_up = False
        # 加载进度回调：on_stage(str) -> None，供 Web 端展示“正在加载 xx”
        self.on_stage = None
        self.stage = "等待加载"

    def _stage(self, message: str) -> None:
        self.stage = message
        if self.on_stage:
            try:
                self.on_stage(message)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ 资源
    def missing_assets(self) -> List[str]:
        """返回缺失的模型文件（相对模型目录的路径，用于启动时给出友好提示）。"""
        return missing_assets_in(self.model_dir)

    def voice_ids(self, lang_code: str) -> List[str]:
        """磁盘上真实存在的、属于该语言的音色 id。"""
        if not self.voice_dir.is_dir():
            return []
        prefix = lang_code
        return sorted(p.stem for p in self.voice_dir.glob(f"{prefix}*.pt") if p.stem[1] in "fm")

    def voice_path(self, voice: str, lang_code: str) -> Path:
        """把音色 id 或文件名解析成磁盘路径。"""
        name = Path(voice).name
        if not name.endswith(".pt"):
            name += ".pt"
        path = self.voice_dir / name
        if not path.is_file():
            fallback = DEFAULT_VOICE.get(lang_code)
            if fallback and (self.voice_dir / f"{fallback}.pt").is_file():
                return self.voice_dir / f"{fallback}.pt"
            raise FileNotFoundError(f"音色文件不存在: {path}")
        return path

    def default_voice(self, lang_code: str) -> str:
        wanted = DEFAULT_VOICE.get(lang_code)
        available = self.voice_ids(lang_code)
        if wanted in available:
            return wanted
        return available[0] if available else ""

    # ------------------------------------------------------------------ 加载
    def load(self) -> "KokoroTTS":
        """加载权重并预热所有语言的 pipeline（多次调用只生效一次）。"""
        with self._load_lock:
            if self.loaded:
                return self
            started = time.perf_counter()
            missing = self.missing_assets()
            if missing:
                self.load_error = (
                    "缺少模型文件：" + "、".join(missing[:5])
                    + ("…" if len(missing) > 5 else "")
                    + "。启动 server.py / cli.py 时会自动下载（联网即可），"
                    "也可以手动执行：python scripts/download_model.py"
                )
                raise FileNotFoundError(self.load_error)

            import torch
            from kokoro import KModel

            torch.set_num_threads(max(1, os.cpu_count() or 4))
            device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")

            self._stage(f"读取权重 {WEIGHTS_NAME}（约 312 MB）...")
            model = KModel(
                repo_id=REPO_ID,  # 仅用于记录来源，实际从本地文件加载
                config=str(self.model_dir / CONFIG_NAME),
                model=str(self.model_dir / WEIGHTS_NAME),
            )
            self._model = model.to(device).eval()
            self.device = device

            total = len(LANG_BY_CODE)
            for index, code in enumerate(LANG_BY_CODE, start=1):
                self._stage(f"初始化 {LANG_NAMES[code]} 前端 ({index}/{total}) ...")
                self._build_pipeline(code)

            self.loaded = True
            self.load_seconds = time.perf_counter() - started
            self._stage("就绪")
            return self

    def _build_pipeline(self, lang_code: str):
        """按语言构建 KPipeline；模型实例在所有 pipeline 间复用。"""
        from kokoro import KPipeline

        if lang_code in self._pipelines:
            return self._pipelines[lang_code]
        pipeline = KPipeline(
            lang_code=lang_code,
            repo_id=REPO_ID,  # 决定中文 G2P 用 v1.0 还是 v1.1 词表
            model=self._model,
        )
        self._pipelines[lang_code] = pipeline
        return pipeline

    def warm_up(self) -> None:
        """跑一小段合成，避免首次点击时卡顿。"""
        if self.warmed_up or not self.loaded:
            return
        try:
            self.synthesize("Hello.", "a", voice=self.default_voice("a"), speed=1.0)
            self.warmed_up = True
        except Exception:  # noqa: BLE001 - 预热失败不影响主流程
            pass

    # ------------------------------------------------------------------ 推理
    def synthesize(
        self,
        text: str,
        lang_code: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> Speech:
        """合成一段文本，返回 24kHz 单声道 float32 音频。"""
        text = (text or "").strip()
        if not text:
            raise ValueError("文本不能为空")
        if lang_code not in LANG_BY_CODE:
            raise ValueError(f"不支持的语言代码: {lang_code}（支持 {','.join(LANG_BY_CODE)}）")
        if not self.loaded:
            self.load()

        speed = float(min(max(speed, 0.4), 2.0))
        voice = voice or self.default_voice(lang_code)
        voice_path = self.voice_path(voice, lang_code)

        import torch

        with self._lock:  # torch 模型串行推理，避免多请求互相抢占
            pipeline = self._pipelines[lang_code]
            started = time.perf_counter()
            pieces: List[np.ndarray] = []
            phonemes_by_chunk: List[str] = []
            for result in pipeline(text, voice=str(voice_path), speed=speed):
                audio = result.audio
                if audio is None:
                    continue
                if result.phonemes:
                    phonemes_by_chunk.append(result.phonemes)
                piece = audio.detach().cpu().to(torch.float32).numpy().reshape(-1)
                if piece.size:
                    pieces.append(piece)
            elapsed = time.perf_counter() - started

        if not pieces:
            raise RuntimeError("合成失败：没有得到音频数据（文本可能不含可发音内容）")

        gap = np.zeros(int(SAMPLE_RATE * CHUNK_GAP), dtype=np.float32)
        merged: List[np.ndarray] = []
        for i, piece in enumerate(pieces):
            if i:
                merged.append(gap)
            merged.append(piece)
        audio = np.concatenate(merged)
        audio = np.clip(audio, -1.0, 1.0).astype(np.float32)

        return Speech(
            audio=audio,
            phonemes=" ".join(phonemes_by_chunk),
            phonemes_by_chunk=phonemes_by_chunk,
            text=text,
            lang_code=lang_code,
            voice=voice,
            speed=speed,
            chunks=len(pieces),
            elapsed=elapsed,
        )

    # ------------------------------------------------------------------ 目录
    def catalog(self) -> List[dict]:
        """给前端用的语言/音色清单，只保留磁盘上存在的音色。"""
        result = []
        for code, meta in LANG_BY_CODE.items():
            existing = set(self.voice_ids(code))
            voices = [
                {
                    "id": vid,
                    "name": name,
                    "gender": gender,
                    "grade": grade,
                    "note": note,
                }
                for vid, name, gender, grade, note in meta["voices"]
                if vid in existing
            ] or [
                {"id": vid, "name": name, "gender": gender, "grade": grade, "note": note}
                for vid, name, gender, grade, note in meta["voices"]
            ]
            result.append(
                {
                    "code": code,
                    "name": meta["name"],
                    "english": meta["english"],
                    "flag": meta["flag"],
                    "speech": meta["speech"],
                    "g2p": meta["g2p"],
                    "tip": meta["tip"],
                    "voices": voices,
                    "default_voice": self.default_voice(code) or voices[0]["id"],
                    "samples": meta["samples"],
                }
            )
        return result

    def describe(self) -> dict:
        return {
            "repo_id": REPO_ID,
            "model_dir": str(self.model_dir),
            "sample_rate": SAMPLE_RATE,
            "device": self.device or "cpu",
            "loaded": self.loaded,
            "warmed_up": self.warmed_up,
            "load_seconds": round(self.load_seconds, 2),
            "languages": len(LANG_BY_CODE),
            "voices": sum(len(self.voice_ids(c)) for c in LANG_BY_CODE),
            "language_names": LANG_NAMES,
            "error": self.load_error,
        }


_ENGINE: Optional[KokoroTTS] = None
_ENGINE_LOCK = threading.Lock()


def get_engine() -> KokoroTTS:
    """进程内单例，供 Web 服务与 CLI 共用。"""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = KokoroTTS()
        return _ENGINE
