/* 공지 모아보기 — 기관을 한 곳씩 서버(/api/collect)에 물어 모은다.
 * 의존성 없음. 상태는 이 파일의 S 하나에 있고, 화면은 그 상태로 다시 그린다.
 */
'use strict';

const CONCURRENCY = 4;            // 동시에 묻는 기관 수(기관마다 서버가 다르다)
const REQUEST_TIMEOUT = 300000;   // 서버 함수 제한(300초)과 같게
const PAGE = 300;                 // 글 목록을 한 번에 그리는 개수
const GUESS_CACHED = 10;          // 게시판을 기억해 둔 곳의 예상 소요(초)
const GUESS_DISCOVER = 60;        // 홈에서 게시판을 찾아야 하는 곳

const $ = (sel, el = document) => el.querySelector(sel);
// 긁어 온 주소는 http(s) 만 링크로 — javascript: 같은 주소가 섞여 들어와도 실행되지 않게.
const safeUrl = (u) => (/^https?:\/\//i.test(u || '') ? u : '#');
const PERIOD = { 1: '오늘·어제', 3: '최근 3일', 7: '최근 7일', 14: '최근 14일', 30: '최근 30일' };
// 목록 파일의 갈래 이름 → 화면 이름('부' 묶음에는 처·원도 들어 있다)
const GROUP_LABEL = { 부: '부·처' };
const groupLabel = (g) => GROUP_LABEL[g] || g;

// 서버가 남긴 사유를 사람 말로 먼저 풀고, 원문은 뒤에 붙인다.
const PLAIN = [
  ['robots.txt 차단', '사이트가 자동 수집을 허용하지 않습니다(robots.txt)'],
  ['시간 제한', '정해진 시간 안에 끝내지 못했습니다'],
  ['시간 초과', '사이트 응답이 너무 느립니다'],
  ['인증서 오류', '사이트의 보안 인증서에 문제가 있습니다'],
  ['접근 거부(403)', '사이트가 접속을 거부했습니다'],
  ['주소 없음(404)', '게시판 주소가 바뀌었습니다'],
  ['도메인을 찾을 수 없음', '홈페이지 주소가 열리지 않습니다'],
  ['게시판·피드 링크를 찾지 못했습니다', '홈에서 게시판을 찾지 못했습니다'],
  ['글 0건', '기간 안에 올라온 글이 없습니다'],
];
const plainWhy = (raw) => (PLAIN.find(([k]) => raw.includes(k)) || [null, ''])[1];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// 브라우저 저장소는 개인 창·차단 환경에서 비거나 예외를 던진다 — 없어도 동작해야 한다.
const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 저장 못 해도 계속 */ }
  },
};

const S = {
  orgs: [], byId: new Map(), sections: [],
  selected: new Set(store.get('osc.sel', [])),
  days: Number(store.get('osc.days', 7)) || 7,
  tab: '', group: '', region: '', q: '',
  view: 'pick',
  run: null,
  shown: PAGE,
  filter: { group: '', org: '', q: '', fresh: false },
};

// ── 시간 표기 ────────────────────────────────────────────────────────────────
function seconds(n) {
  n = Math.max(0, Math.round(n));
  if (n < 60) return `${n}초`;
  const m = Math.floor(n / 60), s = n % 60;
  return s ? `${m}분 ${s}초` : `${m}분`;
}
function left(n) {
  const r = roughly(Math.max(n, 0));
  return r === '곧' ? '곧 끝납니다' : `남은 시간 ${r}`;
}
function roughly(n) {
  if (n <= 20) return '곧';
  if (n < 90) return `약 ${Math.round(n / 10) * 10}초`;
  return `약 ${Math.round(n / 60)}분`;
}
const WEEK = ['일', '월', '화', '수', '목', '금', '토'];
function dayLabel(iso) {
  if (!iso) return '날짜 없음';
  const [y, m, d] = iso.split('-').map(Number);
  const that = new Date(y, m - 1, d);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.round((today - that) / 86400000);
  if (diff === 0) return '오늘';
  if (diff === 1) return '어제';
  const year = y === now.getFullYear() ? '' : `${y}년 `;
  return `${year}${m}월 ${d}일 (${WEEK[that.getDay()]})`;
}

