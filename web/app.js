/* Seslendirme Stüdyosu — arayüz mantığı */
"use strict";

const $ = (s) => document.querySelector(s);
const STUDIO_TOKEN = (document.querySelector('meta[name="studio-token"]') || {}).content || "";
const el = (tag, cls, text) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
};

let S = {
  video: null,
  segments: [],   // {id, text, start, dur, model_text, spoken, token}
  settings: { speed: 0.95, steps: 8, gap: 0.2, out_dir: "", tts_motor: "antalia", vox_ses: "hazir/belgesel_hanim" },
  fit: 1,         // anlatım videoya sığdırılırken uygulanan hız oranı
  result: null,
  engine: { state: "off", message: "" },
  vox: { state: "off", message: "" },
  vox_sesler: [],
};
let busy = false;
let enginePollTimer = null;

// ---------------------------------------------------------------- api
async function api(path, body, method) {
  const opt = { method: method || (body !== undefined ? "POST" : "GET") };
  if (body !== undefined) {
    opt.headers = { "Content-Type": "application/json", "X-Studio-Token": STUDIO_TOKEN };
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  let j = {};
  try { j = await r.json(); } catch (e) { /* boş yanıt */ }
  if (!r.ok || j.error) throw new Error(j.error || ("HTTP " + r.status));
  return j;
}

function setStatus(msg, kind) {
  const box = $("#produce-status");
  if (!msg) { box.hidden = true; box.textContent = ""; box.className = "status"; return; }
  box.hidden = false;
  box.className = "status" + (kind ? " " + kind : "");
  box.textContent = msg;
}

function setBusy(isBusy, msg, kind) {
  busy = isBusy;
  const voxSecili = (S.settings.tts_motor || "antalia") === "voxcpm";
  const motorHazir = voxSecili ? !!(S.vox && S.vox.state === "ready") : S.engine.state === "ready";
  $("#btn-synth").disabled = isBusy || !motorHazir;
  $("#btn-render").disabled = isBusy || !allSynthDone();
  const bs = $("#btn-save");
  if (bs) bs.disabled = isBusy || !canSave();
  const bai = $("#btn-ai");
  if (bai) bai.disabled = isBusy || !S.video;
  if (msg !== undefined) setStatus(msg || "", kind);
}

// ---------------------------------------------------------------- görsel
function showVideo() {
  const v = S.video;
  if (!v) return;
  $("#video-wrap").hidden = false;
  const img = $("#video-img");
  const src = `/api/media?k=${v.token}`;
  img.hidden = false;
  if (!img.src.endsWith(src)) img.src = src;
  $("#video-info").textContent = `${v.name} · soru görseli`;
  $("#video-path").value = v.path || $("#video-path").value;
  const bai = $("#btn-ai");
  if (bai && !busy) bai.disabled = !S.video;
}

async function openVideoFromPath() {
  const path = $("#video-path").value.trim();
  if (!path) return;
  setStatus("Görsel açılıyor…");
  try {
    const r = await api("/api/video", { mode: "path", path });
    const cleared = !!(r.video && r.video.cleared_segments);
    S.video = r.video;
    if (cleared) { S.segments = []; S.result = null; }
    showVideo();
    renderSegments();
    showResult();
    if (cleared) {
      setStatus("Yeni soru görseli açıldı; önceki anlatım adımları sıfırlandı. " +
        "“AI ile taslak yaz” ile çözümünü hazırlatabilirsin.", "ok");
    } else {
      setStatus("");
    }
    // kayıt klasörü önerisi sunucudan güncellenmiş olabilir
    await refreshSettingsFromState();
  } catch (e) {
    setStatus("Görsel açılamadı: " + e.message, "err");
  }
}

async function uploadVideo(file) {
  setStatus("Görsel yükleniyor… (" + (file.size / 1048576).toFixed(1) + " MB)");
  try {
    const r = await fetch("/api/video/upload?name=" + encodeURIComponent(file.name), {
      method: "POST", body: file, headers: { "X-Studio-Token": STUDIO_TOKEN },
    });
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || ("HTTP " + r.status));
    const cleared = !!(j.video && j.video.cleared_segments);
    S.video = j.video;
    if (cleared) { S.segments = []; S.result = null; }
    showVideo();
    renderSegments();
    showResult();
    setStatus(cleared
      ? "Yeni soru görseli yüklendi; önceki anlatım adımları sıfırlandı. “AI ile taslak yaz” ile çözümünü hazırlatabilirsin."
      : "", cleared ? "ok" : undefined);
    await refreshSettingsFromState();
  } catch (e) {
    setStatus("Yükleme başarısız: " + e.message, "err");
  }
}

