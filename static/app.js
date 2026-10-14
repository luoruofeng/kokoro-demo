/* Kokoro-82M 多语言 TTS 播放效果 Demo —— 前端逻辑 */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  catalog: [],
  catalogLoaded: false,
  lang: "z",
  voice: null,
  speed: 1.0,
  studio: null, // { buffer, peaks, meta }
  compare: [],
  history: [],
  busy: false,
  seqToken: 0,
  activeKey: null,
};

/* ------------------------------------------------------------------ 音频引擎 */
const players = {
  ctx: null,
  analyser: null,
  gain: null,
  source: null,
  buffer: null,
  offset: 0,
  startedAt: 0,
  playing: false,
  onEnd: null,

  ensure() {
    if (this.ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AC();
    this.gain = this.ctx.createGain();
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 512;
    this.analyser.smoothingTimeConstant = 0.78;
    this.gain.connect(this.analyser);
    this.analyser.connect(this.ctx.destination);
  },

  async decode(dataUrl) {
    this.ensure();
    const buf = await (await fetch(dataUrl)).arrayBuffer();
    return await this.ctx.decodeAudioData(buf);
  },

  play(buffer, onEnd) {
    this.ensure();
    if (!buffer) return;
    if (this.ctx.state === "suspended") this.ctx.resume();
    this.stopSource();
    const src = this.ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(this.gain);
    let from = this.offset;
    if (from >= buffer.duration - 0.02) from = 0;
    this.buffer = buffer;
    this.offset = from;
    this.startedAt = this.ctx.currentTime - from;
    src.onended = () => {
      if (this.source !== src) return;
      this.source = null;
      this.playing = false;
      this.offset = 0;
      const cb = this.onEnd;
      this.onEnd = null;
      if (cb) cb();
    };
    this.source = src;
    this.playing = true;
    src.start(0, from);
  },

  stopSource() {
    if (this.source) {
      this.source.onended = null;
      try { this.source.stop(); } catch (e) { /* ignore */ }
      this.source = null;
    }
    this.playing = false;
  },

  pause() {
    if (!this.playing) return;
    this.offset = this.position;
    this.stopSource();
  },

  stop() {
    this.stopSource();
    this.offset = 0;
    this.onEnd = null;
  },

  seek(seconds) {
    const buf = this.buffer;
    const target = Math.max(0, Math.min(seconds, buf ? buf.duration : 0));
    if (this.playing) {
      this.offset = target;
      const cb = this.onEnd;
      this.play(buf, cb);
    } else {
      this.offset = target;
    }
  },

  get position() {
    if (!this.playing) return this.offset;
    const p = this.ctx.currentTime - this.startedAt;
    return this.buffer ? Math.min(p, this.buffer.duration) : p;
  },
};

/* ------------------------------------------------------------------ 波形绘制 */
function computePeaks(buffer, buckets = 520) {
  const ch = buffer.getChannelData(0);
  const step = Math.max(1, Math.floor(ch.length / buckets));
  const out = new Float32Array(buckets);
  for (let i = 0; i < buckets; i++) {
    let max = 0;
    const start = i * step;
    const end = Math.min(start + step, ch.length);
    for (let j = start; j < end; j++) {
      const v = Math.abs(ch[j]);
      if (v > max) max = v;
    }
    out[i] = max;
  }
  return out;
}

function fitCanvas(canvas) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 600;
  const h = canvas.clientHeight || 90;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas._grad = null;
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

/* 渐变对象按画布尺寸缓存，避免每帧重复创建（体积/性能关键） */
function canvasGradients(canvas, ctx, h) {
  if (canvas._grad && canvas._grad.h === h) return canvas._grad;
  const mid = h / 2;
  const played = ctx.createLinearGradient(0, 0, 0, h);
  played.addColorStop(0, "#34e0c8");
  played.addColorStop(0.5, "#5b8cff");
  played.addColorStop(1, "#34e0c8");
  const idle = ctx.createLinearGradient(0, 0, 0, h);
  idle.addColorStop(0, "rgba(255,255,255,0.24)");
  idle.addColorStop(1, "rgba(255,255,255,0.08)");
  const bar = ctx.createLinearGradient(0, h, 0, 0);
  bar.addColorStop(0, "rgba(91,140,255,0.85)");
  bar.addColorStop(1, "rgba(52,224,200,0.95)");
  canvas._grad = { h, mid, played, idle, bar };
  return canvas._grad;
}

function drawWave(canvas, peaks, progress) {
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  if (!peaks || !peaks.length) return;
  const { mid, played, idle } = canvasGradients(canvas, ctx, h);
  const n = peaks.length;
  const barW = w / n;
  const bw = Math.max(barW - 1.1, 1);
  const cut = progress * n;
  for (let i = 0; i < n; i++) {
    const amp = Math.max(peaks[i], 0.008) * (h * 0.44);
    ctx.fillStyle = i + 0.5 <= cut ? played : idle;
    ctx.fillRect(i * barW + 0.5, mid - amp, bw, amp * 2);
  }
  if (progress > 0) {
    const px = progress * w;
    ctx.fillStyle = "rgba(255,255,255,0.9)";
    ctx.fillRect(px - 1, 0, 2, h);
    ctx.beginPath();
    ctx.arc(px, mid, 4.5, 0, Math.PI * 2);
    ctx.fill();
  }
}

const SPECTRUM_BARS = 72;
const spectrumData = new Uint8Array(1024);

function drawSpectrum(canvas, analyser, active) {
  const { ctx, w, h } = fitCanvas(canvas);
  ctx.clearRect(0, 0, w, h);
  const bins = analyser ? analyser.frequencyBinCount : 0;
  let data = null;
  if (analyser && active) {
    data = spectrumData.subarray(0, bins);
    analyser.getByteFrequencyData(data);
  }
  const { bar } = canvasGradients(canvas, ctx, h);
  const barW = w / SPECTRUM_BARS;
  for (let i = 0; i < SPECTRUM_BARS; i++) {
    let v = 0;
    if (data && bins) {
      const idx = Math.min(Math.floor(Math.pow(i / SPECTRUM_BARS, 1.6) * (bins * 0.7)), bins - 1);
      v = data[idx] / 255;
    }
    const bh = Math.max(v * h * 0.94, 1.5);
    ctx.fillStyle = data ? bar : "rgba(255,255,255,0.07)";
    ctx.fillRect(i * barW + 1, h - bh, Math.max(barW - 2.4, 1), bh);
  }
}

/* ------------------------------------------------------------------ 播放循环 */
let rafId = null;

function startRenderLoop(key) {
  state.activeKey = key;
  if (rafId) return;
  const tick = () => {
    const isStudio = state.activeKey === "studio";
    if (state.studio) {
      const dur = state.studio.buffer.duration || 1;
      const pos = isStudio ? (players.playing ? players.position : players.offset) : 0;
      drawWave($("wave"), state.studio.peaks, Math.min(pos / dur, 1));
      $("time-now").textContent = fmtTime(pos);
      $("play-btn").textContent = isStudio && players.playing ? "❚❚" : "▶";
    }
    drawSpectrum($("spectrum"), players.analyser, players.playing && isStudio);
    rafId = requestAnimationFrame(tick);
  };
  rafId = requestAnimationFrame(tick);
}

function fmtTime(sec) {
  sec = Math.max(0, sec || 0);
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/* ------------------------------------------------------------------ 工具 */
let toastTimer = null;
function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = "toast show" + (isError ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = "toast"; }, 2600);
}