// ── 시작 ─────────────────────────────────────────────────────────────────────
async function init() {
  readHash();
  $('#days').value = String(S.days);
  bindEvents();
  try {
    const res = await fetch('/api/catalog');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    S.orgs = data.orgs;
    S.sections = data.sections;
    S.byId = new Map(S.orgs.map((o) => [o.id, o]));
    $('#version').textContent = data.version ? `v${data.version}` : '';
  } catch (e) {
    $('#orgs').hidden = true;
    const empty = $('#pick-empty');
    empty.hidden = false;
    empty.innerHTML = `기관 목록을 불러오지 못했습니다(${esc(e.message)}). <button type="button" class="link-btn" onclick="location.reload()">다시 불러오기</button>`;
    return;
  }
  // 목록에 없는 id(공유 링크의 오타·삭제된 기관)는 조용히 버리지 않고 알린다.
  const unknown = [...S.selected].filter((id) => !S.byId.has(id));
  unknown.forEach((id) => S.selected.delete(id));
  if (S.sharedCount != null) {
    const note = $('#shared-note');
    note.hidden = false;
    note.textContent = `공유받은 목록 ${S.selected.size}곳을 골라 두었습니다.` +
      (unknown.length ? ` 지금 목록에 없는 ${unknown.length}곳은 뺐습니다.` : '') +
      ' 아래 단추를 누르면 바로 모읍니다.';
  }
  S.tab = S.sharedCount != null && S.selected.size ? '고른 곳' : (S.sections[0] || '');
  if (S.sharedCount != null) remember();
  renderPick();
  renderBar();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
}

function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  const ids = (h.get('o') || '').split(',').map((s) => s.trim()).filter(Boolean);
  if (ids.length) {
    S.selected = new Set(ids);
    S.sharedCount = ids.length;
  }
  const d = Number(h.get('d'));
  if ([1, 3, 7, 14, 30].includes(d)) S.days = d;
  // 받은 목록은 한 번만 적용한다 — 주소에 남겨 두면 새로 고칠 때마다 내 선택을 덮는다.
  if (location.hash) history.replaceState(null, '', location.pathname + location.search);
}

function shareUrl() {
  const ids = [...S.selected].join(',');
  return `${location.origin}${location.pathname}#o=${encodeURIComponent(ids).replace(/%2C/g, ',')}&d=${S.days}`;
}

function remember() {
  store.set('osc.sel', [...S.selected]);
  store.set('osc.days', S.days);
}

// ── 고르기 화면 ──────────────────────────────────────────────────────────────
function visibleOrgs() {
  const q = S.q.trim().toLowerCase();
  return S.orgs.filter((o) => {
    if (S.tab === '고른 곳') { if (!S.selected.has(o.id)) return false; }
    else if (o.section !== S.tab) return false;
    if (S.tab !== '고른 곳') {
      if (S.group && o.group !== S.group) return false;
      if (S.region && o.region !== S.region) return false;
    }
    if (q && !o.name.toLowerCase().includes(q) && !o.home.toLowerCase().includes(q)) return false;
    return true;
  });
}

function countBy(list, key) {
  const m = new Map();
  for (const o of list) if (o[key]) m.set(o[key], (m.get(o[key]) || 0) + 1);
  return m;
}