// ---------------------------------------------------------------- kamera
let camStream = null;
async function openCamera() {
  $("#cam-modal").hidden = false;
  $("#cam-status").textContent = "";
  try {
    camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
    const v = $("#cam-video");
    v.srcObject = camStream;
    await v.play();
  } catch (e) {
    $("#cam-status").textContent = "Kamera açılamadı: " + e.message +
      " (tarayıcı izinlerini ve kameranın bağlı olduğunu kontrol et)";
  }
}
function closeCamera() {
  if (camStream) { camStream.getTracks().forEach((t) => t.stop()); camStream = null; }
  $("#cam-modal").hidden = true;
}
function captureCamera() {
  const v = $("#cam-video");
  if (!v.videoWidth) { $("#cam-status").textContent = "Kamera henüz hazır değil…"; return; }
  const c = document.createElement("canvas");
  c.width = v.videoWidth; c.height = v.videoHeight;
  c.getContext("2d").drawImage(v, 0, 0);
  c.toBlob((blob) => {
    if (!blob) return;
    const f = new File([blob], "kamera_" + Date.now() + ".png", { type: "image/png" });
    closeCamera();
    uploadVideo(f);
  }, "image/png");
}

async function resetAll() {
  if (busy) return;
  if (!confirm("Seçili soru görseli ve tüm anlatım adımları silinecek. Emin misin?")) return;
  try {
    await api("/api/reset", {});
    S.video = null; S.segments = []; S.result = null; S.fit = 1;
    $("#video-path").value = "";
    const img = $("#video-img");
    img.hidden = true; img.removeAttribute("src");
    $("#video-wrap").hidden = true;
    $("#video-info").textContent = "";
    renderSegments();
    showResult();
    setStatus("Temizlendi — yeni bir soru görseli seçebilirsin.", "ok");
  } catch (e) {
    setStatus("Temizlenemedi: " + e.message + " (sunucuyu yeniden başlatmayı deneyin)", "err");
    const b = $("#produce-status");
    if (b) b.scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

// ---------------------------------------------------------------- segments
function newSegId() {
  return "s" + Math.random().toString(36).slice(2, 9);
}

// Tahtaya yazılacak metni, videodaki görünüme yakın biçimde (üs, kesir) gösterir.
function mathPreviewHTML(text) {
  const raw = (text || "").trim();
  if (!raw) return '<span class="math-auto">otomatik: seslendirmeden yazılır</span>';
  if (raw === "-" || raw === "–" || raw === "—") return '<span class="math-auto">bu adımda ekrana yazı yok</span>';
  let s = raw.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const atom = "(\\([^()]*\\)|[0-9]+(?:[.,][0-9]+)?)";
  s = s.replace(new RegExp(atom + "\\s*\\/\\s*" + atom, "g"), (m, a, b) =>
    '<span class="frac"><span class="fnum">' + a.replace(/[()]/g, "") +
    '</span><span class="fden">' + b.replace(/[()]/g, "") + "</span></span>");
  s = s.replace(/\^\s*(\([^()]*\)|[-+]?[0-9]+)/g, (m, e) => "<sup>" + e.replace(/[()]/g, "") + "</sup>");
  s = s.replace(/\*/g, "·");
  return s;
}

function renderSegments() {
  const wrap = $("#segments");
  wrap.innerHTML = "";
  S.segments.forEach((seg, i) => wrap.appendChild(segCard(seg, i)));
  renderRenderButton();
}

function segCard(seg, idx) {
  const card = el("div", "seg");
  card.dataset.id = seg.id;

  const head = el("div", "seg-head");
  head.appendChild(el("span", "seg-no", String(idx + 1)));
  head.appendChild(el("span", "spacer"));

  const bUp = el("button", "btn", "↑");
  bUp.title = "Yukarı taşı";
  bUp.onclick = () => { if (idx > 0) { const t = S.segments[idx - 1]; S.segments[idx - 1] = seg; S.segments[idx] = t; renderSegments(); saveSegments(true); } };
  head.appendChild(bUp);

  const bDown = el("button", "btn", "↓");
  bDown.title = "Aşağı taşı";
  bDown.onclick = () => { if (idx < S.segments.length - 1) { const t = S.segments[idx + 1]; S.segments[idx + 1] = seg; S.segments[idx] = t; renderSegments(); saveSegments(true); } };
  head.appendChild(bDown);

  const bRe = el("button", "btn", "🔁");
  bRe.title = "Bu adımı yeniden oku (yeni ton)";
  bRe.onclick = () => resynthOne(seg);
  head.appendChild(bRe);

  const bDel = el("button", "btn", "✕");
  bDel.title = "Bu adımı sil";
  bDel.onclick = () => {
    S.segments = S.segments.filter((s) => s !== seg);
    renderSegments();
    saveSegments(true);
  };
  head.appendChild(bDel);
  card.appendChild(head);

  const ta = el("textarea");
  ta.rows = Math.min(6, Math.max(2, Math.ceil((seg.text || "").length / 90) + 1));
  ta.placeholder = "Çözüm adımını yaz…  ör. 4^4 / 4^1 = 4^3";
  ta.value = seg.text || "";
  ta.addEventListener("input", () => {
    seg.text = ta.value;
    scheduleSave();
  });
  card.appendChild(ta);

  const dl = el("label", "seg-display");
  dl.appendChild(el("span", "seg-display-label", '✍️ Tahtaya yazılacak (boş = otomatik, "-" = yazma)'));
  const da = el("textarea", "seg-display-input");
  da.rows = 1;
  da.placeholder = "ör. 4^4 / 4 = 4^3";
  da.value = seg.display || "";
  const dp = el("div", "math-preview");
  dp.innerHTML = mathPreviewHTML(seg.display || "");
  da.addEventListener("input", () => {
    seg.display = da.value;
    dp.innerHTML = mathPreviewHTML(da.value);
    scheduleSave();
  });
  dl.appendChild(da);
  dl.appendChild(dp);
  card.appendChild(dl);

  const row = el("div", "row between small");
  const lab = el("label");
  lab.appendChild(el("span", "", "Başlangıç"));
  const inp = el("input", "seg-start");
  inp.type = "number";
  inp.step = "0.05";
  inp.min = "0";
  inp.placeholder = "otomatik";
  if (seg.start !== null && seg.start !== undefined && seg.start !== "") inp.value = Number(seg.start).toFixed(2);
  inp.onchange = () => {
    seg.start = inp.value === "" ? null : Number(inp.value);
    saveSegments(true);
  };
  lab.appendChild(inp);
  lab.appendChild(el("span", "muted", "sn"));
  row.appendChild(lab);
  row.appendChild(el("span", "seg-dur muted", seg.dur ? `süre: ${(Number(seg.dur) / (S.fit || 1)).toFixed(2)} sn` : ""));
  card.appendChild(row);

  const prev = el("div", "seg-preview");
  prev.innerHTML = "";
  prev.appendChild(el("b", "", "Okunuş: "));
  prev.appendChild(el("span", "", seg.spoken || seg.text || "…"));
  card.appendChild(prev);

  if (seg.token) {
    const au = el("audio");
    au.controls = true;
    au.preload = "metadata";
    au.src = `/api/media?k=${seg.token}`;
    card.appendChild(au);
  }
  return card;
}

let saveTimer = null;
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => saveSegments(false), 700);
}