function setBusy(busy, label) {
  state.busy = busy;
  for (const id of ["btn-generate", "btn-generate-only", "btn-compare", "btn-play-all"]) {
    const btn = $(id);
    if (!btn) continue;
    btn.disabled = busy || (id === "btn-play-all" && !state.compare.some((c) => c.ok));
  }
  if (busy) {
    const target = $("btn-generate");
    target.dataset.label = target.dataset.label || target.textContent;
    target.innerHTML = `<span class="spin-inline"></span>${label || "合成中"}`;
  } else {
    $("btn-generate").textContent = "生成并播放";
  }
}

function gradeClass(grade) {
  const g = (grade || "").toUpperCase();
  if (g.startsWith("A")) return "g-a";
  if (g.startsWith("B")) return "g-b";
  if (g.startsWith("C")) return "g-c";
  return "g-d";
}

/* ------------------------------------------------------------------ 渲染 */
function renderLanguages() {
  const list = $("lang-list");
  list.innerHTML = "";
  $("lang-count").textContent = `${state.catalog.length}`;
  for (const lang of state.catalog) {
    const li = document.createElement("li");
    li.className = "lang-item" + (lang.code === state.lang ? " active" : "");
    li.innerHTML = `
      <span class="lang-flag">${lang.flag}</span>
      <span>
        <div class="lang-name">${lang.name}</div>
        <div class="lang-english">${lang.english}</div>
      </span>`;
    li.onclick = () => selectLanguage(lang.code);
    list.appendChild(li);
  }
}