function renderPick() {
  // 묶음 탭
  const tabs = [...S.sections, '고른 곳'];
  $('#tabs').innerHTML = tabs.map((t) => {
    const n = t === '고른 곳' ? S.selected.size : S.orgs.filter((o) => o.section === t).length;
    const label = t === '정부' ? '정부 기관' : t;
    return `<button type="button" class="tab" role="tab" data-tab="${esc(t)}" aria-selected="${t === S.tab}">${esc(label)}<span class="n">${n}</span></button>`;
  }).join('');

  // 갈래·지역 거르개 — 지금 탭의 기관에서만 만든다
  const inTab = S.orgs.filter((o) => o.section === S.tab);
  let filters = '';
  if (S.tab !== '고른 곳' && inTab.length) {
    const groups = countBy(inTab, 'group');
    if (groups.size > 1) {
      filters += `<button type="button" class="chip" data-group="" aria-pressed="${!S.group}">전체</button>`;
      for (const [g, n] of groups) {
        filters += `<button type="button" class="chip" data-group="${esc(g)}" aria-pressed="${S.group === g}">${esc(groupLabel(g))}<span class="n">${n}</span></button>`;
      }
    }
    const regions = countBy(inTab, 'region');
    if (regions.size > 1) {
      const opts = [...regions.keys()].sort((a, b) => a.localeCompare(b, 'ko'));
      filters += `<label><span class="sr">지역</span><select id="region"><option value="">모든 지역</option>${
        opts.map((r) => `<option value="${esc(r)}"${S.region === r ? ' selected' : ''}>${esc(r)} (${regions.get(r)})</option>`).join('')
      }</select></label>`;
    }
  }
  $('#filters').innerHTML = filters;

  // 목록
  const list = visibleOrgs();
  const picked = list.filter((o) => S.selected.has(o.id)).length;
  $('#list-count').textContent = list.length ? `${list.length}곳${picked ? `, 그중 ${picked}곳 고름` : ''}` : '';
  const toggle = $('#toggle-all');
  toggle.hidden = !list.length;
  toggle.textContent = picked === list.length && list.length ? '이 목록 모두 빼기' : '이 목록 모두 고르기';
  $('#orgs').hidden = !list.length;
  $('#orgs').innerHTML = list.map((o) => {
    const meta = o.section === '학교' ? [o.region, o.group].filter(Boolean).join(' ') : groupLabel(o.group);
    return `<li><label><input type="checkbox" data-id="${esc(o.id)}"${S.selected.has(o.id) ? ' checked' : ''}>` +
      `<span class="name">${esc(o.name)}</span><span class="meta">${esc(meta)}</span></label></li>`;
  }).join('');
  const empty = $('#pick-empty');
  empty.hidden = !!list.length;
  empty.textContent = S.tab === '고른 곳'
    ? '아직 고른 곳이 없습니다. 정부 기관이나 학교 탭에서 골라 주세요.'
    : '찾는 이름이 없습니다. 이름 일부만 넣어 보세요(예: 외국어, 노동).';
}

function estimate(ids) {
  const total = ids.reduce((sum, id) => sum + (S.byId.get(id)?.checked ? GUESS_CACHED : GUESS_DISCOVER), 0);
  return total / Math.min(CONCURRENCY, Math.max(ids.length, 1));
}

function renderBar() {
  const go = $('#go');
  const running = S.run && !S.run.finished;
  if (running) {
    go.disabled = false;
    go.textContent = S.view === 'read' ? '멈추기' : '모으는 중… 결과 보기';
    go.dataset.action = S.view === 'read' ? 'stop' : 'show';
    return;
  }
  if (S.view === 'read' && S.run) {
    go.disabled = false;
    go.textContent = '다시 모으기';
    go.dataset.action = 'again';
    return;
  }
  const n = S.selected.size;
  go.disabled = !n;
  go.dataset.action = 'start';
  const est = n ? estimate([...S.selected]) : 0;
  go.textContent = n ? `${n}곳 모으기${est > 20 ? ` · ${roughly(est)}` : ''}` : '기관을 골라 주세요';
}

function setView(view) {
  S.view = view;
  $('#pick').hidden = view !== 'pick';
  $('#read').hidden = view !== 'read';
  document.querySelectorAll('.view-btn').forEach((b) => {
    if (b.dataset.view === view) b.setAttribute('aria-current', 'page');
    else b.removeAttribute('aria-current');
  });
  renderBar();
  window.scrollTo({ top: 0 });
}

// ── 모으기 ───────────────────────────────────────────────────────────────────
function start() {
  const ids = [...S.selected].filter((id) => S.byId.has(id));
  if (!ids.length) return;
  remember();
  const run = {
    ids, days: S.days, queue: ids.slice(), active: new Map(), results: [],
    started: Date.now(), finished: false, stopped: false, controllers: new Set(),
  };
  S.run = run;
  S.shown = PAGE;
  S.filter = { group: '', org: '', q: '', fresh: false };
  $('#tq').value = '';
  setView('read');
  renderRun();
  run.ticker = setInterval(renderProgress, 1000);
  const workers = Array.from({ length: Math.min(CONCURRENCY, ids.length) }, () => worker(run));
  Promise.all(workers).then(() => finish(run));
}