async function saveSegments(structural) {
  try {
    const r = await api("/api/segments", {
      segments: S.segments.map((s) => ({
        id: s.id, text: s.text || "", start: s.start,
        display: (s.display && s.display.trim()) ? s.display : null,
      })),
    });
    // sunucudan dönen okunuş/durum bilgilerini yerel kopyaya işle
    const byId = new Map(S.segments.map((s) => [s.id, s]));
    for (const rs of r.segments) {
      const s = byId.get(rs.id);
      if (!s) continue;
      s.spoken = rs.spoken;
      s.dur = rs.dur;
      s.token = rs.token;
      s.model_text = rs.model_text;
      updateSegMeta(s);
    }
    // yeni eklenen/silinen olduysa baştan çiz
    if (r.segments.length !== S.segments.length) {
      S.segments = r.segments;
      renderSegments();
    } else if (structural === true) {
      renderSegments();
    }
  } catch (e) {
    setStatus("Adımlar kaydedilemedi: " + e.message, "err");
  }
}

function updateSegMeta(seg) {
  const card = document.querySelector(`.seg[data-id="${seg.id}"]`);
  if (!card) return;
  const dur = card.querySelector(".seg-dur");
  if (dur) dur.textContent = seg.dur ? `süre: ${(Number(seg.dur) / (S.fit || 1)).toFixed(2)} sn` : "";
  const prev = card.querySelector(".seg-preview span:last-child");
  if (prev) prev.textContent = seg.spoken || seg.text || "…";
  if (seg.token && !card.querySelector("audio")) {
    const au = document.createElement("audio");
    au.controls = true;
    au.preload = "metadata";
    au.src = `/api/media?k=${seg.token}`;
    card.appendChild(au);
  }
  renderRenderButton();
}