function currentLangMeta() {
  return state.catalog.find((l) => l.code === state.lang) || state.catalog[0];
}

function selectLanguage(code) {
  state.lang = code;
  const meta = currentLangMeta();
  state.voice = meta.default_voice;
  // 切换语言时直接带入该语言的示例文案，做到"点一下就能听"
  $("text").value = meta.samples[0];
  renderLanguages();
  renderStudio();
}

function renderStudio() {
  const meta = currentLangMeta();
  if (!meta) return;
  $("lang-title").textContent = `${meta.flag} ${meta.name}`;
  $("lang-tip").textContent = meta.tip;
  $("lang-g2p").textContent = "G2P · " + meta.g2p;

  const grid = $("voice-grid");
  grid.innerHTML = "";
  for (const v of meta.voices) {
    const btn = document.createElement("button");
    btn.className = "voice-btn" + (v.id === state.voice ? " active" : "");
    btn.innerHTML = `
      <span class="v-name">${v.name} <span class="grade ${gradeClass(v.grade)}">${v.grade}</span></span>
      <span class="v-sub">${v.gender === "f" ? "女声" : "男声"} · ${v.id}${v.note ? " · " + v.note : ""}</span>`;
    btn.onclick = () => {
      state.voice = v.id;
      renderStudio();
      playVoicePreview();
    };
    grid.appendChild(btn);
  }
  $("voice-hint").textContent = `${meta.voices.length} 个音色 · 点击试听`;

  const chips = $("sample-chips");
  chips.innerHTML = "";
  meta.samples.forEach((text, i) => {
    const b = document.createElement("button");
    b.className = "chip-btn";
    b.textContent = `示例 ${i + 1} · ${text.slice(0, 26)}…`;
    b.title = text;
    b.onclick = () => {
      $("text").value = text;
      $("text").focus();
    };
    chips.appendChild(b);
  });
  if (!$("text").value.trim()) $("text").value = meta.samples[0];
}

function renderPlayer(meta) {
  $("player").hidden = false;
  const langName = meta.lang_name || "";
  $("player-title").textContent = `${langName} · ${meta.voice} @ ${meta.speed.toFixed(2)}×`;
  $("player-meta").innerHTML = [
    `音频 <b>${meta.seconds}s</b>`,
    `合成耗时 <b>${meta.elapsed}s</b>`,
    `RTF <b>${meta.rtf}</b>`,
    `切块 <b>${meta.chunks}</b>`,
    `采样率 <b>24 kHz</b>`,
  ].join(" · ");
  $("time-total").textContent = fmtTime(meta.seconds);
  $("time-now").textContent = "0:00";
  $("phoneme-text").textContent = meta.phonemes || "（无）";
}

