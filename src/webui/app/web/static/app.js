(() => {
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const el = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v; else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) e.setAttribute(k, v === true ? '' : v);
  }
  kids.flat().forEach(k => k != null && e.append(k.nodeType ? k : document.createTextNode(k)));
  return e;
};

// ------------------------------------------------------------------ state
const S = { schema: null, defaults: {}, state: null, tab: 'swap', widgets: {}, drag: null };
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function api(url, method = 'GET', data, raw) {
  const opt = { method, headers: {} };
  if (data instanceof FormData) opt.body = data;
  else if (data !== undefined) { opt.body = JSON.stringify(data); opt.headers['Content-Type'] = 'application/json'; }
  let r;
  try { r = await fetch(url, opt); } catch (e) { toast('error', 'Connection lost', String(e)); throw e; }
  if (raw) return r;
  let j = {};
  try { j = await r.json(); } catch (e) { /* empty */ }
  if (!r.ok || j.ok === false) { toast('error', 'Error', j.error || r.statusText); throw new Error(j.error || r.statusText); }
  return j;
}
const post = (u, d = {}) => api(u, 'POST', d);

function toast(level, title, message = '') {
  const t = el('div', { class: 'toast ' + level }, el('b', { text: title }), message ? el('span', { text: message }) : null);
  $('#toasts').append(t);
  setTimeout(() => t.remove(), level === 'error' ? 8000 : 4500);
}

// ------------------------------------------------------------------ modal helpers
function modal(content) { const b = $('#modalBox'); b.replaceChildren(content); $('#modal').hidden = false; }
function closeModal() { $('#modal').hidden = true; $('#modalBox').replaceChildren(); }
$('#modal').addEventListener('mousedown', e => { if (e.target.id === 'modal') closeModal(); });

function prompt2(title, fields, okText = 'OK') {
  return new Promise(res => {
    const inputs = fields.map(f => f.type === 'select'
      ? el('select', { id: 'pf_' + f.name }, f.options.map(o => el('option', { value: o, text: o, selected: o === f.value })))
      : el('input', { type: 'text', id: 'pf_' + f.name, value: f.value || '', placeholder: f.placeholder || '' }));
    const done = v => { closeModal(); res(v); };
    const submit = () => done(Object.fromEntries(fields.map((f, i) => [f.name, inputs[i].value])));
    modal(el('div', {}, el('h2', { text: title }),
      fields.map((f, i) => el('div', { class: 'row', style: 'margin-top:8px' }, el('label', { text: f.label, style: 'width:110px' }), inputs[i])),
      el('div', { class: 'actions', style: 'margin-top:12px' },
        el('button', { class: 'btn', text: 'Cancel', onclick: () => done(null) }),
        el('button', { class: 'btn on', text: okText, onclick: submit }))));
    inputs[0].focus();
    inputs.forEach(i => i.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); if (e.key === 'Escape') done(null); }));
  });
}
const confirm2 = (title, text) => new Promise(res => {
  modal(el('div', {}, el('h2', { text: title }), el('p', { text }),
    el('div', { class: 'actions' }, el('button', { class: 'btn', text: 'Cancel', onclick: () => { closeModal(); res(false); } }),
      el('button', { class: 'btn on', text: 'OK', onclick: () => { closeModal(); res(true); } }))));
});

// server-side file browser. mode: dir | media | image | json | file ; multi: allow multiple files
let lastBrowsePath = '';
function browse({ mode = 'file', multi = false, title = 'Select', start = '' }) {
  return new Promise(async res => {
    let cur = start || lastBrowsePath || '';
    const picked = new Set();
    const pathInput = el('input', { type: 'text', id: 'fbPath' });
    const entries = el('div', { class: 'entries' });
    const roots = el('div', { class: 'roots' });
    const done = v => { closeModal(); res(v); };
    const okBtn = el('button', { class: 'btn on', text: mode === 'dir' ? 'Select this folder' : 'Select', onclick: () => {
      if (mode === 'dir') done(pathInput.value);
      else if (picked.size) done([...picked]);
    } });
    async function load(path) {
      let d;
      try { d = await api('/api/fs?mode=' + mode + '&path=' + encodeURIComponent(path || '')); } catch (e) { return; }
      cur = d.path; lastBrowsePath = cur; pathInput.value = cur; picked.clear();
      roots.replaceChildren(...d.roots.map(r => el('button', { class: 'btn sm', text: r, onclick: () => load(r) })));
      const join = n => cur.replace(/[\\/]$/, '') + d.sep + n;
      const rows = [];
      if (d.parent) rows.push(el('div', { class: 'ent', onclick: () => load(d.parent) }, '⬆ ..'));
      d.dirs.forEach(n => rows.push(el('div', { class: 'ent', ondblclick: () => load(join(n)), onclick: () => { if (mode === 'dir') pathInput.value = join(n); } }, '📁 ' + n)));
      d.files.forEach(f => rows.push(el('div', { class: 'ent', onclick: e => {
        const full = join(f.name);
        if (!multi) { picked.clear(); $$('.ent.sel', entries).forEach(x => x.classList.remove('sel')); }
        if (picked.has(full)) { picked.delete(full); e.currentTarget.classList.remove('sel'); } else { picked.add(full); e.currentTarget.classList.add('sel'); }
      }, ondblclick: () => { if (!multi) done([full(f)]); function full(x) { return join(x.name); } } }, '🖼 ' + f.name, el('small', { text: fmtSize(f.size) }))));
      entries.replaceChildren(...rows);
    }
    pathInput.addEventListener('keydown', e => { if (e.key === 'Enter') load(pathInput.value); });
    modal(el('div', { class: 'fb' }, el('h2', { text: title }), roots,
      el('div', { class: 'row' }, pathInput, el('button', { class: 'btn', text: 'Go', onclick: () => load(pathInput.value) }),
        el('button', { class: 'btn', text: 'New folder', onclick: async () => {
          const r = await prompt2('New folder', [{ name: 'n', label: 'Name' }]);
          if (r && r.n) { await post('/api/fs/mkdir', { path: cur.replace(/[\\/]$/, '') + '/' + r.n }); load(cur); }
        } })),
      entries, el('div', { class: 'actions' }, el('button', { class: 'btn', text: 'Cancel', onclick: () => done(null) }), okBtn)));
    load(cur);
  });
}
const fmtSize = n => n > 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB';