function allSynthDone() {
  const real = S.segments.filter((s) => (s.text || "").trim());
  return real.length > 0 && real.every((s) => s.token);
  // (token: son üretimden kalan dosya; metin değişmediyse geçerli)
}

function canSave() {
  return !!(S.result && S.result.mp4 && !S.result.saved);
}

function renderRenderButton() {
  if (busy) return;
  $("#btn-render").disabled = !allSynthDone();
  const bs = $("#btn-save");
  if (bs) bs.disabled = !canSave();
}

function autoTime() {
  const gap = Math.max(0.05, Number($("#opt-gap").value) || 0.2);
  const durs = S.segments.map((s) => s.dur || ((s.text || "").length * 0.075 + 0.4));
  let t = 0;
  S.segments.forEach((seg, i) => {
    seg.start = Math.round(t * 100) / 100;
    t += durs[i] + gap;
    const card = document.querySelector(`.seg[data-id="${seg.id}"]`);
    const inp = card && card.querySelector(".seg-start");
    if (inp) inp.value = seg.start.toFixed(2);
  });
  saveSegments(true);
}

// ---------------------------------------------------------------- üretim
async function aiDraft() {
  if (busy) return;
  if (!S.video) { setStatus("Önce bir soru görseli seç.", "err"); return; }
  if (S.segments.some((s) => (s.text || "").trim()) &&
      !confirm("Mevcut anlatım adımları silinip yerine AI taslağı yazılacak. Devam edilsin mi?")) return;
  setBusy(true, "🤖 AI soruyu inceliyor ve çözüyor… (genelde 20-60 sn; internet gerekir, sabret)");
  try {
    const r = await api("/api/ai_draft", {});
    S.segments = r.segments || [];
    renderSegments();
    setBusy(false,
      `AI taslağı hazır ✅ (${Math.round(r.seconds)} sn). ` +
      "Adımları kontrol et, gerekirse düzelt; sonra “Sesleri oluştur”a bas.", "ok");
  } catch (e) {
    setBusy(false, "AI taslağı oluşturulamadı: " + e.message, "err");
  }
}

async function synthAll() {
  if (busy) return;
  const vox = (S.settings.tts_motor || "antalia") === "voxcpm";
  setBusy(true, vox
    ? "VoxCPM2 üretiyor… (1 sn ses ≈ 20 sn; uzun metinde uzun sürer, sabret)"
    : "Sesler üretiliyor… (model her adım için birkaç saniye çalışır, sabret)");
  try {
    const r = await api("/api/synth", {});
    S.segments = r.segments;
    S.fit = Number(r.fit_speed) || 1;
    renderSegments();
    const total = r.total || S.segments.reduce((a, s) => a + (s.dur || 0), 0);
    setBusy(false, `Sesler hazır · toplam ${total.toFixed(1)} sn. Başlangıçlar otomatik dizildi.`, "ok");
  } catch (e) {
    setBusy(false, "Üretim hatası: " + e.message, "err");
  }
}