function renderCompare() {
  const box = $("compare-list");
  box.innerHTML = "";
  if (!state.compare.length) {
    box.innerHTML = '<div class="empty">还没有对比结果</div>';
    $("btn-play-all").disabled = true;
    return;
  }
  state.compare.forEach((item, idx) => {
    const row = document.createElement("div");
    row.className = "cmp-item";
    row.dataset.idx = String(idx);
    if (!item.ok) {
      row.innerHTML = `<button disabled>✕</button>
        <div class="cmp-main"><div class="cmp-title">${item.lang_name}</div>
        <div class="cmp-sub">失败：${item.error}</div></div>`;
    } else {
      row.innerHTML = `
        <button title="播放">▶</button>
        <div class="cmp-main">
          <div class="cmp-title">${item.flag} ${item.lang_name}</div>
          <div class="cmp-sub">${item.voice} · ${item.seconds}s · RTF ${item.rtf}</div>
        </div>`;
      row.querySelector("button").onclick = () => playCompareItem(idx);
    }
    box.appendChild(row);
  });
  $("btn-play-all").disabled = !state.compare.some((c) => c.ok);
}

function markPlaying(key) {
  document.querySelectorAll(".cmp-item, .his-item").forEach((el) => el.classList.remove("playing"));
  if (!key) return;
  const [kind, id] = key.split(":");
  const sel = kind === "compare" ? `.cmp-item[data-idx="${id}"]` : `.his-item[data-file="${CSS.escape(id)}"]`;
  const el = document.querySelector(sel);
  if (el) el.classList.add("playing");
}

function renderHistory() {
  const box = $("history-list");
  box.innerHTML = "";
  $("history-count").textContent = state.history.length ? `${state.history.length}` : "";
  if (!state.history.length) {
    box.innerHTML = '<div class="empty">暂无记录</div>';
    return;
  }
  for (const item of state.history) {
    const row = document.createElement("div");
    row.className = "his-item";
    row.dataset.file = item.file;
    row.innerHTML = `
      <button title="播放 / 下载">▶</button>
      <div class="his-main">
        <div class="his-title">${item.flag || ""} ${item.text.slice(0, 18)}${item.text.length > 18 ? "…" : ""}</div>
        <div class="his-sub">${item.lang_name} · ${item.voice} · ${item.seconds}s</div>
      </div>`;
    row.querySelector("button").onclick = () => playHistory(item);
    row.querySelector(".his-title").onclick = () => {
      state.lang = item.lang;
      const meta = currentLangMeta();
      if (meta) {
        state.voice = meta.voices.some((v) => v.id === item.voice) ? item.voice : meta.default_voice;
      }
      $("text").value = item.text;
      renderLanguages();
      renderStudio();
    };
    box.appendChild(row);
  }
}

/* ------------------------------------------------------------------ 播放动作 */
const historyBuffers = new Map();

function playStudio() {
  if (!state.studio) return;
  state.seqToken++;
  markPlaying(null);
  startRenderLoop("studio");
  if (players.playing && players.buffer === state.studio.buffer) {
    players.pause();
    return;
  }
  players.onEnd = () => {
    drawWave($("wave"), state.studio.peaks, 0);
    $("play-btn").textContent = "▶";
    $("time-now").textContent = "0:00";
    drawSpectrum($("spectrum"), players.analyser, false);
  };
  players.play(state.studio.buffer, players.onEnd);
}

function playCompareItem(idx) {
  const item = state.compare[idx];
  if (!item || !item.buffer) return;
  state.seqToken++;
  markPlaying(`compare:${idx}`);
  startRenderLoop("other");
  players.stop();
  players.play(item.buffer, () => {
    markPlaying(null);
    drawSpectrum($("spectrum"), players.analyser, false);
  });
}

async function playHistory(item) {
  try {
    let buffer = historyBuffers.get(item.file);
    if (!buffer) {
      buffer = await players.decode(item.url);
      historyBuffers.set(item.file, buffer);
    }
    state.seqToken++;
    markPlaying(`history:${item.file}`);
    startRenderLoop("other");
    players.stop();
    players.play(buffer, () => {
      markPlaying(null);
      drawSpectrum($("spectrum"), players.analyser, false);
    });
  } catch (e) {
    toast("播放失败：" + e.message, true);
  }
}