async function worker(run) {
  while (run.queue.length && !run.stopped) {
    const id = run.queue.shift();
    run.active.set(id, Date.now());
    renderProgress();
    const began = Date.now();
    let data;
    try {
      data = await ask(run, id);
    } catch (e) {
      data = { id, name: S.byId.get(id)?.name || id, count: 0, notices: [], failures: [], notes: [], error: e.message };
    }
    run.active.delete(id);
    if (run.stopped && data.error === '멈춤') continue; // '멈춰서 못 본 곳'으로 따로 보여 준다
    data.ms = Date.now() - began;
    run.results.push(data);
    renderRun();
  }
}

async function ask(run, id) {
  const ctl = new AbortController();
  run.controllers.add(ctl);
  const timer = setTimeout(() => ctl.abort(), REQUEST_TIMEOUT);
  try {
    const res = await fetch(`/api/collect?id=${encodeURIComponent(id)}&days=${run.days}`, { signal: ctl.signal });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || (res.status === 504 ? '서버 시간 초과(504)' : `HTTP ${res.status}`));
    return body;
  } catch (e) {
    if (e.name === 'AbortError') throw new Error(run.stopped ? '멈춤' : '응답이 너무 늦음');
    if (e instanceof TypeError) throw new Error('네트워크 연결 실패');
    throw e;
  } finally {
    clearTimeout(timer);
    run.controllers.delete(ctl);
  }
}

function stop() {
  const run = S.run;
  if (!run || run.finished) return;
  run.stopped = true;
  run.queue.length = 0;
  run.controllers.forEach((c) => c.abort());
}

function finish(run) {
  clearInterval(run.ticker);
  run.finished = true;
  run.ended = Date.now();
  markSeen(run);
  renderRun();
  renderBar();
}

// '새 글' — 이 기기에서 전에 본 적 없는 링크. 처음 모으는 곳은 전부 새 글이라 표시하지 않는다.
function freshness(run) {
  if (run.seen) return run.seen;
  run.seen = { urls: new Set(store.get('osc.seen', [])), orgs: new Set(store.get('osc.seenOrgs', [])) };
  return run.seen;
}
function isFresh(run, n) {
  const seen = freshness(run);
  return seen.orgs.has(n.orgId) && !seen.urls.has(n.url);
}
function markSeen(run) {
  const urls = store.get('osc.seen', []);
  const known = new Set(urls);
  for (const n of allNotices(run)) if (n.url && !known.has(n.url)) { urls.push(n.url); known.add(n.url); }
  store.set('osc.seen', urls.slice(-6000));
  const orgs = new Set(store.get('osc.seenOrgs', []));
  run.results.forEach((r) => { if (r.count) orgs.add(r.id); });
  store.set('osc.seenOrgs', [...orgs]);
}

function allNotices(run) {
  if (run._flat && run._flatSize === run.results.length) return run._flat;
  const out = [];
  for (const r of run.results) {
    for (const n of r.notices || []) out.push({ ...n, org: r.name, orgId: r.id });
  }
  out.sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  for (const n of out) n.fresh = isFresh(run, n);
  run._flat = out;
  run._flatSize = run.results.length;
  return out;
}

// ── 결과 화면 ────────────────────────────────────────────────────────────────
function renderRun() {
  renderProgress();
  renderSummary();
  renderList();
  renderFails();
  renderBar();
  const badge = $('#read-badge');
  const total = S.run ? allNotices(S.run).length : 0;
  badge.hidden = !total;
  badge.textContent = total;
}

