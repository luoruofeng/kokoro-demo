"""Kokoro-82M 模型资源清单 + 自动检查 / 自动下载。

项目从 GitHub 克隆下来时**不含**权重（约 330 MB，见 .gitignore），
这里集中提供三个能力，供 run.ps1 / server.py / cli.py 复用：

    is_ready()            # 检查 config.json + 权重 + 全部音色是否齐全
    missing_assets()      # 返回缺失/被截断的文件（相对路径）
    ensure_assets()       # 缺什么下什么；已存在的按大小校验后跳过

下载默认走 ModelScope（国内直连快），失败自动回退 HuggingFace；
支持断点/续传语义：只有大小与远端一致的文件才会被跳过。

命令行入口见 scripts/download_model.py。
"""
from __future__ import annotations

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from languages import LANG_BY_CODE, REPO_ID

# --------------------------------------------------------------------- 常量
ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL_DIR = ROOT / "models" / "Kokoro-82M"

CONFIG_NAME = "config.json"
WEIGHTS_NAME = "kokoro-v1_0.pth"
VOICES_DIR = "voices"
VOICE_EXT = ".pt"
DOC_FILES = ("VOICES.md", "README.md", "SAMPLES.md")

# 判定“文件完整”的最小体积，用来识别下载被中断而留下的半个文件
MIN_BYTES: Dict[str, int] = {
    CONFIG_NAME: 256,
    WEIGHTS_NAME: 100 * 1024 * 1024,  # 实际约 312 MB
}
DEFAULT_MIN_BYTES = 1024  # 音色/文档

MODELSCOPE_API = "https://www.modelscope.cn/api/v1/models/{repo}/repo/files"
MODELSCOPE_RAW = "https://www.modelscope.cn/api/v1/models/{repo}/repo"
HF_API = "https://huggingface.co/api/models/{repo}/tree/main"
HF_RAW = "https://huggingface.co/{repo}/resolve/main/{path}"

CHUNK = 1 << 18  # 256 KiB
UA = {"User-Agent": "kokoro-demo/1.0"}
SOURCES = ("modelscope", "hf")
SOURCE_LABEL = {"modelscope": "ModelScope", "hf": "HuggingFace"}


# --------------------------------------------------------------------- 工具
def human(n: float) -> str:
    """字节数转可读文本。"""
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}GB"


