/* Shared reel runtime. Needs globals TL (timeline.json) and CAPS (Roman caption words per beat),
   plus gsap. A topic scene calls Reel.build(fn) where fn(R) adds tweens to R.master.
   Everything is a pure function of t — no timers, no randomness. */
(function () {
  const LEAD = 0.35;                       // hook entrances are already in motion at frame 0
  const P = t => t + LEAD;
  const B = Object.fromEntries(TL.beats.map(b => [b.id, b]));
  const norm = s => s.normalize('NFC').toLowerCase().replace(/[.,?!।:;]/g, '');
  // time of a spoken word in a beat: index, or the word text (nth occurrence via [word, n])
  const wt = (id, w) => {
    const ws = B[id].words;
    let i = w;
    if (typeof w !== 'number') {
      const [txt, n] = Array.isArray(w) ? w : [w, 0];
      const hits = ws.map((x, k) => norm(x.w) === norm(txt) ? k : -1).filter(k => k >= 0);
      i = hits[n] ?? -1;
    }
    if (i < 0 || !ws[i]) throw new Error(`word ${JSON.stringify(w)} not in beat ${id}`);
    return ws[i].t;
  };
  const master = gsap.timeline({ paused: true });
  const $ = s => document.querySelector(s);

  // ---- headers (.hdr#h-<beatId>) ----
  function hdrInit() {
    gsap.set('.hdr .ln>span', { yPercent: 110 });
    gsap.set('.hdr .sub, .hdr .step', { opacity: 0, y: 24 });
  }
  function hdrIn(id, at = P(B[id].start)) {
    master.to(`#h-${id} .ln>span`, { yPercent: 0, duration: 0.7, ease: 'expo.out', stagger: 0.07 }, at);
    master.to(`#h-${id} .step`, { opacity: 1, y: 0, duration: 0.5, ease: 'expo.out' }, at);
    master.to(`#h-${id} .sub`, { opacity: 1, y: 0, duration: 0.6, ease: 'expo.out' }, at + 0.25);
  }
  function hdrOut(id) {
    const at = P(B[id].end) - 0.32;
    master.to(`#h-${id} .ln>span`, { yPercent: -110, duration: 0.3, ease: 'power2.in' }, at);
    master.to(`#h-${id} .sub, #h-${id} .step`, { opacity: 0, y: -16, duration: 0.3, ease: 'power2.in' }, at);
  }
  // pop in / out helpers
  const popIn = (sel, at, o = {}) => master.to(sel, Object.assign({ opacity: 1, scale: 1, y: 0, x: 0, duration: 0.55, ease: 'back.out(1.7)' }, o), at);
  const fadeOut = (sel, at, o = {}) => master.to(sel, Object.assign({ opacity: 0, duration: 0.3, ease: 'power2.in' }, o), at);
  // typing: element must be a single-line .code with known text length; caret optional
  function typeText(sel, nChars, at, caretSel, caretX0, caretY, cw) {
    const d = Math.min(1.1, nChars * 0.05);
    master.to(sel, { clipPath: 'inset(0 0% 0 0)', duration: d, ease: `steps(${nChars})` }, at);
    if (caretSel) {
      master.set(caretSel, { x: caretX0, y: caretY, opacity: 1 }, at);
      master.to(caretSel, { x: caretX0 + nChars * cw + 4, duration: d, ease: `steps(${nChars})` }, at);
    }
    return d;
  }
  const charWidth = (font = '500 38px "DM Mono"') => {
    const c = document.createElement('canvas').getContext('2d'); c.font = font; return c.measureText('MMMMMMMMMM').width / 10;
  };
  // counter: writes formatted number into el from t (call from build via onUpdate-free approach)
  const counters = [];
  function counter(sel, from, to, at, dur, fmt = n => Math.round(n).toLocaleString('en-IN')) {
    counters.push({ el: $(sel), from, to, at, dur, fmt });
  }
  // several counters may target one element: use the latest one that has started (or the earliest if none has)
  function drawCounters(t) {
    const pt = P(t), pick = new Map();
    for (const c of counters) {
      const cur = pick.get(c.el);
      if (!cur) { pick.set(c.el, c); continue; }
      const started = c.at <= pt, curStarted = cur.at <= pt;
      if (started && (!curStarted || c.at >= cur.at)) pick.set(c.el, c);
      else if (!started && !curStarted && c.at < cur.at) pick.set(c.el, c);
    }
    for (const c of pick.values()) {
      const p = Math.max(0, Math.min(1, (pt - c.at) / c.dur));
      const e = 1 - Math.pow(1 - p, 3);
      c.el.textContent = c.fmt(c.from + (c.to - c.from) * e);
    }
  }
  // per-frame hooks (for things like looping dots) — fn(t)
  const frameFns = [];
  const everyFrame = fn => frameFns.push(fn);

  // ---- captions ----
  const GROUPS = [];
  TL.beats.forEach((b, bi) => {
    const cw = CAPS[bi]; let g = null;
    b.words.forEach((w, i) => {
      const text = cw[i] ?? w.w;
      if (!g) { g = { beat: bi, words: [] }; GROUPS.push(g); }
      g.words.push({ text, t: w.t });
      const chars = g.words.reduce((a, x) => a + x.text.length + 1, 0);
      if (/[.,?!:]$/.test(text) || g.words.length >= 4 || chars > 17) g = null;
    });
  });
  GROUPS.forEach((g, i) => {
    g.start = g.words[0].t - 0.06;
    const nx = GROUPS[i + 1];
    g.end = nx && nx.beat === g.beat ? nx.words[0].t - 0.06 : TL.beats[g.beat].end;
  });
  let curGroup = -2;
  function drawCaptions(t) {
    const capbox = $('#capbox');
    const gi = GROUPS.findIndex(g => t >= g.start && t < g.end);
    if (gi !== curGroup) {
      curGroup = gi;
      capbox.innerHTML = gi < 0 ? '' : GROUPS[gi].words.map(w => `<span>${w.text}</span>`).join('');
      capbox.style.visibility = gi < 0 ? 'hidden' : 'visible';
    }
    if (gi < 0) return;
    const g = GROUPS[gi];
    [...capbox.children].forEach((el, i) => {
      const w = g.words[i], nxt = g.words[i + 1];
      const active = t >= w.t - 0.03 && (!nxt || t < nxt.t - 0.03);
      const k = Math.max(0, 1 - (t - w.t) / 0.18);
      el.style.color = active ? '#FFC857' : '#E8EEF8';
      el.style.opacity = t >= w.t - 0.03 ? 1 : 0.5;
      el.style.transform = `scale(${active ? 1 + 0.12 * k : 1})`;
    });
    const e = Math.min(1, (t - g.start) / 0.12);
    capbox.style.transform = `translateY(${(1 - e) * 14}px)`;
  }

  // ---- ambient background ----
  function drawBg(t) {
    $('#dots').style.transform = `translate(${(t * 7) % 40}px, ${(t * 11) % 40}px)`;
    $('#g1').style.transform = `translate(${Math.sin(t * 0.3) * 40}px,${Math.cos(t * 0.25) * 30}px) scale(${1 + 0.06 * Math.sin(t * 0.9)})`;
    $('#g2').style.transform = `translate(${Math.cos(t * 0.27) * 40}px,${Math.sin(t * 0.33) * 30}px) scale(${1 + 0.07 * Math.sin(t * 0.7 + 2)})`;
    $('#g1').style.opacity = 0.85 + 0.15 * Math.sin(t * 0.9);
    const b = TL.beats.find(b => t >= b.start && t < b.end) || TL.beats[TL.beats.length - 1];
    const p = Math.min(1, (t - b.start) / (b.end - b.start));
    $('#stage').style.transform = `scale(${1 + 0.018 * p})`;
    document.querySelectorAll('.caret').forEach(c => c.style.visibility = (Math.floor(t * 2.2) % 2 === 0) ? 'visible' : 'hidden');
  }

  // ---- reusable pieces ----
  const CYL = `<svg viewBox="0 0 360 480"><defs><linearGradient id="cg" x1="0" x2="1"><stop offset="0" stop-color="#1d3566"/><stop offset=".5" stop-color="#2a4c8f"/><stop offset="1" stop-color="#16294f"/></linearGradient></defs>
  <path d="M20 70 V410 A160 50 0 0 0 340 410 V70" fill="url(#cg)" stroke="#4F8CFF" stroke-width="4"/>
  <path d="M20 185 A160 50 0 0 0 340 185 M20 300 A160 50 0 0 0 340 300" fill="none" stroke="#4F8CFF" stroke-opacity=".6" stroke-width="4"/>
  <ellipse cx="180" cy="70" rx="160" ry="50" fill="#26467f" stroke="#7FB0FF" stroke-width="4"/></svg>`;
  // every empty .dbi becomes a database cylinder (360x480, scale it with gsap)
  document.querySelectorAll('.dbi:empty').forEach(d => d.innerHTML = '<div class="gl"></div>' + CYL);
  // table builder: cols = [{h:'ID', w:140, c:'p'}], rows = [[...]]; row i gets id `${pre}${i}`, cells get class c-<h>
  function table(sel, cols, rows, pre) {
    const el = $(sel); pre = pre || el.id + 'r';
    const cell = (c, v) => `<div style="width:${c.w}px" class="c-${c.h.toLowerCase().replace(/[^a-z0-9]/g, '')} ${c.c || ''}">${v}</div>`;
    el.insertAdjacentHTML('beforeend', `<div class="tr th">${cols.map(c => cell(c, c.h)).join('')}</div>` +
      rows.map((r, i) => `<div class="tr td" id="${pre}${i}">${cols.map((c, k) => cell(c, r[k])).join('')}</div>`).join(''));
  }

  // ---- row animation helpers (call inside build) ----
  // absRows: make .td rows absolutely positioned so they can filter / reorder. Returns state object.
  function absRows(sel) {
    const el = $(sel), rows = [...el.querySelectorAll('.td')];
    const hh = el.querySelector('.th').offsetHeight, rh = rows.length ? rows[0].offsetHeight : 68;
    rows.forEach((r, i) => { r.style.position = 'absolute'; r.style.left = '0'; r.style.width = '100%'; r.style.top = '0'; gsap.set(r, { y: hh + i * rh }); });
    el.style.height = (hh + rows.length * rh + 4) + 'px';
    el._st = { rows, hh, rh, vis: rows.map((_, i) => i) };
    return el._st;
  }
  // filterRows: keep = row indices to keep (original index). Others slide out, kept rows close the gaps.
  function filterRows(sel, keep, at, o = {}) {
    const st = $(sel)._st, gone = st.vis.filter(i => !keep.includes(i));
    gone.forEach((i, k) => master.to(st.rows[i], { x: o.dx || 160, opacity: 0, duration: 0.35, ease: 'power2.in' }, at + k * 0.05));
    const t2 = at + 0.3 + gone.length * 0.05, nv = st.vis.filter(i => keep.includes(i));
    nv.forEach((i, slot) => master.to(st.rows[i], { y: st.hh + slot * st.rh, duration: 0.55, ease: 'expo.out' }, t2));
    master.to(sel, { height: st.hh + nv.length * st.rh + 4, duration: 0.55, ease: 'expo.out' }, t2);
    st.vis = nv; return t2 + 0.55;
  }
  // showRows: bring a set of rows (in given order) back into view
  function showRows(sel, order, at) {
    const st = $(sel)._st;
    order.forEach((i, slot) => { master.set(st.rows[i], { y: st.hh + slot * st.rh }, at); master.to(st.rows[i], { x: 0, opacity: 1, duration: 0.4, ease: 'expo.out' }, at + slot * 0.04); });
    master.to(sel, { height: st.hh + order.length * st.rh + 4, duration: 0.4, ease: 'expo.out' }, at);
    st.vis = order.slice(); return at + 0.5;
  }
  // reorderRows: order = row indices in new top-to-bottom order (must be the visible set)
  // rows that move slide out, jump to their new slot, and cascade back in (never cross / overlap)
  function reorderRows(sel, order, at, dur = 0.8) {
    const st = $(sel)._st, moving = order.filter((i, slot) => st.vis.indexOf(i) !== slot);
    moving.forEach(i => master.to(st.rows[i], { x: 60, opacity: 0, duration: 0.22, ease: 'power2.in' }, at));
    order.forEach((i, slot) => {
      if (!moving.includes(i)) return;
      master.set(st.rows[i], { y: st.hh + slot * st.rh, x: -40 }, at + 0.24);
      master.to(st.rows[i], { x: 0, opacity: 1, duration: 0.35, ease: 'expo.out' }, at + 0.26 + slot * 0.06);
    });
    st.vis = order.slice(); return at + dur;
  }

  let buildFn = null, built = false;
  window.Reel = {
    LEAD, P, B, wt, master, $, CYL, table, absRows, filterRows, showRows, reorderRows, hdrInit, hdrIn, hdrOut, popIn, fadeOut, typeText, charWidth, counter, everyFrame,
    build(fn) { buildFn = fn; },
  };
  window.renderFrame = (t) => {
    if (!built) { built = true; hdrInit(); buildFn(window.Reel); }
    master.seek(P(t), false);
    drawBg(t); drawCounters(t); frameFns.forEach(f => f(t)); drawCaptions(t);
  };
})();