function renderProgress() {
  const run = S.run;
  const box = $('#progress');
  if (!run) { box.innerHTML = ''; return; }
  const done = run.results.length;
  const total = run.ids.length;
  const got = run.results.reduce((s, r) => s + (r.count || 0), 0);
  if (run.finished) {
    const took = seconds((run.ended - run.started) / 1000);
    box.innerHTML = `<p class="status">${run.stopped ? '멈췄습니다' : '다 모았습니다'}. ${total}곳 중 ${done}곳, ${took} 걸렸습니다.</p>`;
    return;
  }
  const elapsed = (Date.now() - run.started) / 1000;
  const remaining = run.queue.length + run.active.size;
  let eta;
  if (done >= 2) {
    const avg = run.results.reduce((s, r) => s + r.ms, 0) / done / 1000;
    eta = (avg * remaining) / Math.min(CONCURRENCY, remaining || 1);
  } else {
    eta = estimate([...run.queue, ...run.active.keys()]) - (done ? 0 : elapsed);
  }
  const pct = Math.round((done / total) * 100);
  const lanes = [...run.active.entries()].map(([id, since]) => {
    const org = S.byId.get(id);
    const what = org?.checked ? '기억해 둔 게시판 확인' : '홈에서 게시판 찾는 중';
    return `<li><span class="who">${esc(org?.name || id)}</span><span class="what">${what}</span><span class="sec">${seconds((Date.now() - since) / 1000)}</span></li>`;
  });
  const recent = run.results.slice(-4).reverse().map((r) => (
    r.count
      ? `<li><span class="who">${esc(r.name)}</span><span class="got">${r.count}건</span><span class="sec">${seconds(r.ms / 1000)}</span></li>`
      : `<li><span class="who">${esc(r.name)}</span><span class="miss">못 가져옴</span><span class="sec">${seconds(r.ms / 1000)}</span></li>`
  ));
  box.innerHTML =
    `<div class="meter" role="progressbar" aria-valuemin="0" aria-valuemax="${total}" aria-valuenow="${done}"><span style="width:${pct}%"></span></div>` +
    `<p class="status"><strong>${total}곳 중 ${done}곳</strong> 끝냈습니다. 지금까지 ${got}건, ${left(eta)}.</p>` +
    `<ul class="lanes">${lanes.join('')}${recent.join('')}</ul>`;
}

function filtered(run) {
  const f = S.filter;
  const q = f.q.trim().toLowerCase();
  return allNotices(run).filter((n) =>
    (!f.group || n.group === f.group) &&
    (!f.org || n.orgId === f.org) &&
    (!f.fresh || n.fresh) &&
    (!q || n.title.toLowerCase().includes(q)));
}

function renderSummary() {
  const run = S.run;
  const box = $('#summary');
  const items = run ? allNotices(run) : [];
  if (!run || (!items.length && !run.finished)) { box.innerHTML = ''; $('#tools').hidden = true; return; }
  const orgsWithHits = run.results.filter((r) => r.count).length;
  const groups = countBy(items, 'group');
  const freshCount = items.filter((n) => n.fresh).length;
  const head = run.finished
    ? `<div class="seal${run.stampShown ? '' : ' stamp'}" aria-hidden="true"><small>수집완료</small><b>${items.length}</b><small>건</small></div>`
    : '';
  run.stampShown = run.finished;
  const chip = (key, value, label, n) =>
    `<button type="button" class="chip" data-f="${key}" data-v="${esc(value)}" aria-pressed="${String(S.filter[key] === value || (key === 'fresh' && S.filter.fresh))}">${esc(label)}<span class="n">${n}</span></button>`;
  let chips = chip('group', '', '전체', items.length);
  for (const [g, n] of [...groups].sort((a, b) => b[1] - a[1])) chips += chip('group', g, g, n);
  if (freshCount) chips += chip('fresh', 'on', '새 글', freshCount);
  box.innerHTML =
    `<div><h2>${PERIOD[run.days] || `최근 ${run.days}일`} 올라온 글 ${items.length}건</h2>` +
    `<p class="sub">${orgsWithHits}곳에서 모았습니다${run.finished ? '' : ' (모으는 중)'}.</p></div>${head}` +
    `<div class="chips">${chips}</div>`;

  $('#tools').hidden = !items.length;
  const sel = $('#org-filter');
  const counts = new Map(run.results.filter((r) => r.count).map((r) => [r.id, r]));
  sel.innerHTML = `<option value="">모든 곳</option>${[...counts.values()]
    .sort((a, b) => a.name.localeCompare(b.name, 'ko'))
    .map((r) => `<option value="${esc(r.id)}"${S.filter.org === r.id ? ' selected' : ''}>${esc(r.name)} (${r.count})</option>`).join('')}`;
}