def default_model_dir() -> Path:
    """模型目录，可用环境变量 KOKORO_MODEL_DIR 覆盖。"""
    env = os.environ.get("KOKORO_MODEL_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_MODEL_DIR


# --------------------------------------------------------------------- 清单
@dataclass(frozen=True)
class Asset:
    """一个需要落地的文件。"""

    path: str  # 相对模型目录的路径，如 voices/af_heart.pt
    min_bytes: int
    category: str  # core | voices | docs

    def local(self, model_dir: Path) -> Path:
        return Path(model_dir) / self.path


def voice_files() -> List[str]:
    """清单里出现的全部音色文件（相对路径），顺序稳定。"""
    files: List[str] = []
    for meta in LANG_BY_CODE.values():
        for entry in meta["voices"]:
            files.append(f"{VOICES_DIR}/{entry[0]}{VOICE_EXT}")
    return files


def assets(include_docs: bool = True, only_core: bool = False) -> List[Asset]:
    """返回需要下载的全部资源。

    include_docs=False 时只保留跑推理必须的文件（config + 权重 + 音色）。
    """
    result = [
        Asset(CONFIG_NAME, MIN_BYTES.get(CONFIG_NAME, DEFAULT_MIN_BYTES), "core"),
        Asset(WEIGHTS_NAME, MIN_BYTES.get(WEIGHTS_NAME, DEFAULT_MIN_BYTES), "core"),
    ]
    if not only_core:
        result += [
            Asset(path, DEFAULT_MIN_BYTES, "voices") for path in voice_files()
        ]
    if include_docs and not only_core:
        result += [Asset(path, 64, "docs") for path in DOC_FILES]
    return result


def _intact(asset: Asset, model_dir: Path) -> bool:
    path = asset.local(model_dir)
    if not path.is_file():
        return False
    if asset.min_bytes <= 0:
        return True
    return path.stat().st_size >= asset.min_bytes


def missing_assets(
    model_dir: Optional[Path] = None,
    include_docs: bool = False,
    only_core: bool = False,
) -> List[str]:
    """返回缺失或体积异常的文件的相对路径（include_docs 默认 False）。"""
    model_dir = Path(model_dir) if model_dir else default_model_dir()
    return [
        a.path
        for a in assets(include_docs=include_docs, only_core=only_core)
        if not _intact(a, model_dir)
    ]


def is_ready(model_dir: Optional[Path] = None) -> bool:
    """推理所需文件是否齐全（doc 不算）。"""
    return not missing_assets(model_dir)


def disk_usage(model_dir: Optional[Path] = None) -> dict:
    """已落地的文件统计，供状态接口与 --check 使用。"""
    model_dir = Path(model_dir) if model_dir else default_model_dir()
    want = assets(include_docs=True)
    present = [a for a in want if _intact(a, model_dir)]
    total = sum(a.local(model_dir).stat().st_size for a in present)
    voices = sum(1 for a in present if a.category == "voices")
    return {
        "model_dir": str(model_dir),
        "files_present": len(present),
        "files_expected": len(want),
        "voices_present": voices,
        "voices_expected": len(voice_files()),
        "bytes": total,
        "ready": not missing_assets(model_dir),
        "missing": missing_assets(model_dir),
    }


# --------------------------------------------------------------------- 进度
@dataclass
class Progress:
    """下载/检查过程中的进度事件，通过 on_progress 回调抛出。"""

    stage: str = "check"  # check | download | verify | done | error
    message: str = ""
    file: str = ""
    file_index: int = 0
    files_total: int = 0
    bytes_done: int = 0  # 当前文件已下
    bytes_total: int = 0  # 当前文件总大小
    bytes_written: int = 0  # 本次累计写入
    percent: float = 0.0  # 当前文件百分比
    overall_percent: float = 0.0  # 全部任务百分比
    speed: float = 0.0  # B/s

    @property
    def text(self) -> str:
        if self.stage == "download" and self.file:
            head = f"下载模型 {self.file.split('/')[-1]}"
            if self.bytes_total:
                head += f" {self.percent:5.1f}%"
            if self.speed:
                head += f" {human(self.speed)}/s"
            return head
        return self.message


ProgressCallback = Callable[[Progress], None]


def _emit(cb: Optional[ProgressCallback], **kwargs) -> None:
    if cb is None:
        return
    try:
        cb(Progress(**kwargs))
    except Exception:  # noqa: BLE001 - 进度回调不应影响下载
        pass


class ConsoleReporter:
    """把进度事件打印到控制台（原地刷新百分比）。"""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._inline = False

    def _newline(self) -> None:
        if self._inline:
            sys.stdout.write("\n")
            self._inline = False

    def __call__(self, event: Progress) -> None:
        if not self.enabled:
            return
        if event.stage in ("done", "error"):
            return  # 最终结论由调用方（CLI）打印，避免重复
        if event.stage == "download" and event.bytes_total:
            sys.stdout.write("\r  " + event.text.ljust(64))
            sys.stdout.flush()
            self._inline = True
            return
        self._newline()
        if event.message:
            print("  " + event.message, flush=True)

    def finish(self) -> None:
        self._newline()


# --------------------------------------------------------------------- 网络
def _request(url: str, timeout: float = 60.0, retries: int = 3, **kwargs):
    import requests  # 延迟导入：纯检查（--check）时不需要装 requests

    last: Optional[Exception] = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=UA, timeout=timeout, **kwargs)
            if resp.status_code == 200:
                return resp
            last = RuntimeError(f"HTTP {resp.status_code}")
        except Exception as exc:  # noqa: BLE001
            last = exc
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败: {url} ({last})")


def _list_step(url: str, **kwargs):
    """清单类请求只需要一次成功。"""
    return _request(url, **kwargs)


def _keep(path: str) -> bool:
    return path in DOC_FILES or path == CONFIG_NAME or path == WEIGHTS_NAME or (
        path.startswith(f"{VOICES_DIR}/") and path.endswith(VOICE_EXT)
    )


def list_remote_files(source: str) -> Dict[str, int]:
    """读取远端文件清单，返回 {相对路径: 字节数}。"""
    if source == "hf":
        resp = _list_step(HF_API.format(repo=REPO_ID), params={"recursive": "true"})
        return {
            item["path"]: item.get("size", 0)
            for item in resp.json()
            if item.get("type") == "file" and _keep(item["path"])
        }

    resp = _list_step(
        MODELSCOPE_API.format(repo=REPO_ID),
        params={"Revision": "master", "Recursive": "True"},
    )
    files = (resp.json().get("Data") or {}).get("Files") or []
    return {
        f["Path"]: f.get("Size", 0)
        for f in files
        if f.get("Type") != "tree" and _keep(f["Path"])
    }


