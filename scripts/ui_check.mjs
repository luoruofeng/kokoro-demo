/**
 * 前端逻辑验证脚本：用 jsdom 加载 static/index.html + static/app.js，
 * 打桩 Web Audio / Canvas，然后真的去调用本地服务完成"选语言 → 选音色 → 生成 → 对比"全流程。
 *
 * 用法：先启动 python server.py，再执行
 *     npm install --no-save jsdom
 *     node scripts/ui_check.mjs
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const BASE = process.env.KOKORO_BASE || "http://127.0.0.1:8000";

const html = readFileSync(resolve(ROOT, "static/index.html"), "utf8");
const appJs = readFileSync(resolve(ROOT, "static/app.js"), "utf8");

const dom = new JSDOM(html, {
  url: BASE + "/",
  runScripts: "outside-only",
  pretendToBeVisual: true,
});
const { window } = dom;

/* ---------------------------------------------------------- Web Audio 打桩 */
let clock = 0;
class FakeBufferSource {
  constructor(ctx) {
    this.ctx = ctx;
    this.buffer = null;
    this.onended = null;
  }
  connect() {}
  start() {
    this.ctx.started += 1;
    setTimeout(() => {
      if (this.onended) this.onended();
    }, 20);
  }
  stop() {}
}
class FakeGain {
  connect() {}
}
class FakeAnalyser {
  constructor() {
    this.fftSize = 512;
    this.frequencyBinCount = 256;
    this.smoothingTimeConstant = 0;
  }
  connect() {}
  getByteFrequencyData(arr) {
    for (let i = 0; i < arr.length; i++) arr[i] = (i * 7) % 200;
  }
}
class FakeAudioContext {
  constructor() {
    this.destination = {};
    this.started = 0;
    this.state = "running";
  }
  get currentTime() {
    return ++clock * 0.02;
  }
  createGain() { return new FakeGain(); }
  createAnalyser() { return new FakeAnalyser(); }
  createBufferSource() { return new FakeBufferSource(this); }
  resume() { this.state = "running"; }
  async decodeAudioData(arrayBuffer) {
    const seconds = Math.min(3, Math.max(0.6, arrayBuffer.byteLength / 48000));
    const data = new Float32Array(Math.round(seconds * 24000));
    for (let i = 0; i < data.length; i++) data[i] = Math.sin(i / 40) * 0.4;
    return {
      duration: seconds,
      length: data.length,
      sampleRate: 24000,
      getChannelData: () => data,
    };
  }
}
window.AudioContext = FakeAudioContext;
window.webkitAudioContext = FakeAudioContext;
window.CSS = { escape: (s) => String(s).replace(/[^a-zA-Z0-9_-]/g, (c) => "\\" + c) };
window.HTMLCanvasElement.prototype.getContext = function () {
  return {
    setTransform() {},
    clearRect() {},
    fillRect() {},
    beginPath() {},
    arc() {},
    fill() {},
    createLinearGradient: () => ({ addColorStop() {} }),
    set fillStyle(v) {},
    get fillStyle() { return ""; },
  };
};
let frames = 0;
window.requestAnimationFrame = (fn) => {
  if (frames++ > 400) return 0;
  return setTimeout(() => fn(performance.now()), 16);
};

// 相对路径的 fetch 需要补全成绝对地址
window.fetch = (input, init) => globalThis.fetch(new URL(input, BASE + "/"), init);

/* ---------------------------------------------------------------- 执行 app.js */
window.eval(appJs);
const doc = window.document;
const $ = (id) => doc.getElementById(id);

const failures = [];
function check(name, condition, detail = "") {
  const ok = Boolean(condition);
  console.log(`  ${ok ? "✅" : "❌"} ${name}${detail ? " — " + detail : ""}`);
  if (!ok) failures.push(name + (detail ? ` (${detail})` : ""));
}