// context menu
function ctxMenu(e, items) {
  e.preventDefault();
  const m = $('#ctx');
  m.replaceChildren(...items.map(([t, fn]) => el('button', { text: t, onclick: () => { m.hidden = true; fn(); } })));
  m.hidden = false;
  m.style.left = Math.min(e.clientX, innerWidth - 190) + 'px';
  m.style.top = Math.min(e.clientY, innerHeight - items.length * 32 - 10) + 'px';
}
document.addEventListener('mousedown', e => { if (!e.target.closest('#ctx')) $('#ctx').hidden = true; });

// ------------------------------------------------------------------ parameter widgets
function getVal(name) {
  const st = S.state;
  if (name in st.parameters) return st.parameters[name];
  return st.control[name];
}
function isVisible(w) {
  const req = w.requiredToggleValue;
  if (w.parentToggle) {
    const pt = w.parentToggle;
    let v;
    if (pt.includes('&')) v = pt.split('&').every(p => !!getVal(p.trim()));
    else if (pt.includes('|')) v = pt.split('|').some(p => !!getVal(p.trim()));
    else v = !!getVal(pt.trim());
    if (v !== req) return false;
  }
  if (w.parentSelection) {
    const want = w.requiredSelectionValue;
    const cur = getVal(w.parentSelection);
    if (Array.isArray(want) ? !want.includes(cur) : cur !== want) return false;
  }
  return true;
}

const pending = {};
function sendValue(w, value) {
  const url = w.kind === 'parameter' ? '/api/parameter' : '/api/control';
  clearTimeout(pending[w.name]);
  pending[w.name] = setTimeout(() => {
    api(url, 'POST', { name: w.name, value }).then(r => {
      if (w.kind === 'control' && 'value' in r) S.state.control[w.name] = r.value;
    }).catch(() => {});
  }, w.type === 'slider' || w.type === 'decimal' ? 40 : 0);
  (w.kind === 'parameter' ? S.state.parameters : S.state.control)[w.name] = value;
  if (w.exec === 'change_theme') applyTheme(value);
  refreshVisibility();
}