async function resynthOne(seg) {
  if (busy) return;
  if (!(seg.text || "").trim()) { setStatus("Bu adımda okunacak metin yok.", "err"); return; }
  setBusy(true, "Bu adım yeni tonla okunuyor…");
  try {
    const r = await api("/api/resynth", { id: seg.id, seed: Math.floor(Math.random() * 100000) });
    const s = S.segments.find((x) => x.id === seg.id);
    if (s && r.segment) { s.dur = r.segment.dur; s.token = r.segment.token; s.model_text = r.segment.model_text; }
    renderSegments();
    setBusy(false, "Adım yeni tonla okundu ✅ (zamanlamayı “⏱ Önerilen zamanlama” ile tazeleyebilirsin)", "ok");
  } catch (e) {
    setBusy(false, "Yeniden okuma hatası: " + e.message, "err");
  }
}

async function renderAll() {
  if (busy) return;
  const penMode = S.settings.pen_style !== false;
  setBusy(true, penMode
    ? "Ses ekleniyor — çözüm, soru görselinin üzerine kalemle yazılıyor (bu adım biraz sürebilir)…"
    : "Ses ekleniyor — çözüm adımları panellerde hazırlanıyor (bu adım biraz sürebilir)…");
  try {
    const r = await api("/api/render", {});
    S.fit = Number(r.fit_speed) || 1;
    // sonuç doğrudan yanıttan gelir; önizleme henüz kaydedilmemiş olabilir
    if (r.result) { S.result = r.result; showResult(); }
    try { await refreshState(); } catch (e) { /* durum tazelenemedi; sonuç yine de hazır */ }
    const w = $("#result-warnings");
    if (r.warnings && r.warnings.length) {
      w.hidden = false;
      w.textContent = r.warnings.join("\n");
    } else {
      w.hidden = true;
    }
    setBusy(false, `Video hazır 🎬  Ses: ${Number(r.total).toFixed(1)} sn · önizleme aşağıda — beğendiysen 💾 Kaydet'e bas.`, "ok");
  } catch (e) {
    setBusy(false, "Kayıt hatası: " + e.message, "err");
  }
}

async function saveAll() {
  if (busy || !canSave()) return;
  setBusy(true, "Dosyalar kaydediliyor…");
  try {
    const r = await api("/api/save", {});
    if (S.result) S.result.saved = r.saved;
    showResult();
    setBusy(false, `Kaydedildi ✅ ${r.saved.dir}`, "ok");
  } catch (e) {
    setBusy(false, "Kaydetme hatası: " + e.message, "err");
  }
}

function showResult() {
  const res = S.result;
  const box = $("#result");
  if (!res) { box.hidden = true; return; }
  box.hidden = false;
  const setLink = (a, item, name) => {
    if (item && item.token) {
      a.href = `/api/media?k=${item.token}&dl=1&name=${encodeURIComponent(name)}`;
      a.download = name;
      a.style.display = "";
    } else a.style.display = "none";
  };
  setLink($("#dl-mp4"), res.mp4, (S.video ? S.video.name.replace(/\.[^.]+$/, "") : "video") + "_seslendirmeli.mp4");
  setLink($("#dl-wav"), res.wav, "ses.wav");
  setLink($("#dl-mp3"), res.mp3, "ses.mp3");
  if (res.txt) { $("#dl-txt").href = "/api/narration?dl=1"; $("#dl-txt").style.display = ""; }
  const ov = $("#out-video");
  if (res.mp4 && res.mp4.token) { ov.hidden = false; ov.src = `/api/media?k=${res.mp4.token}`; }
  const oa = $("#out-audio");
  if (res.wav && res.wav.token) { oa.hidden = false; oa.src = `/api/media?k=${res.wav.token}`; }
  const sn = $("#result-saved");
  if (sn) {
    const saved = res.saved;
    sn.hidden = !saved;
    if (saved) sn.textContent = `💾 Kaydedildi: ${saved.dir}`;
  }
}

