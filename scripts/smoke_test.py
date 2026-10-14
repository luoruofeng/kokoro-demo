"""端到端冒烟测试：确认 Web 服务与 9 种语言的合成链路都正常。

先启动服务（python server.py），再运行：
    python scripts/smoke_test.py
    python scripts/smoke_test.py --base http://127.0.0.1:8000 --langs a,z
"""
from __future__ import annotations

import argparse
import base64
import io
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from languages import LANG_BY_CODE  # noqa: E402


def wait_ready(base: str, timeout: float = 120) -> dict:
    started = time.time()
    last = ""
    while time.time() - started < timeout:
        try:
            status = requests.get(f"{base}/api/status", timeout=10).json()
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"无法连接 {base}：{exc}（请先运行 python server.py）") from exc
        if status["state"] == "ready":
            return status
        if status["state"] == "error":
            raise SystemExit(f"引擎加载失败：{status.get('error')}")
        if status.get("stage") != last:
            last = status.get("stage") or ""
            print(f"  等待模型加载 ... {last}", flush=True)
        time.sleep(1.0)
    raise SystemExit("等待模型加载超时")


def audio_stats(data_url: str) -> tuple[float, float]:
    import numpy as np
    import soundfile as sf

    raw = base64.b64decode(data_url.split(",", 1)[1])
    audio, rate = sf.read(io.BytesIO(raw))
    return len(audio) / rate, float(np.abs(audio).max())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--langs", default="a,b,e,f,h,i,p,j,z", help="要测试的语言代码")
    parser.add_argument("--speed", type=float, default=1.0)
    args = parser.parse_args()
    base = args.base.rstrip("/")

    print("[1/4] 等待服务就绪 ...")
    status = wait_ready(base)
    print(f"      就绪：设备 {status['device']}，模型加载 {status['load_seconds']}s")

    print("[2/4] 读取语言/音色清单 ...")
    catalog = requests.get(f"{base}/api/catalog", timeout=30).json()
    langs = catalog["languages"]
    total_voices = sum(len(l["voices"]) for l in langs)
    print(f"      语言 {len(langs)} 种，音色 {total_voices} 个，repo={catalog['repo_id']}")
    assert catalog["ready"], "catalog 未标记 ready"

    print("[3/4] 逐语言合成（使用各语言第一条示例文案）...")
    langs_wanted = [c.strip() for c in args.langs.split(",") if c.strip()]
    failures = []
    for code in langs_wanted:
        meta = next((l for l in langs if l["code"] == code), None)
        if meta is None:
            failures.append((code, "语言不存在"))
            continue
        payload = {
            "text": meta["samples"][0],
            "lang": code,
            "voice": meta["default_voice"],
            "speed": args.speed,
            "save": True,
        }
        resp = requests.post(f"{base}/api/tts", json=payload, timeout=180)
        if resp.status_code != 200:
            failures.append((code, resp.text[:120]))
            print(f"      {code} 失败：{resp.text[:120]}")
            continue
        data = resp.json()
        seconds, peak = audio_stats(data["audio"])
        flag = "OK " if seconds > 0.5 and peak > 0.05 else "弱 "
        print(
            f"      {flag}{code} {meta['name']:<8} {data['voice']:<13} "
            f"音频 {seconds:5.2f}s | 用时 {data['elapsed']:4.2f}s | RTF {data['rtf']:4.2f} | "
            f"峰值 {peak:.3f} | 音素 {data['phonemes'][:32]}..."
        )
        if seconds <= 0.5 or peak <= 0.05:
            failures.append((code, f"音频异常 seconds={seconds} peak={peak}"))

    print("[4/4] 检查对比接口与历史记录 ...")
    cmp_resp = requests.post(f"{base}/api/compare", json={"sample_index": 0, "speed": 1.0}, timeout=600)
    cmp_data = cmp_resp.json()
    ok_count = sum(1 for r in cmp_data["results"] if r["ok"])
    print(f"      对比接口返回 {len(cmp_data['results'])} 项，成功 {ok_count} 项")
    history = requests.get(f"{base}/api/history", timeout=30).json()["items"]
    print(f"      历史记录 {len(history)} 条")

    print()
    if failures:
        print("存在失败项：")
        for code, reason in failures:
            print(f"  - {code}: {reason}")
        return 1
    print("全部检查通过 ✅")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