function buildWidget(w) {
  const def = w.kind === 'parameter' ? w.default : w.default;
  const root = el('div', { class: `w l${w.level} ${w.type === 'toggle' ? 'tog' : ''}`, 'data-name': w.name });
  const label = el('label', { class: 'lbl', text: w.label, title: w.help || '' });
  const rst = el('button', { class: 'rst', title: 'Reset to default', text: '↺' });
  let ctl, set;
  if (w.type === 'toggle') {
    const inp = el('input', { type: 'checkbox' });
    inp.addEventListener('change', () => sendValue(w, inp.checked));
    ctl = el('span', { class: 'sw' }, inp, el('span'));
    set = v => { inp.checked = !!v; };
    root.append(label, ctl);
  } else if (w.type === 'select') {
    const sel = el('select', {}, w.options.map(o => el('option', { value: o, text: o })));
    sel.addEventListener('change', () => sendValue(w, sel.value));
    ctl = el('div', { class: 'ctl' }, sel, rst);
    set = v => { if (![...sel.options].some(o => o.value === v)) sel.append(el('option', { value: v, text: v })); sel.value = v; };
    root.append(label, ctl);
  } else if (w.type === 'text') {
    const t = el('input', { class: 'txt', type: 'text', style: `max-width:${w.width || 130}px` });
    t.addEventListener('input', () => sendValue(w, t.value));
    ctl = el('div', { class: 'ctl' }, t, rst);
    set = v => { if (document.activeElement !== t) t.value = v ?? ''; };
    root.append(label, ctl);
  } else {
    const dec = w.type === 'decimal' ? w.decimals : 0;
    const range = el('input', { type: 'range', min: w.min, max: w.max, step: w.step });
    const num = el('input', { class: 'num', type: 'number', min: w.min, max: w.max, step: w.step });
    const fmt = v => dec ? Number(v).toFixed(dec) : String(Math.round(v));
    range.addEventListener('input', () => { num.value = fmt(range.value); sendValue(w, Number(range.value)); });
    num.addEventListener('change', () => {
      let v = Number(num.value); if (Number.isNaN(v)) v = def;
      v = Math.min(w.max, Math.max(w.min, v)); range.value = v; num.value = fmt(v); sendValue(w, v);
    });
    ctl = el('div', { class: 'ctl' }, range, num, rst);
    set = v => { range.value = v; if (document.activeElement !== num) num.value = fmt(v); };
    root.append(label, ctl);
  }
  rst.addEventListener('click', () => {
    const d = w.default; set(d); sendValue(w, d);
  });
  if (w.type === 'toggle') root.append(rst);
  S.widgets[w.name] = { w, root, set };
  return root;
}