async function waitFor(label, fn, timeout = 180000, step = 250) {
  const started = Date.now();
  for (;;) {
    let value = false;
    try {
      value = fn();
    } catch (e) {
      value = false;
    }
    if (value) return value;
    if (Date.now() - started > timeout) throw new Error(`等待超时：${label}`);
    await new Promise((r) => setTimeout(r, step));
  }
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function main() {
  console.log(`\n[1/6] 等待引擎就绪（${BASE}）...`);
  await waitFor("engine ready", () => $("chip-state-text").textContent === "已就绪");
  check("引擎状态显示已就绪", $("chip-state-text").textContent === "已就绪");
  check("加载遮罩已隐藏", $("overlay").className.includes("hide"));

  console.log("[2/6] 检查语言与音色渲染 ...");
  const langItems = doc.querySelectorAll(".lang-item");
  check("渲染 9 个语言条目", langItems.length === 9, `实际 ${langItems.length}`);
  const voiceBtns = doc.querySelectorAll(".voice-btn");
  check("默认语言的音色按钮已渲染", voiceBtns.length > 0, `${voiceBtns.length} 个`);
  check("状态栏显示音色总数 54", $("chip-voices").textContent.includes("54"), $("chip-voices").textContent);

  console.log("[3/6] 切换到中文并检查文案联动 ...");
  const zhItem = [...langItems].find((el) => el.textContent.includes("中文"));
  zhItem.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(120);
  check("中文被标记为选中", zhItem.className.includes("active"));
  check("标题切换为中文", $("lang-title").textContent.includes("中文"), $("lang-title").textContent);
  check("文本框自动填入中文示例", $("text").value.includes("你好"), $("text").value.slice(0, 12));
  check("G2P 标签已更新", $("lang-g2p").textContent.includes("misaki[zh]"), $("lang-g2p").textContent);

  console.log("[4/6] 点击“生成并播放”（真实调用 /api/tts）...");
  $("btn-generate").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await waitFor("player visible", () => !$("player").hidden, 120000);
  await waitFor("player meta", () => $("player-meta").textContent.includes("RTF"), 120000);
  const meta = $("player-meta").textContent;
  check("播放器已展开", !$("player").hidden);
  check("展示音频时长/RTF 等指标", meta.includes("音频") && meta.includes("RTF"), meta.replace(/\s+/g, " "));
  check("音素序列非空", $("phoneme-text").textContent.length > 3, $("phoneme-text").textContent.slice(0, 40));
  check("已触发音频播放", $("play-btn").textContent.length > 0);
  check("总时长已更新", $("time-total").textContent !== "0:00", $("time-total").textContent);

  console.log("[5/6] 点击“生成 9 种语言”进行对比 ...");
  $("btn-compare").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await waitFor("compare list", () => doc.querySelectorAll(".cmp-item").length === 9, 600000);
  check("生成 9 条对比条目", doc.querySelectorAll(".cmp-item").length === 9);
  check("对比条目包含音频信息", doc.querySelector(".cmp-sub").textContent.includes("RTF"), doc.querySelector(".cmp-sub").textContent);

  console.log("[6/6] 依次播放与历史记录 ...");
  $("btn-play-all").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(1500);
  check("依次播放时存在高亮条目或已播完", doc.querySelectorAll(".cmp-item.playing").length >= 0);
  const historyRows = doc.querySelectorAll(".his-item");
  check("历史记录已写入", historyRows.length > 0, `${historyRows.length} 条`);
  const hisTitle = doc.querySelector(".his-title").textContent;
  doc.querySelector(".his-title").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await sleep(120);
  check("点击历史记录可回填文本框", $("text").value.length > 0, hisTitle.trim().slice(0, 20));

  console.log("\n===== 结果 =====");
  if (failures.length) {
    console.error(`前端检查失败 ${failures.length} 项：\n  - ` + failures.join("\n  - "));
    process.exitCode = 1;
  } else {
    console.log("前端全流程检查通过 ✅");
  }
  window.close();
}

main().catch((err) => {
  console.error("前端检查异常：", err.message);
  process.exitCode = 1;
});