// ---------------------------------------------------------------- durum / ayarlar
async function refreshState() {
  const st = await api("/api/state");
  S.engine = st.engine || S.engine;
  S.vox = st.vox || S.vox;
  S.vox_sesler = st.vox_sesler || S.vox_sesler;
  S.settings = st.settings || S.settings;
  S.video = st.video || S.video;
  S.result = st.result || S.result;
  S.fit = Number(st.fit_speed) || 1;
  if (!S.segments.length && st.segments && st.segments.length) {
    S.segments = st.segments;
  } else if (st.segments && st.segments.length) {
    // sunucudaki üretim bilgileriyle eşleştir
    const local = new Map(S.segments.map((s) => [s.id, s]));
    S.segments = st.segments.map((rs) => {
      const ls = local.get(rs.id);
      return ls ? { ...rs, text: ls.text, display: ls.display ?? rs.display } : rs;
    });
  }
  applyBadges(st.ffmpeg);
  applySettingsUI();
  if (S.video) showVideo();
  renderSegments();
  showResult();
}

function applyBadges(ffmpegOk) {
  const be = $("#badge-engine");
  be.className = "badge";
  const voxSecili = (S.settings.tts_motor || "antalia") === "voxcpm";
  if (voxSecili) {
    const v = S.vox || { state: "off" };
    if (v.state === "ready") {
      be.classList.add("ok");
      be.textContent = "Motor: VoxCPM2 hazır";
    } else if (v.state === "error") {
      be.classList.add("err");
      be.textContent = "VoxCPM2: " + (v.message || "").slice(0, 60);
    } else {
      be.classList.add("loading");
      be.textContent = "VoxCPM2: " + (v.state || "?");
    }
  } else if (S.engine.state === "ready") {
    be.classList.add("ok");
    be.textContent = "Motor: hazır";
  } else if (S.engine.state === "starting") {
    be.classList.add("loading");
    be.textContent = "Motor: başlatılıyor… (ilk sefer 10–20 sn)";
  } else if (S.engine.state === "error") {
    be.classList.add("err");
    be.textContent = "Motor hatası: " + (S.engine.message || "").slice(0, 60);
  } else {
    be.textContent = "Motor: " + S.engine.state;
  }
  const bf = $("#badge-ffmpeg");
  bf.className = "badge" + (ffmpegOk ? " ok" : " err");
  bf.textContent = ffmpegOk ? "ffmpeg: hazır" : "ffmpeg bulunamadı!";
  setBusy(busy); // düğme durumları
}

function applySettingsUI() {
  const s = S.settings;
  const tm = $("#opt-ttsmotor");
  if (tm) tm.value = s.tts_motor || "antalia";
  const vs = $("#opt-voxses");
  if (vs) {
    const liste = S.vox_sesler || [];
    const imza = liste.map((v) => v.kimlik).join("|");
    if (vs.dataset.imza !== imza) {
      vs.innerHTML = liste.map((v) => `<option value="${v.kimlik}">${v.ad}</option>`).join("");
      vs.dataset.imza = imza;
    }
    if (s.vox_ses && liste.some((v) => v.kimlik === s.vox_ses)) vs.value = s.vox_ses;
  }
  $("#opt-speed").value = s.speed;
  $("#opt-steps").value = String(s.steps);
  $("#opt-gap").value = s.gap;
  $("#opt-seed").value = (s.seed ?? 0);
  $("#opt-outdir").value = s.out_dir || "";
  const op = $("#opt-pen");
  if (op) op.checked = s.pen_style !== false;
  $("#opt-ailen").value = s.ai_length || "dengeli";
  $("#opt-aiaud").value = s.ai_audience || "ogrenci";
  $("#opt-aihook").value = s.ai_hook || "merak";
}

async function saveSettings() {
  S.settings = {
    speed: Number($("#opt-speed").value) || 0.95,
    steps: Number($("#opt-steps").value) || 8,
    gap: Number($("#opt-gap").value) || 0.2,
    seed: Math.max(0, Math.min(9999, Number($("#opt-seed").value) || 0)),
    out_dir: $("#opt-outdir").value.trim(),
    tts_motor: $("#opt-ttsmotor") ? $("#opt-ttsmotor").value : "antalia",
    vox_ses: $("#opt-voxses") ? $("#opt-voxses").value : "",
    pen_style: $("#opt-pen") ? $("#opt-pen").checked : true,
    ai_length: $("#opt-ailen").value,
    ai_audience: $("#opt-aiaud").value,
    ai_hook: $("#opt-aihook").value,
  };
  try { await api("/api/settings", S.settings); } catch (e) { setStatus("Ayar kaydedilemedi: " + e.message, "err"); }
}