function renderList() {
  const run = S.run;
  const box = $('#notices');
  if (!run) { box.innerHTML = ''; return; }
  const items = filtered(run);
  if (!items.length) {
    box.innerHTML = run.finished
      ? `<p class="empty">${allNotices(run).length ? '거른 조건에 맞는 글이 없습니다.' : '이 기간에 올라온 글이 없습니다. 기간을 늘려 다시 모아 보세요.'}</p>`
      : '';
    $('#after').hidden = !run.finished;
    return;
  }
  let html = '';
  let day = null;
  for (const n of items.slice(0, S.shown)) {
    const label = dayLabel(n.date);
    if (label !== day) {
      if (day !== null) html += '</ol>';
      html += `<h3 class="day">${esc(label)}</h3><ol class="items">`;
      day = label;
    }
    html += `<li class="item"><a class="t" href="${esc(safeUrl(n.url))}" target="_blank" rel="noopener">${n.fresh ? '<span class="new" title="새 글"></span>' : ''}${esc(n.title)}</a>` +
      `<div class="m"><span class="org">${esc(n.org)}</span><span>${esc(n.category || n.group)}</span>${n.unit ? `<span>${esc(n.unit)}</span>` : ''}` +
      `${n.origin ? `<span class="src">${esc(n.origin)}</span>` : ''}</div></li>`;
  }
  html += '</ol>';
  if (items.length > S.shown) {
    html += `<p class="empty"><button type="button" class="ghost" id="more">${items.length - S.shown}건 더 보기</button></p>`;
  }
  box.innerHTML = html;
  $('#after').hidden = !run.finished;
}

function shortWhy(r) {
  if (r.error) return r.error;
  const first = (r.failures || [])[0] || (r.notes || [])[0] || '게시판에서 기간 안의 글을 찾지 못했습니다';
  return first.length > 140 ? `${first.slice(0, 140)}…` : first;
}
function whyHtml(r) {
  const raw = shortWhy(r);
  const plain = plainWhy(raw);
  return plain ? `${esc(plain)} <span class="raw">${esc(raw)}</span>` : esc(raw);
}

function renderFails() {
  const run = S.run;
  const box = $('#fails');
  if (!run || !run.finished) { box.innerHTML = ''; return; }
  const misses = run.results.filter((r) => !r.count);
  const hits = run.results.filter((r) => r.count).sort((a, b) => b.count - a.count);
  const pending = run.ids.filter((id) => !run.results.some((r) => r.id === id));
  let html = '';
  if (hits.length) {
    html += `<details class="fails"><summary>곳별 건수 (${hits.length}곳)</summary><ul>${hits.map((r) =>
      `<li>${esc(r.name)} <b>${r.count}건</b> <span class="why">${r.mode === 'cache' ? '기억한 게시판' : '게시판 새로 찾음'}, ${seconds(r.ms / 1000)}</span></li>`).join('')}</ul></details>`;
  }
  if (misses.length) {
    html += `<details class="fails" open><summary>글을 못 가져온 곳 (${misses.length}곳)</summary><ul>${misses.map((r) =>
      `<li>${esc(r.name)} <span class="why">${whyHtml(r)}</span></li>`).join('')}</ul></details>`;
  }
  if (pending.length) {
    html += `<details class="fails"><summary>멈춰서 못 본 곳 (${pending.length}곳)</summary><ul>${pending.map((id) =>
      `<li>${esc(S.byId.get(id)?.name || id)}</li>`).join('')}</ul></details>`;
  }
  box.innerHTML = html;
}

// ── 공유·저장 ────────────────────────────────────────────────────────────────
async function share() {
  const url = shareUrl();
  const title = '공지 모아보기';
  try {
    if (navigator.share) { await navigator.share({ title, url }); return; }
    await navigator.clipboard.writeText(url);
    flash('#share', '링크를 복사했습니다');
  } catch (e) {
    if (e && e.name === 'AbortError') return; // 공유 창을 닫은 경우
    window.prompt('이 링크를 복사하세요', url);
  }
}

function flash(sel, text) {
  const b = $(sel);
  const before = b.textContent;
  b.textContent = text;
  setTimeout(() => { b.textContent = before; }, 1800);
}