function buildTabs() {
  const tabs = $('#tabs'); tabs.replaceChildren();
  const body = $('#tabBody'); body.replaceChildren();
  S.widgets = {};
  S.schema.tabs.forEach(t => {
    tabs.append(el('button', { 'data-tab': t.id, text: t.title, onclick: () => selectTab(t.id) }));
    const pane = el('div', { class: 'pane', 'data-pane': t.id, hidden: true });
    t.groups.forEach((g, gi) => {
      const widgets = g.widgets.map(buildWidget);
      if (g.title) pane.append(el('details', { class: 'grp', open: gi < 3 || t.id === 'settings' ? true : null }, el('summary', { text: g.title }), el('div', { class: 'gbody' }, widgets)));
      else pane.append(el('div', { class: 'gbody' }, widgets));
    });
    body.append(pane);
  });
  selectTab(S.tab);
}
function selectTab(id) {
  S.tab = id;
  $$('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === id));
  $$('#tabBody .pane').forEach(p => p.hidden = p.dataset.pane !== id);
  $('#faceTools').hidden = id === 'settings';
  try { localStorage.setItem('viso.tab', id); } catch (e) { /* ignore */ }
}
function refreshValues() {
  for (const { w, set } of Object.values(S.widgets)) {
    const v = getVal(w.name); if (v !== undefined) set(v);
  }
  refreshVisibility();
  applyTheme(S.state.control.ThemeSelection);
  $('#outFolder').value = S.state.control.OutputMediaFolder || '';
}
function refreshVisibility() {
  for (const { w, root } of Object.values(S.widgets)) root.classList.toggle('hidden', !isVisible(w));
}
function applyTheme(t) {
  const map = { 'Dark': 'dark', 'Dark-Blue': 'dark-blue', 'Light': 'light' };
  document.documentElement.dataset.theme = map[t] || 'dark';
}

// ------------------------------------------------------------------ lists
function filt(inputId, items, key) {
  const q = ($(inputId).value || '').toLowerCase();
  return q ? items.filter(i => (i[key] || '').toLowerCase().includes(q)) : items;
}
function renderMedia() {
  const box = $('#mediaList'); box.dataset.empty = S.state.loading.media ? 'Loading…' : 'Drop files here, or use the buttons above';
  box.replaceChildren(...filt('#qMedia', S.state.media, 'name').map(m => {
    const c = el('div', { class: 'card' + (S.state.selected_media === m.id ? ' sel' : ''), title: m.path,
      onclick: () => post(`/api/media/${m.id}/select`).catch(() => {}),
      oncontextmenu: e => ctxMenu(e, [['Remove from list', () => api(`/api/media/${m.id}`, 'DELETE')]]) },
      el('img', { src: `/api/thumb/media/${m.id}`, loading: 'lazy' }),
      el('span', { class: 'badge', text: m.type }),
      el('span', { class: 'cap', text: m.name }),
      el('button', { class: 'x', text: '×', onclick: e => { e.stopPropagation(); api(`/api/media/${m.id}`, 'DELETE'); } }));
    return c;
  }));
}
function renderTarget() {
  const box = $('#targetList'); box.dataset.empty = 'No target faces. Use "Find faces".';
  box.replaceChildren(...S.state.target_faces.map(f => el('div', { class: 'card' + (S.state.selected_target_face === f.id ? ' sel' : ''),
    onclick: () => post(`/api/target_faces/${f.id}/select`).catch(() => {}),
    oncontextmenu: e => ctxMenu(e, [['Copy parameters', () => post(`/api/target_faces/${f.id}/copy`)], ['Paste parameters', () => post(`/api/target_faces/${f.id}/paste`)],
      ['Save parameters…', () => saveParams(f.id)], ['Load parameters…', () => loadParams(f.id)], ['Remove', () => api(`/api/target_faces/${f.id}`, 'DELETE')]]) },
    el('img', { src: `/api/thumb/target/${f.id}` }),
    f.input_faces.length + f.embeddings.length ? el('span', { class: 'badge', text: '⇄ ' + (f.input_faces.length + f.embeddings.length) }) : null,
    el('button', { class: 'x', text: '×', onclick: e => { e.stopPropagation(); api(`/api/target_faces/${f.id}`, 'DELETE'); } }))));
  $('#faceTools').hidden = S.tab === 'settings';
}
const modOf = e => e.shiftKey ? 'shift' : (e.ctrlKey || e.metaKey ? 'ctrl' : '');
function renderInput() {
  const box = $('#inputList'); box.dataset.empty = S.state.loading.faces ? 'Detecting faces…' : 'Drop face images here, or use the buttons above';
  const checked = new Set(S.state.checked_input_faces);
  box.replaceChildren(...filt('#qInput', S.state.input_faces, 'name').map(f => el('div', { class: 'card' + (checked.has(f.id) ? ' sel' : ''), title: f.path,
    onclick: e => post(`/api/input_faces/${f.id}/select`, { modifier: modOf(e) }).catch(() => {}),
    oncontextmenu: e => ctxMenu(e, [['Remove', () => api(`/api/input_faces/${f.id}`, 'DELETE')]]) },
    el('img', { src: `/api/thumb/input/${f.id}`, loading: 'lazy' }),
    el('span', { class: 'cap', text: f.name }),
    el('button', { class: 'x', text: '×', onclick: e => { e.stopPropagation(); api(`/api/input_faces/${f.id}`, 'DELETE'); } }))));
}
function renderEmb() {
  const checked = new Set(S.state.checked_embeddings);
  $('#embList').replaceChildren(...filt('#qEmb', S.state.embeddings, 'name').map(m => el('div', { class: 'chip' + (checked.has(m.id) ? ' sel' : ''),
    onclick: e => post(`/api/embeddings/${m.id}/select`, { modifier: modOf(e) }).catch(() => {}) },
    el('span', { text: m.name }), el('button', { class: 'x', text: '×', onclick: e => { e.stopPropagation(); api(`/api/embeddings/${m.id}`, 'DELETE'); } }))));
}

// ------------------------------------------------------------------ player
function renderPlayer() {
  const p = S.state.player;
  const seek = $('#seek');
  seek.max = p.max_frame; if (!S.seeking) seek.value = p.frame;
  if (document.activeElement !== $('#frameNum')) $('#frameNum').value = p.frame;
  $('#frameMax').textContent = '/ ' + p.max_frame;
  $('#timeText').textContent = p.fps ? fmtTime(p.frame / p.fps) + ' / ' + fmtTime(p.max_frame / p.fps) : '';
  $('#bPlay').textContent = p.playing && !p.recording ? '■ Stop' : '▶ Play';
  $('#bPlay').classList.toggle('on', p.playing && !p.recording);
  $('#bRec').classList.toggle('on', p.recording);
  $('#bRec').textContent = p.recording ? '■ Stop rec' : '● Record';
  const noMedia = !p.has_media, isVideo = p.file_type === 'video';
  ['bPlay', 'bRec', 'bBack', 'bFwd', 'bBack30', 'bFwd30', 'bMPrev', 'bMAdd', 'bMDel', 'bMNext'].forEach(id => $('#' + id).disabled = noMedia || p.file_type === 'image' || p.locked);
  seek.disabled = noMedia || p.file_type !== 'video' || p.playing;
  $('#frameNum').disabled = seek.disabled;
  $('#bSaveFrame').disabled = noMedia;
  $('#viewerMsg').hidden = !!p.has_media;
  const max = Math.max(p.max_frame, 1);
  $('#markers').replaceChildren(...p.markers.map(m => el('i', { style: `left:${(m / max) * 100}%`, title: 'Marker @' + m })));
}
const fmtTime = s => { s = Math.max(0, s); const m = Math.floor(s / 60); return `${m}:${(s % 60).toFixed(1).padStart(4, '0')}`; };
function renderFlags() {
  const f = S.state.flags;
  $('#fSwap').checked = f.swap; $('#fEdit').checked = f.edit; $('#fMask').checked = f.mask; $('#fCompare').checked = f.compare;
}
function renderGpu() {
  const g = S.state.gpu; if (!g.total) return;
  $('#gpuFill').style.width = (100 * g.used / g.total) + '%';
  $('#gpuText').textContent = `${(g.used / 1024).toFixed(1)} / ${(g.total / 1024).toFixed(1)} GB`;
}
function renderAll() {
  renderMedia(); renderTarget(); renderInput(); renderEmb(); renderPlayer(); renderFlags(); renderGpu(); refreshValues();
  $('#modelsBusy').hidden = !S.state.models_loading;
  $('#chkWebcams').checked = S.state.media.some(m => m.type === 'webcam') || $('#chkWebcams').checked;
  $('#mLastWs').style.display = S.state.last_workspace ? '' : 'none';
}
let refetchTimer = null, refetchWhat = new Set();
function refetch(what) {
  what.forEach(w => refetchWhat.add(w));
  if (refetchTimer) return;
  refetchTimer = setTimeout(async () => {
    const w = refetchWhat; refetchWhat = new Set(); refetchTimer = null;
    const st = await api('/api/state');
    const old = S.state; S.state = st;
    if (w.has('media')) renderMedia();
    if (w.has('faces')) renderTarget();
    if (w.has('lists') || w.has('faces')) { renderInput(); renderEmb(); renderTarget(); }
    if (w.has('params') || w.has('control')) refreshValues();
    if (w.has('media') || w.has('faces') || w.has('lists')) { renderPlayer(); }
    renderFlags();
    if (old && old.selected_media !== st.selected_media) { fitView(); }
  }, 30);
}

// ------------------------------------------------------------------ events (SSE)
function connectEvents() {
  const es = new EventSource('/api/events');
  es.onmessage = ev => {
    const d = JSON.parse(ev.data);
    switch (d.type) {
      case 'frame': wantFrame(d.seq); break;
      case 'hello': wantFrame(-1); if (S.state) refetch(['media', 'faces', 'lists', 'params', 'control']); break;
      case 'player': S.state.player = d; renderPlayer(); break;
      case 'invalidate': refetch(d.what); break;
      case 'output': if (autoDl()) downloadOutput(d.id); break;
      case 'toast': toast(d.level, d.title, d.message); break;
      case 'loading': S.state.loading[d.what] = d.value; if (d.what === 'media') renderMedia(); else renderInput(); break;
      case 'models_loading': S.state.models_loading = d.value; $('#modelsBusy').hidden = !d.value; break;
      case 'gpu': S.state.gpu = { used: d.used, total: d.total }; renderGpu(); break;
      case 'flags': S.state.flags = { swap: d.swap, edit: d.edit, mask: d.mask, compare: d.compare }; renderFlags(); break;
      default: break;
    }
  };
}

// ------------------------------------------------------------------ outputs (download to the PC running the browser)
const isRemote = !['localhost', '127.0.0.1', '[::1]'].includes(location.hostname);
function autoDl() { return $('#autoDl').checked; }
function downloadOutput(id) {
  const a = el('a', { href: '/api/outputs/' + id, download: '' });
  document.body.append(a); a.click(); a.remove();
}
async function showOutputs() {
  const r = await api('/api/outputs');
  const rows = r.items.length ? r.items.map(i => el('div', { class: 'ent', onclick: () => downloadOutput(i.id) }, '⬇ ' + i.name, el('small', { text: fmtSize(i.size) })))
    : [el('p', { text: 'Nothing saved yet in this session.' })];
  modal(el('div', { class: 'fb' }, el('h2', { text: 'Saved files (click to download to this PC)' }), el('div', { class: 'entries' }, rows),
    el('div', { class: 'actions' }, el('button', { class: 'btn', text: 'Close', onclick: closeModal }))));
}

// ------------------------------------------------------------------ viewer (zoom / pan)
const V = { scale: 1, x: 0, y: 0, fit: true, nw: 0, nh: 0 };
function applyView() {
  const img = $('#screen'), st = $('#stage');
  if (!V.nw) return;
  if (V.fit) {
    const s = Math.min(st.clientWidth / V.nw, st.clientHeight / V.nh);
    V.scale = s; V.x = (st.clientWidth - V.nw * s) / 2; V.y = (st.clientHeight - V.nh * s) / 2;
  }
  img.style.transform = `translate(${V.x}px,${V.y}px) scale(${V.scale})`;
  $('#hudZoom').textContent = V.fit ? 'Fit' : Math.round(V.scale * 100) + '%';
}
function fitView() { V.fit = true; applyView(); }
function initViewer() {
  const img = $('#screen'), st = $('#stage');
  const check = () => {
    if (img.naturalWidth && (img.naturalWidth !== V.nw || img.naturalHeight !== V.nh)) { V.nw = img.naturalWidth; V.nh = img.naturalHeight; applyView(); }
  };
  setInterval(check, 250); img.addEventListener('load', check);
  new ResizeObserver(applyView).observe(st);
  st.addEventListener('wheel', e => {
    e.preventDefault();
    const r = st.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    const k = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    if (V.fit) V.fit = false;
    const ns = Math.min(20, Math.max(0.05, V.scale * k));
    V.x = px - (px - V.x) * (ns / V.scale); V.y = py - (py - V.y) * (ns / V.scale); V.scale = ns; applyView();
  }, { passive: false });
  let pan = null, moved = false;
  st.addEventListener('pointerdown', e => {
    moved = false; pan = { x: e.clientX, y: e.clientY, vx: V.x, vy: V.y, btn: e.button };
    st.setPointerCapture(e.pointerId);
  });
  st.addEventListener('pointermove', e => {
    if (!pan) return;
    const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
    if (pan.btn !== 0 || moved) { if (pan.btn !== 0 || V.scale > 0) { V.fit = false; V.x = pan.vx + dx; V.y = pan.vy + dy; applyView(); } }
  });
  st.addEventListener('pointerup', e => {
    if (pan && pan.btn === 0 && !moved) togglePlay();
    pan = null;
  });
  st.addEventListener('contextmenu', e => e.preventDefault());
  st.addEventListener('dblclick', fitView);
  wantFrame(-1);
}
// Frames are fetched one by one (always the newest) instead of using a multipart stream:
// browsers/proxies buffer MJPEG and show every frame one step late.
const F = { want: 0, have: -1, busy: false, url: null };
function wantFrame(seq) {
  F.want = seq < 0 ? Math.max(F.want, F.have + 1) : Math.max(F.want, seq);
  pumpFrame();
}
async function pumpFrame() {
  if (F.busy) return;
  F.busy = true;
  try {
    while (F.have !== F.want) {
      const target = F.want;
      const r = await fetch('/api/frame.jpg?s=' + target + '&t=' + Date.now(), { cache: 'no-store' });
      if (r.ok) {
        const blob = await r.blob();
        const u = URL.createObjectURL(blob);
        const img = $('#screen');
        await new Promise(res => { img.onload = img.onerror = res; img.src = u; });
        if (F.url) URL.revokeObjectURL(F.url);
        F.url = u;
      } else {
        $('#screen').removeAttribute('src');
        V.nw = 0;
      }
      F.have = target;
      if (F.want === target) break;
    }
  } catch (e) { await sleep(800); }
  F.busy = false;
  if (F.have !== F.want) pumpFrame();
}

// ------------------------------------------------------------------ actions
const run = fn => (...a) => Promise.resolve(fn(...a)).catch(() => {});
function togglePlay() { if (S.state.player.has_media) post('/api/player/play', { record: false }).catch(() => {}); }
function toggleRec() { if (S.state.player.has_media) post('/api/player/play', { record: true }).catch(() => {}); }
const adv = n => post('/api/player/advance', { n }).catch(() => {});
function setFlag(k, v) { post('/api/flags', { [k]: v }).catch(() => {}); }
async function saveParams(fid) { location.href = `/api/target_faces/${fid}/parameters`; }
function pickFile(accept, multiple = false, dir = false) {
  return new Promise(res => {
    const inp = $('#fileHidden'); inp.value = ''; inp.accept = dir ? '' : (accept || ''); inp.multiple = multiple || dir;
    if (dir) inp.setAttribute('webkitdirectory', ''); else inp.removeAttribute('webkitdirectory');
    inp.onchange = () => res([...inp.files]); inp.click();
  });
}
const IMG_EXT = /\.(jpe?g|png|bmp|webp|tiff?)$/i, VID_EXT = /\.(mp4|mkv|avi|mov|webm|m4v|wmv|flv|gif)$/i;
async function pcPick(kind, dir) {
  const isMedia = kind === 'media';
  let files = await pickFile(isMedia ? 'image/*,video/*' : 'image/*', true, dir);
  if (dir) {
    // like the original: only include subfolders when the setting is on
    const rec = !!S.state.control[isMedia ? 'TargetMediaFolderRecursiveToggle' : 'InputFacesFolderRecursiveToggle'];
    files = files.filter(f => (IMG_EXT.test(f.name) || (isMedia && VID_EXT.test(f.name)))
      && (rec || (f.webkitRelativePath || '').split('/').length <= 2));
  }
  if (!files.length) return toast('error', 'No supported files selected');
  upload(isMedia ? '/api/media/upload' : '/api/input_faces/upload', files).catch(() => {});
}
async function upload(url, files, extra = {}) {
  if (!files.length) return;
  const fd = new FormData(); files.forEach(f => fd.append(files.length > 1 || url.includes('upload') ? 'files' : 'file', f));
  Object.entries(extra).forEach(([k, v]) => fd.append(k, v));
  toast('info', 'Uploading…', `${files.length} file(s)`);
  return api(url, 'POST', fd);
}
async function loadParams(fid) {
  const f = await pickFile('.json'); if (!f.length) return;
  const withSettings = await confirm2('Load parameters', 'Also load the global settings stored in the file?');
  const fd = new FormData(); fd.append('file', f[0]); fd.append('settings', withSettings ? '1' : '0');
  await api(`/api/target_faces/${fid}/parameters`, 'POST', fd);
}
const targetFace = () => S.state.selected_target_face;

const actions = {
  'media-pc': e => pcMenu(e, 'media'),
  'input-pc': e => pcMenu(e, 'input'),
  'ws-save': async () => { const r = await post('/api/workspace/save', {}); toast('success', 'Workspace saved', r.file); },
  'ws-load': async () => { const r = await browse({ mode: 'json', title: 'Load workspace' }); if (r) post('/api/workspace/load', { filename: r[0] }); },
  'ws-last': () => post('/api/workspace/load', {}),
  'ws-export': () => { location.href = '/api/workspace/export'; },
  'ws-import': async () => { const f = await pickFile('.json'); if (f.length) upload('/api/workspace/import', f); },
  'emb-export': () => { location.href = '/api/embeddings/export'; },
  'emb-import': async () => { const f = await pickFile('.json'); if (f.length) upload('/api/embeddings/import', f); },
  'fullscreen': () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen(),
  'media-folder': async () => { const r = await browse({ mode: 'dir', title: 'Target media folder', start: S.state.paths.target }); if (r) post('/api/media/load', { folder: r }); },
  'media-files': async () => { const r = await browse({ mode: 'media', multi: true, title: 'Target media files', start: S.state.paths.target }); if (r) post('/api/media/load', { files: r }); },
  'input-folder': async () => { const r = await browse({ mode: 'dir', title: 'Input faces folder', start: S.state.paths.input }); if (r) post('/api/input_faces/load', { folder: r }); },
  'input-files': async () => { const r = await browse({ mode: 'image', multi: true, title: 'Input face images', start: S.state.paths.input }); if (r) post('/api/input_faces/load', { files: r }); },
  'out-folder': async () => { const r = await browse({ mode: 'dir', title: 'Output media folder', start: S.state.control.OutputMediaFolder }); if (r) setOutput(r); },
  'p-copy': () => targetFace() ? post(`/api/target_faces/${targetFace()}/copy`).then(() => toast('success', 'Parameters copied')) : toast('error', 'Select a target face first'),
  'p-paste': () => targetFace() ? post(`/api/target_faces/${targetFace()}/paste`) : toast('error', 'Select a target face first'),
  'p-save': () => targetFace() ? saveParams(targetFace()) : toast('error', 'Select a target face first'),
  'p-load': () => targetFace() ? loadParams(targetFace()) : toast('error', 'Select a target face first'),
};
function pcMenu(e, kind) {
  const r = e.target.getBoundingClientRect();
  ctxMenu({ preventDefault() {}, clientX: r.left, clientY: r.bottom }, [
    ['Files from this PC…', () => pcPick(kind, false)],
    ['Folder from this PC…', () => pcPick(kind, true)],
  ]);
}
function setOutput(v) {
  S.state.control.OutputMediaFolder = v; $('#outFolder').value = v;
  post('/api/control', { name: 'OutputMediaFolder', value: v }).catch(() => {});
}

function bindUI() {
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const fn = actions[b.dataset.act]; if (fn) Promise.resolve(fn(e)).catch(() => {});
    if (b.closest('.dd-menu')) document.activeElement.blur();
  });
  $('#bPlay').onclick = togglePlay; $('#bRec').onclick = toggleRec;
  $('#bBack').onclick = () => adv(-1); $('#bFwd').onclick = () => adv(1);
  $('#bBack30').onclick = () => adv(-30); $('#bFwd30').onclick = () => adv(30);
  $('#bMAdd').onclick = () => post('/api/player/marker', { action: 'add' }).catch(() => {});
  $('#bMDel').onclick = () => post('/api/player/marker', { action: 'remove' }).catch(() => {});
  $('#bMNext').onclick = () => post('/api/player/marker', { action: 'next' }).catch(() => {});
  $('#bMPrev').onclick = () => post('/api/player/marker', { action: 'previous' }).catch(() => {});
  $('#bSaveFrame').onclick = () => post('/api/player/save_frame').then(() => {}).catch(() => {});
  $('#bFit').onclick = fitView;
  $('#btnFind').onclick = () => { toast('info', 'Searching faces…'); post('/api/target_faces/find').catch(() => {}); };
  $('#btnClearTf').onclick = () => post('/api/target_faces/clear').catch(() => {});
  $('#btnClearMem').onclick = async () => { if (await confirm2('Clear VRAM', 'Unload every model from the GPU memory? Swap/Edit will be disabled.')) post('/api/player/clear_memory').catch(() => {}); };
  $('#btnMakeEmb').onclick = async () => {
    if (!S.state.checked_input_faces.length) return toast('error', 'Select at least one input face');
    const r = await prompt2('Create embedding', [{ name: 'name', label: 'Name' }, { name: 'merge', label: 'Merge type', type: 'select', options: ['Mean', 'Median'], value: S.state.control.EmbMergeMethodSelection }], 'Create');
    if (r && r.name.trim()) post('/api/embeddings', { name: r.name, merge: r.merge, face_ids: S.state.checked_input_faces }).catch(() => {});
  };
  $('#chkWebcams').onchange = e => post('/api/media/webcams', { enabled: e.target.checked }).catch(() => {});
  $('#fSwap').onchange = e => setFlag('swap', e.target.checked);
  $('#fEdit').onchange = e => setFlag('edit', e.target.checked);
  $('#fMask').onchange = e => setFlag('mask', e.target.checked);
  $('#fCompare').onchange = e => setFlag('compare', e.target.checked);
  try { const v = localStorage.getItem('viso.autodl'); $('#autoDl').checked = v === null ? isRemote : v === '1'; } catch (e) { $('#autoDl').checked = isRemote; }
  $('#autoDl').onchange = e => { try { localStorage.setItem('viso.autodl', e.target.checked ? '1' : '0'); } catch (x) { /* ignore */ } };
  $('#bOutputs').onclick = () => showOutputs().catch(() => {});
  $('#outFolder').onchange = e => setOutput(e.target.value.trim());
  ['qMedia', 'qInput', 'qEmb'].forEach(id => $('#' + id).addEventListener('input', () => { renderMedia(); renderInput(); renderEmb(); }));

  const seek = $('#seek');
  seek.addEventListener('pointerdown', () => { S.seeking = true; });
  seek.addEventListener('input', () => { $('#frameNum').value = seek.value; post('/api/player/seek', { frame: Number(seek.value), process: false }).catch(() => {}); });
  seek.addEventListener('change', () => { S.seeking = false; post('/api/player/seek', { frame: Number(seek.value), process: true }).catch(() => {}); });
  seek.addEventListener('pointerup', () => { S.seeking = false; });
  $('#frameNum').addEventListener('keydown', e => { if (e.key === 'Enter') post('/api/player/seek', { frame: Number(e.target.value) || 0 }).catch(() => {}); });

  const lay = $('#layout');
  const vis = () => {
    lay.classList.toggle('noleft', !$('#vLeft').checked); lay.classList.toggle('noright', !$('#vRight').checked);
    $('#pMedia').classList.toggle('hide', !$('#vMedia').checked);
    ['pTarget', 'pInput', 'pEmb'].forEach(id => $('#' + id).classList.toggle('hide', !$('#vFaces').checked));
  };
  ['vLeft', 'vRight', 'vMedia', 'vFaces'].forEach(id => $('#' + id).addEventListener('change', vis));

  // drag & drop uploads
  $$('.dropzone').forEach(z => {
    z.addEventListener('dragover', e => { e.preventDefault(); z.classList.add('drag'); });
    z.addEventListener('dragleave', () => z.classList.remove('drag'));
    z.addEventListener('drop', e => {
      e.preventDefault(); z.classList.remove('drag');
      const files = [...e.dataTransfer.files]; if (!files.length) return;
      upload(z.dataset.drop === 'media' ? '/api/media/upload' : '/api/input_faces/upload', files).catch(() => {});
    });
  });

  // keyboard shortcuts (same as the desktop version)
  document.addEventListener('keydown', e => {
    if (e.target.matches('input[type=text],input[type=number],textarea,select')) return;
    if (!$('#modal').hidden) return;
    const k = e.key.toLowerCase();
    const map = {
      ' ': togglePlay, r: toggleRec, a: () => adv(-1), arrowleft: () => adv(-1), d: () => adv(1), arrowright: () => adv(1),
      z: () => adv(-30), c: () => adv(30), s: () => $('#bSaveFrame').click(),
      v: () => setFlag('swap', !S.state.flags.swap), b: () => setFlag('edit', !S.state.flags.edit),
      f: () => $(e.altKey ? '#bMDel' : '#bMAdd').click(), w: () => $('#bMNext').click(), q: () => $('#bMPrev').click(),
    };
    if (e.ctrlKey || e.metaKey) return;
    if (map[k]) { e.preventDefault(); map[k](); }
  });
  try {
    const t = localStorage.getItem('viso.tab'); if (t) S.tab = t;
  } catch (e) { /* ignore */ }
}

// ------------------------------------------------------------------ boot
async function boot() {
  bindUI(); initViewer();
  const [schema, state] = await Promise.all([api('/api/schema'), api('/api/state')]);
  S.schema = schema; S.defaults = schema.defaults; S.state = state;
  buildTabs(); renderAll(); applyView();
  connectEvents();
  if (state.last_workspace && !state.media.length) {
    if (await confirm2('Load last workspace', 'Do you want to load your last workspace?')) post('/api/workspace/load', {}).catch(() => {});
  }
}
boot().catch(e => { document.body.append(el('pre', { style: 'color:#e66;padding:20px', text: 'Failed to start UI: ' + e })); });
})();