async function refreshSettingsFromState() {
  const st = await api("/api/state");
  S.settings = st.settings || S.settings;
  applySettingsUI();
}

function copyText(text, btn) {
  const done = () => {
    if (!btn) return;
    const old = btn.textContent;
    btn.textContent = "✓ Kopyalandı";
    btn.disabled = true;
    setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1500);
  };
  const fallback = () => {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.top = "-1000px";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    ta.setSelectionRange(0, ta.value.length);
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    ta.remove();
    if (ok) done();
  };
  if (navigator.clipboard && window.isSecureContext) {
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else {
    fallback();
  }
}

async function loadNet() {
  const box = $("#net-info");
  if (!box) return;
  try {
    const n = await api("/api/net");
    box.hidden = false;
    box.innerHTML = "";
    if (!n.bound_all) {
      box.appendChild(el("span", "muted",
        "Telefondan kullanmak için: Durdur.bat → Baslat-telefon.bat ile başlat."));
      return;
    }
    const ts = (n.ts_urls || [])[0];
    const lan = (n.urls || [])[0];
    const addr = ts || lan;
    if (!addr) return;
    box.appendChild(el("span", "", ts ? "📱 Her yerden:" : "📱 Telefondan:"));
    box.appendChild(el("b", "", addr));
    const cp = el("button", "btn tiny", "Kopyala");
    cp.type = "button";
    cp.onclick = () => copyText(addr, cp);
    box.appendChild(cp);
    if (ts && lan) box.appendChild(el("span", "muted small", "· evde: " + lan));
    box.appendChild(el("span", "muted small",
      n.password_required ? "· şifre: work\\password.txt" : "· şifre yok!"));
  } catch (e) { /* yoksay */ }
}

function pollEngine() {
  clearTimeout(enginePollTimer);
  const delay = S.engine.state === "ready" ? 15000 : 2500;
  enginePollTimer = setTimeout(async () => {
    try {
      const st = await api("/api/state");
      S.engine = st.engine || S.engine;
      applyBadges(st.ffmpeg);
    } catch (e) { /* yoksay */ }
    pollEngine();
  }, delay);
}

// ---------------------------------------------------------------- klasör gezme
let M = { dir: "", parent: null, sel: null };

async function openModal(startDir) {
  $("#modal").hidden = false;
  await browse(startDir || (S.video ? S.video.path : "") || S.settings.out_dir || "");
}

async function browse(dir) {
  const r = await api("/api/browse?dir=" + encodeURIComponent(dir || ""));
  M.dir = r.dir; M.parent = r.parent; M.sel = null;
  $("#modal-path").textContent = r.drives_mode ? "Sürücü seç:" : r.dir;
  const list = $("#modal-list");
  list.innerHTML = "";
  $("#modal-pick").disabled = true;
  for (const d of r.dirs) {
    const it = el("div", "modal-item");
    it.appendChild(el("span", "ico", "📁"));
    it.appendChild(el("span", "", d.name || d.path));
    it.onclick = () => browse(d.path);
    list.appendChild(it);
  }
  for (const f of r.files) {
    const it = el("div", "modal-item");
    it.appendChild(el("span", "ico", "🖼️"));
    it.appendChild(el("span", "", f.name));
    it.appendChild(el("span", "size", (f.size / 1048576).toFixed(1) + " MB"));
    it.onclick = () => {
      for (const o of list.querySelectorAll(".modal-item.sel")) o.classList.remove("sel");
      it.classList.add("sel");
      M.sel = f.path;
      $("#modal-pick").disabled = false;
    };
    it.ondblclick = () => { M.sel = f.path; $("#modal").hidden = true; $("#video-path").value = f.path; openVideoFromPath(); };
    list.appendChild(it);
  }
}