def _url_for(source: str, path: str):
    if source == "hf":
        return HF_RAW.format(repo=REPO_ID, path=path), {}
    return MODELSCOPE_RAW.format(repo=REPO_ID), {"Revision": "master", "FilePath": path}


@dataclass
class _Ctx:
    """下载过程中的共享计数，用于估算总进度。"""

    files_total: int = 0
    file_index: int = 0
    done_bytes: int = 0  # 本次已完成的文件字节合计
    planned_bytes: int = 1  # 本次计划下载的总字节
    written: int = 0  # 本次已写入字节合计


def _overall(ctx: _Ctx, current: int = 0) -> float:
    """总进度百分比：已完成文件字节 + 当前文件已下字节。"""
    return min(100.0, (ctx.done_bytes + current) * 100.0 / max(ctx.planned_bytes, 1))


def _download_one(
    source: str,
    path: str,
    size: int,
    out_dir: Path,
    on_progress: Optional[ProgressCallback],
    ctx: _Ctx,
) -> int:
    """下载单个文件，返回本次写入的字节数（0 表示跳过）。"""
    dest = out_dir / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and size and dest.stat().st_size == size:
        _emit(
            on_progress,
            stage="verify",
            file=path,
            file_index=ctx.file_index,
            files_total=ctx.files_total,
            bytes_written=ctx.written,
            overall_percent=_overall(ctx, 0),
            message=f"[跳过] {path}（{human(size)}）",
        )
        return 0

    url, params = _url_for(source, path)
    part = dest.with_suffix(dest.suffix + ".part")
    written = 0
    with _request(url, params=params, stream=True) as resp:
        total = int(resp.headers.get("Content-Length") or size or 0)
        done = 0
        started = time.time()
        last_tick = 0.0
        with part.open("wb") as fh:
            for chunk in resp.iter_content(CHUNK):
                if not chunk:
                    continue
                fh.write(chunk)
                done += len(chunk)
                written += len(chunk)
                now = time.time()
                if now - last_tick <= 0.4:
                    continue
                last_tick = now
                speed = done / max(now - started, 0.01)
                pct = done * 100 / total if total else 0.0
                overall = _overall(ctx, done)
                _emit(
                    on_progress,
                    stage="download",
                    file=path,
                    file_index=ctx.file_index,
                    files_total=ctx.files_total,
                    bytes_done=done,
                    bytes_total=total,
                    bytes_written=ctx.written + written,
                    percent=pct,
                    overall_percent=overall,
                    speed=speed,
                )
    part.replace(dest)
    final = dest.stat().st_size
    _emit(
        on_progress,
        stage="verify",
        file=path,
        file_index=ctx.file_index,
        files_total=ctx.files_total,
        bytes_done=final,
        bytes_total=final,
        bytes_written=ctx.written + written,
        overall_percent=_overall(ctx, final),
        message=f"[完成] {path}（{human(final)}）",
    )
    return written


# --------------------------------------------------------------------- 结果
@dataclass
class Report:
    """一次 ensure_assets() 的结果。"""

    model_dir: Path
    missing_before: List[str] = field(default_factory=list)
    missing_after: List[str] = field(default_factory=list)
    downloaded: List[str] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    bytes_written: int = 0
    sources_tried: List[str] = field(default_factory=list)
    error: Optional[str] = None
    elapsed: float = 0.0

    @property
    def verified(self) -> bool:
        """模型是否已完整可用。"""
        return self.error is None and not self.missing_after

    @property
    def needed_download(self) -> bool:
        return bool(self.missing_before)

    def summary(self) -> str:
        if not self.needed_download:
            return "模型文件已完整，跳过下载"
        if self.verified:
            return (
                f"模型文件已就绪：新下载 {len(self.downloaded)} 个文件，"
                f"{human(self.bytes_written)}，用时 {self.elapsed:.1f}s"
            )
        return self.error or (
            f"模型文件仍不完整，缺少 {len(self.missing_after)} 个文件："
            + "、".join(self.missing_after[:3])
        )


# --------------------------------------------------------------------- 主流程
_LOCK = threading.Lock()  # 同一进程内避免重复下载