async function playAllCompare() {
  const token = ++state.seqToken;
  for (let i = 0; i < state.compare.length; i++) {
    const item = state.compare[i];
    if (!item.ok || !item.buffer || token !== state.seqToken) break;
    markPlaying(`compare:${i}`);
    startRenderLoop("other");
    players.stop();
    await new Promise((resolve) => {
      players.play(item.buffer, () => setTimeout(resolve, 260));
      if (!players.playing) resolve();
    });
  }
  if (token === state.seqToken) markPlaying(null);
}

async function playVoicePreview() {
  // 切换音色时用当前文本的前一小段做快速试听
  const meta = currentLangMeta();
  const text = ($("text").value || meta.samples[0]).split(/\n+/)[0].slice(0, 60);
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, lang: state.lang, voice: state.voice, speed: state.speed, save: false }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "试听失败");
    const buffer = await players.decode(data.audio);
    state.seqToken++;
    markPlaying(null);
    players.stop();
    players.play(buffer, null);
  } catch (e) {
    toast("试听失败：" + e.message, true);
  }
}

/* ------------------------------------------------------------------ 请求 */
async function generate(autoplay) {
  const text = $("text").value.trim();
  if (!text) { toast("请先输入要朗读的文本", true); return; }
  setBusy(true);
  try {
    const res = await fetch("/api/tts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        lang: state.lang,
        voice: state.voice,
        speed: state.speed,
        save: true,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "合成失败");
    const buffer = await players.decode(data.audio);
    state.studio = { buffer, peaks: computePeaks(buffer), meta: data };
    players.offset = 0;
    players.buffer = buffer;
    renderPlayer(data);
    drawWave($("wave"), state.studio.peaks, 0);
    startRenderLoop("studio");
    if (autoplay) playStudio();
    toast(`合成完成：${data.seconds}s 音频 / 用时 ${data.elapsed}s`);
    refreshHistory();
  } catch (e) {
    toast(e.message, true);
  } finally {
    setBusy(false);
  }
}

async function runCompare() {
  setBusy(true, "对比合成中");
  try {
    const res = await fetch("/api/compare", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_index: 0, speed: state.speed }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "对比合成失败");
    for (const item of data.results) {
      if (item.ok) item.buffer = await players.decode(item.audio);
    }
    state.compare = data.results;
    renderCompare();
    refreshHistory();
    toast(`已生成 ${data.results.filter((r) => r.ok).length} 种语言的对比音频`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    setBusy(false);
  }
}

async function refreshHistory() {
  try {
    const data = await (await fetch("/api/history")).json();
    state.history = data.items || [];
    renderHistory();
  } catch (e) { /* ignore */ }
}

async function clearHistory() {
  await fetch("/api/history", { method: "DELETE" });
  historyBuffers.clear();
  refreshHistory();
  toast("已清空历史记录");
}

/* ------------------------------------------------------------------ 启动 */
async function loadCatalog() {
  const data = await (await fetch("/api/catalog")).json();
  state.catalog = data.languages;
  state.catalogLoaded = true;
  const engine = data.engine || {};
  $("chip-device").textContent = `设备 · ${(engine.device || "cpu").toUpperCase()}`;
  $("chip-model").textContent = `模型 · ${data.repo_id}`;
  $("chip-voices").textContent = `音色 · ${engine.voices}`;
  state.lang = state.catalog.find((l) => l.code === "z") ? "z" : state.catalog[0].code;
  state.voice = currentLangMeta().default_voice;
  renderLanguages();
  renderStudio();
  drawSpectrum($("spectrum"), null, false);
  return data;
}