// ---------------------------------------------------------------- olaylar / başlat
$("#btn-open-video").onclick = openVideoFromPath;
$("#video-path").addEventListener("keydown", (e) => { if (e.key === "Enter") openVideoFromPath(); });
$("#video-file").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (f) uploadVideo(f);
  e.target.value = "";
});
$("#btn-browse").onclick = () => openModal("");
$("#modal-close").onclick = () => { $("#modal").hidden = true; };
$("#modal-up").onclick = () => { if (M.parent) browse(M.parent); else browse(""); };
$("#modal-pick").onclick = () => {
  if (!M.sel) return;
  $("#modal").hidden = true;
  $("#video-path").value = M.sel;
  openVideoFromPath();
};
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").hidden = true; });

$("#btn-add-seg").onclick = () => {
  S.segments.push({ id: newSegId(), text: "", start: null, dur: null, token: null, spoken: "", display: "" });
  renderSegments();
  const cards = document.querySelectorAll("#segments .seg textarea");
  if (cards.length) cards[cards.length - 1].focus();
};
$("#btn-auto-time").onclick = autoTime;
$("#btn-ai").onclick = aiDraft;
$("#btn-synth").onclick = synthAll;
$("#btn-render").onclick = renderAll;
$("#btn-save").onclick = saveAll;
$("#btn-openfolder").onclick = () => {
  const dir = S.result
    ? ((S.result.saved && S.result.saved.dir) || (S.settings && S.settings.out_dir) || S.result.dir)
    : "";
  if (dir) api("/api/openfolder", { path: dir }).catch(() => {});
};
$("#btn-camera").onclick = openCamera;
$("#cam-close").onclick = closeCamera;
$("#cam-shot").onclick = captureCamera;
$("#cam-modal").addEventListener("click", (e) => { if (e.target.id === "cam-modal") closeCamera(); });
$("#btn-reset").onclick = resetAll;

// ---- sürükle-bırak ve panodan yapıştırma ile soru görseli ----
function firstImageFromDataTransfer(dt) {
  if (!dt) return null;
  if (dt.files && dt.files.length) {
    for (const f of dt.files) if (f && f.type && f.type.startsWith("image/")) return f;
  }
  if (dt.items) {
    for (const it of dt.items) {
      if (it.kind === "file") {
        const f = it.getAsFile();
        if (f && f.type && f.type.startsWith("image/")) return f;
      }
    }
  }
  return null;
}
function hasFiles(dt) {
  if (!dt) return false;
  try { return Array.from(dt.types || []).includes("Files"); } catch (e) { return false; }
}
let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  if (!hasFiles(e.dataTransfer)) return;
  e.preventDefault();
  dragDepth++;
  document.body.classList.add("drop-active");
});
window.addEventListener("dragover", (e) => {
  if (hasFiles(e.dataTransfer)) e.preventDefault();
});
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) document.body.classList.remove("drop-active");
});
window.addEventListener("drop", (e) => {
  if (!hasFiles(e.dataTransfer)) return;
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove("drop-active");
  const f = firstImageFromDataTransfer(e.dataTransfer);
  if (f) uploadVideo(f);
});
window.addEventListener("paste", (e) => {
  const f = firstImageFromDataTransfer(e.clipboardData);
  if (f) { e.preventDefault(); uploadVideo(f); }
});

for (const id of ["#opt-speed", "#opt-steps", "#opt-gap", "#opt-pen", "#opt-seed", "#opt-ailen", "#opt-aiaud", "#opt-aihook", "#opt-ttsmotor", "#opt-voxses"]) {
  $(id).addEventListener("change", saveSettings);
}
$("#opt-outdir").addEventListener("change", saveSettings);
$("#opt-ttsmotor").addEventListener("change", () => setBusy(busy));
$("#btn-outdir").onclick = async () => {
  const cur = $("#opt-outdir").value;
  const r = await api("/api/browse?dir=" + encodeURIComponent(cur || "")).catch(() => null);
  if (!r) return;
  // basit istem: seçili klasörü doğrudan yaz
  $("#opt-outdir").value = r.dir || cur;
  saveSettings();
};

window.addEventListener("beforeunload", () => { clearTimeout(saveTimer); });

(async function boot() {
  try {
    await refreshState();
  } catch (e) {
    setStatus("Sunucuya ulaşılamadı: " + e.message, "err");
  }
  loadNet();
  pollEngine();
})();