def ensure_assets(
    model_dir: Optional[Path] = None,
    source: str = "auto",
    only_core: bool = False,
    include_docs: bool = True,
    allow_download: bool = True,
    on_progress: Optional[ProgressCallback] = None,
) -> Report:
    """检查并按需下载模型资源。

    参数：
        model_dir     模型目录（默认 models/Kokoro-82M，可用 KOKORO_MODEL_DIR 覆盖）
        source        auto | modelscope | hf
        only_core     只保证 config + 权重（不下音色）
        include_docs  是否连带拉取 VOICES.md 等说明文档
        allow_download False 时只检查不下载（离线模式）
        on_progress   进度回调，接收 Progress；抛异常会被忽略
    """
    model_dir = Path(model_dir) if model_dir else default_model_dir()
    started = time.time()
    want = assets(include_docs=include_docs, only_core=only_core)
    report = Report(
        model_dir=model_dir,
        missing_before=[a.path for a in want if not _intact(a, model_dir)],
    )

    def finish() -> Report:
        report.missing_after = [a.path for a in want if not _intact(a, model_dir)]
        report.elapsed = time.time() - started
        if report.verified:
            if report.needed_download:
                _emit(on_progress, stage="done", message=report.summary())
        else:
            _emit(on_progress, stage="error", message=report.error or "模型文件不完整")
        return report

    if not report.missing_before:
        _emit(on_progress, stage="check", message="模型文件已完整，无需下载")
        return finish()

    if not allow_download:
        report.error = (
            f"缺少模型文件：{'、'.join(report.missing_before[:5])}"
            + ("…" if len(report.missing_before) > 5 else "")
            + "。已禁用自动下载（--no-download），请执行 python scripts/download_model.py"
        )
        return finish()

    sources = list(SOURCES) if source == "auto" else [source]
    todo = {a.path: a for a in want if a.path in set(report.missing_before)}
    labels = "、".join(SOURCE_LABEL.get(s, s) for s in sources)
    _emit(
        on_progress,
        stage="check",
        message=f"缺少 {len(todo)} 个模型文件，开始自动下载（下载源：{labels}）",
        files_total=len(todo),
    )

    errors: List[str] = []
    with _LOCK:
        for src in sources:
            report.sources_tried.append(src)
            try:
                _emit(
                    on_progress,
                    stage="check",
                    message=f"读取 {SOURCE_LABEL.get(src, src)} 文件清单 ...",
                )
                remote = list_remote_files(src)
                planned = {p: int(remote[p]) for p in todo if remote.get(p)}
                ctx = _Ctx(
                    files_total=len(planned),
                    planned_bytes=max(sum(planned.values()), 1),
                    written=report.bytes_written,
                )
                for index, (path, size) in enumerate(planned.items(), start=1):
                    ctx.file_index = index
                    ctx.written = report.bytes_written
                    written = _download_one(
                        src, path, size, model_dir, on_progress, ctx
                    )
                    report.bytes_written += written
                    ctx.done_bytes += size
                    (report.downloaded if written else report.skipped).append(path)

                absent = sorted(set(todo) - set(planned))
                if absent:
                    errors.append(
                        f"{src} 远端清单缺少 {len(absent)} 个文件（{'、'.join(absent[:3])}）"
                    )

                report.missing_after = [a.path for a in want if not _intact(a, model_dir)]
                if not report.missing_after:
                    break
                errors.append(
                    f"{src} 下载后仍有 {len(report.missing_after)} 个文件不完整"
                    f"（{'、'.join(report.missing_after[:3])}）"
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{src}: {exc}")
                if src != sources[-1]:
                    _emit(
                        on_progress,
                        stage="check",
                        message=f"{SOURCE_LABEL.get(src, src)} 下载失败（{exc}），回退下一个源 ...",
                    )

    if report.missing_after:
        tried = "；".join(errors) if errors else "无可用下载源"
        report.error = (
            f"自动下载失败：{tried}。"
            "可手动重试 python scripts/download_model.py，"
            "或把 models/Kokoro-82M 整个目录复制到本项目后再启动。"
        )
    return finish()


# 语义别名：CLI 里“下载全部”其实也是 ensure
download_all = ensure_assets


if __name__ == "__main__":  # pragma: no cover - 便捷自检
    info = disk_usage()
    print(f"模型目录：{info['model_dir']}")
    print(f"文件：{info['files_present']}/{info['files_expected']}，音色 {info['voices_present']}/{info['voices_expected']}")
    print(f"占用：{human(info['bytes'])}")
    print("状态：" + ("完整 ✅" if info["ready"] else f"缺少 {len(info['missing'])} 个文件 ❌"))
    raise SystemExit(0 if info["ready"] else 3)