function saveReport() {
  const run = S.run;
  if (!run) return;
  const items = allNotices(run);
  const when = new Date(run.ended || Date.now());
  const stamp = `${when.getFullYear()}-${String(when.getMonth() + 1).padStart(2, '0')}-${String(when.getDate()).padStart(2, '0')}`;
  const byOrg = new Map();
  for (const n of items) {
    if (!byOrg.has(n.org)) byOrg.set(n.org, []);
    byOrg.get(n.org).push(n);
  }
  const groups = [...countBy(items, 'group')].sort((a, b) => b[1] - a[1]).map(([g, n]) => `${esc(g)} ${n}건`).join(', ');
  const sections = [...byOrg].map(([org, list]) => `<h2>${esc(org)} <small>${list.length}건</small></h2><table>${list.map((n) =>
    `<tr><td class="d">${esc(n.date || '')}</td><td><a href="${esc(safeUrl(n.url))}">${esc(n.title)}</a><div class="c">${esc(n.category || n.group)}</div></td></tr>`).join('')}</table>`).join('');
  const misses = run.results.filter((r) => !r.count);
  const html = `<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>공지 모아보기 ${stamp}</title>
<style>body{font:15px/1.6 "Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif;max-width:760px;margin:0 auto;padding:24px 16px;color:#18202e}
h1{font-size:22px;margin:0 0 6px}h2{font-size:17px;margin:28px 0 6px;border-bottom:2px solid #18202e;padding-bottom:4px}h2 small{font-weight:400;color:#5b6577}
table{border-collapse:collapse;width:100%}td{border-bottom:1px solid #dce1e8;padding:7px 4px;vertical-align:top}td.d{white-space:nowrap;color:#5b6577;width:6.5em}
.c{font-size:12px;color:#5b6577}a{color:#1d4fa3}.meta{color:#5b6577}</style></head><body>
<h1>공지 모아보기 보고서</h1><p class="meta">${stamp} 작성, 최근 ${run.days}일, ${run.results.length}곳에서 ${items.length}건. ${groups}</p>
${sections}${misses.length ? `<h2>글을 못 가져온 곳 <small>${misses.length}곳</small></h2><ul>${misses.map((r) => `<li>${esc(r.name)}: ${esc(shortWhy(r))}</li>`).join('')}</ul>` : ''}
<p class="meta">제목·날짜·링크만 모았습니다. 원문은 각 기관 누리집에 있습니다. — open_site_clipper</p></body></html>`;
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `공지모음-${stamp}.html`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

// ── 이벤트 ───────────────────────────────────────────────────────────────────
function bindEvents() {
  document.querySelectorAll('.view-btn').forEach((b) => b.addEventListener('click', () => {
    if (b.dataset.view === 'read' && !S.run) return;
    setView(b.dataset.view);
  }));

  $('#q').addEventListener('input', (e) => { S.q = e.target.value; renderPick(); });

  $('#tabs').addEventListener('click', (e) => {
    const b = e.target.closest('[data-tab]');
    if (!b) return;
    S.tab = b.dataset.tab;
    S.group = '';
    S.region = '';
    renderPick();
  });

  $('#filters').addEventListener('click', (e) => {
    const b = e.target.closest('[data-group]');
    if (!b) return;
    S.group = b.dataset.group;
    renderPick();
  });
  $('#filters').addEventListener('change', (e) => {
    if (e.target.id === 'region') { S.region = e.target.value; renderPick(); }
  });

  $('#orgs').addEventListener('change', (e) => {
    const id = e.target.dataset.id;
    if (!id) return;
    if (e.target.checked) S.selected.add(id); else S.selected.delete(id);
    remember();
    renderPick();
    renderBar();
  });

  $('#toggle-all').addEventListener('click', () => {
    const list = visibleOrgs();
    const all = list.every((o) => S.selected.has(o.id));
    list.forEach((o) => (all ? S.selected.delete(o.id) : S.selected.add(o.id)));
    remember();
    renderPick();
    renderBar();
  });

  $('#days').addEventListener('change', (e) => { S.days = Number(e.target.value); remember(); renderBar(); });

  $('#go').addEventListener('click', () => {
    const action = $('#go').dataset.action;
    if (action === 'start' || action === 'again') start();
    else if (action === 'stop') stop();
    else if (action === 'show') setView('read');
  });

  $('#summary').addEventListener('click', (e) => {
    const b = e.target.closest('[data-f]');
    if (!b) return;
    if (b.dataset.f === 'fresh') S.filter.fresh = !S.filter.fresh;
    else S.filter.group = b.dataset.v;
    S.shown = PAGE;
    renderSummary();
    renderList();
  });
  $('#org-filter').addEventListener('change', (e) => { S.filter.org = e.target.value; S.shown = PAGE; renderList(); });
  $('#tq').addEventListener('input', (e) => { S.filter.q = e.target.value; S.shown = PAGE; renderList(); });
  $('#notices').addEventListener('click', (e) => {
    if (e.target.id === 'more') { S.shown += PAGE; renderList(); }
  });

  $('#share').addEventListener('click', share);
  $('#save').addEventListener('click', saveReport);
}

document.addEventListener('DOMContentLoaded', init);