async function pollStatus() {
  let status;
  try {
    status = await (await fetch("/api/status")).json();
  } catch (e) {
    $("overlay-text").textContent = "无法连接后端，正在重试 …";
    setTimeout(pollStatus, 1200);
    return;
  }
  $("overlay-text").textContent = status.stage || status.message || "";
  if (status.state === "ready") {
    $("chip-state").className = "chip chip-state ready";
    $("chip-state-text").textContent = "已就绪";
    $("chip-device").textContent = `设备 · ${(status.device || "cpu").toUpperCase()}`;
    if (!state.catalogLoaded) {
      try {
        await loadCatalog();
      } catch (e) {
        setTimeout(pollStatus, 900);
        return;
      }
    }
    $("overlay").classList.add("hide");
    return;
  }
  if (status.state === "error") {
    $("overlay-spinner").style.display = "none";
    $("overlay-bar").hidden = true;
    $("chip-state").className = "chip chip-state error";
    $("chip-state-text").textContent = "加载失败";
    $("overlay-title").textContent = "模型加载失败";
    $("overlay-title").classList.add("err");
    $("overlay-text").textContent = status.error || status.message;
    $("overlay-sub").textContent = status.auto_download
      ? "可手动执行 python scripts/download_model.py 后刷新页面"
      : "当前以 --no-download 启动，请先准备好模型文件再刷新";
    if (!state.catalogLoaded) loadCatalog().catch(() => {});
    return;
  }
  renderBootstrap(status);
  setTimeout(pollStatus, status.state === "downloading" ? 700 : 800);
}

/* 首次运行：把后端自动下载模型的进度画在遮罩层上 */
function renderBootstrap(status) {
  const dl = status.download;
  const bar = $("overlay-bar");
  const fill = $("overlay-bar-fill");
  const sub = $("overlay-sub");

  if (dl && status.state === "downloading") {
    $("overlay-title").textContent = "首次运行：正在自动下载模型";
    $("overlay-title").classList.remove("err");
    const pct = dl.overall_percent || 0;
    bar.hidden = false;
    fill.style.width = `${pct.toFixed(1)}%`;
    $("overlay-spinner").style.display = dl.stage === "download" ? "none" : "";
    if (dl.stage === "download" && dl.bytes_total) {
      sub.textContent =
        `${dl.files_done}/${dl.files_total} 个文件 · ${fmtBytes(dl.bytes_written)} 已写入 · ` +
        `${fmtBytes(dl.speed)}/s · 总进度 ${pct.toFixed(0)}%`;
    } else {
      sub.textContent = dl.files_total ? `共 ${dl.files_total} 个文件待处理` : "";
    }
    return;
  }

  bar.hidden = true;
  $("overlay-spinner").style.display = "";
  const assets = status.assets;
  if (assets) {
    sub.textContent = assets.missing
      ? `本地已有 ${assets.files_present}/${assets.files_expected} 个文件（${assets.human_size}），缺 ${assets.missing} 个`
      : `本地模型 ${assets.files_present} 个文件 / ${assets.human_size} 已就绪，正在加载引擎`;
  } else {
    sub.textContent = "";
  }
}

function fmtBytes(n) {
  const value = Number(n) || 0;
  const units = ["B", "KB", "MB", "GB"];
  let v = value;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)}${units[i]}`;
}

function bindEvents() {
  $("btn-generate").onclick = () => generate(true);
  $("btn-generate-only").onclick = () => generate(false);
  $("btn-clear").onclick = () => {
    $("text").value = "";
    $("text").focus();
  };
  $("btn-compare").onclick = runCompare;
  $("btn-play-all").onclick = playAllCompare;
  $("btn-history-refresh").onclick = refreshHistory;
  $("btn-history-clear").onclick = clearHistory;
  $("play-btn").onclick = playStudio;
  $("speed").oninput = (e) => {
    state.speed = parseFloat(e.target.value);
    $("speed-value").textContent = state.speed.toFixed(2) + "×";
  };
  $("wave").onclick = (e) => {
    if (!state.studio) return;
    const rect = $("wave").getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    players.seek(ratio * state.studio.buffer.duration);
    startRenderLoop("studio");
    $("time-now").textContent = fmtTime(players.position);
  };
  $("text").addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") generate(true);
  });
  window.addEventListener("resize", () => {
    if (state.studio) drawWave($("wave"), state.studio.peaks, players.playing ? players.position / state.studio.buffer.duration : 0);
    drawSpectrum($("spectrum"), players.analyser, players.playing);
  });
}

(async function boot() {
  bindEvents();
  drawSpectrum($("spectrum"), null, false);
  pollStatus();
  refreshHistory();
})();
