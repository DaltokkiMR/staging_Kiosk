// ===== 공통 =====
const API = location.protocol === 'file:' ? 'http://localhost:8000' : '';
const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { return null; } };
const $ = (s) => document.querySelector(s);
const won = (n) => (n ?? 0).toLocaleString('ko-KR') + '원';
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

let TOKEN = ls('consumerToken');
let ME = null;
let PAY_TYPES = [];
const S = { view: 'home', methods: [], selected: 0, usePoints: ls('set_points') !== '0', qr: null, qrTimer: null, pollTimer: null };

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...(TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401 && TOKEN) { logout(); throw new Error('다시 로그인해 주세요'); }
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '요청에 실패했어요');
  return data;
}
// 스와이프 토스트: 아래로 밀면 닫힘, 아래쪽 심지가 타들어가며 남은 시간 표시
function toast(msg, type) {
  if (window.UFX?.swipeToast) return UFX.swipeToast(msg, { type: type || (/실패|못|없어요|오류|다시/.test(msg) ? 'error' : '') });
  alert(msg);
}
// 할인 카운터(오도미터) 정리용
let COUNTERS = [];
function clearCounters() { COUNTERS.forEach((c) => c.stop()); COUNTERS = []; }
function hydrateCounters(root) {
  root.querySelectorAll('[data-count]:not([data-live])').forEach((el) => {
    el.dataset.live = '1';
    COUNTERS.push(UFX.countdown(el, Date.now() + +el.dataset.count * 1000));
  });
}
const discBadge = (d) => d ? `<span class="disc">${d.rate}% 할인 · <span data-count="${d.seconds_left}"></span> 남음</span>` : '';
const PALETTE = ['#E2572B', '#D98B2B', '#8A6B3E', '#6F8F3A', '#3B7A8F', '#8F3B6B', '#5A4FA0'];
function colorFor(text) { let h = 0; for (const c of text) h = (h * 31 + c.charCodeAt(0)) >>> 0; return PALETTE[h % PALETTE.length]; }
const CARD_STYLE = {
  credit_card: ['#2B2D42', '#fff'], check_card: ['#3D5A80', '#fff'], samsung_pay: ['#1428A0', '#fff'],
  naver_pay: ['#03C75A', '#fff'], kakao_pay: ['#FEE500', '#191600'], local_currency: ['#6A994E', '#fff'],
  onnuri: ['#B5462F', '#fff'], dodo_point: ['#E2572B', '#fff'],
};
const typeLabel = (t) => PAY_TYPES.find((p) => p.value === t)?.label || t;

// ===== 로그인 (시안: 처음엔 문구 + 로그인하기, 누르면 입력칸이 열림) =====
let signupMode = false;
// 시연용: 회원가입 칸을 미리 채워둠 (취향은 가입 후 직접 설정)
const SIGNUP_DEMO = { name: '김디미', birth: '2003-05-14', gender: '여', phone: '010-1234-5678', email: 'dimi@uniorder.kr', pw: '1234' };
const showFields = () => $('#loginFields').classList.remove('hidden');
const setGender = (g) => document.querySelectorAll('#signupGender [data-g]').forEach((b) => b.classList.toggle('on', b.dataset.g === g));
const agreeBoxes = () => [...document.querySelectorAll('#signupAgree input:not([data-all])')];
if (ls('lastEmail')) $('#loginEmail').value = ls('lastEmail');
$('#toggleSignup').addEventListener('click', () => {
  signupMode = !signupMode; showFields();
  $('#loginView').classList.toggle('signup', signupMode);
  document.querySelectorAll('#loginView .signup-only').forEach((el) => el.classList.toggle('hidden', !signupMode));
  $('#loginBtn').textContent = signupMode ? '가입하기' : '로그인하기';
  $('#toggleSignup').textContent = signupMode ? '이미 계정이 있어요' : '계정이 없으신가요?';
  if (signupMode) {
    const d = SIGNUP_DEMO;
    $('#signupName').value = d.name; $('#signupBirth').value = d.birth; $('#signupPhone').value = d.phone;
    $('#loginEmail').value = d.email; $('#loginPw').value = d.pw; $('#signupPw2').value = d.pw; setGender(d.gender);
    document.querySelectorAll('#signupAgree input').forEach((c) => (c.checked = true));
  }
});
$('#signupGender').addEventListener('click', (e) => { const b = e.target.closest('[data-g]'); if (b) setGender(b.dataset.g); });
$('#signupAgree').addEventListener('change', (e) => {
  if (e.target.matches('[data-all]')) agreeBoxes().forEach((c) => (c.checked = e.target.checked));
  else $('#signupAgree [data-all]').checked = agreeBoxes().every((c) => c.checked);
});
$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  if ($('#loginFields').classList.contains('hidden')) { showFields(); $('#loginEmail').focus(); return; }
  try {
    const body = { email: $('#loginEmail').value.trim(), password: $('#loginPw').value };
    let r;
    if (signupMode) {
      if (body.password !== $('#signupPw2').value) return toast('비밀번호가 서로 달라요');
      if (![...document.querySelectorAll('#signupAgree [data-req]')].every((c) => c.checked)) return toast('필수 약관에 동의해 주세요');
      r = await api('/api/auth/signup', { method: 'POST', body: {
        ...body, role: 'consumer', name: $('#signupName').value.trim() || '손님', birthdate: $('#signupBirth').value || null,
        gender: document.querySelector('#signupGender .on')?.dataset.g || null, phone: $('#signupPhone').value.trim() || null } });
    } else {
      r = await api('/api/auth/login', { method: 'POST', body });
    }
    if (r.user.role !== 'consumer') return toast('손님 계정으로 로그인해 주세요 (사장님은 사장님 화면 이용)');
    TOKEN = r.access_token; ls('consumerToken', TOKEN); ls('lastEmail', body.email);
    const isNew = signupMode;
    if (signupMode) $('#toggleSignup').click();  // 다음에 로그아웃하면 로그인 화면으로
    await start();
    if (isNew) openTaste(true);  // 가입 직후 바로 입맛 설정
  } catch (err) { toast(err.message); }
});
function logout() { TOKEN = null; ls('consumerToken', null); stopQr(); clearInterval(S.linkTimer); $('#appView').classList.add('hidden'); $('#loginView').classList.remove('hidden'); }

async function start() {
  try { ME = await api('/api/auth/me'); PAY_TYPES = await api('/api/pay-types'); }
  catch { return logout(); }
  $('#loginView').classList.add('hidden'); $('#appView').classList.remove('hidden');
  $('#hello').textContent = ME.name + '님';
  if (!NAV && window.UFX?.pillNav) NAV = UFX.pillNav($('#nav'), { bounce: 0.42 });
  go('home'); // 앱을 열면 바로 결제 QR
}

// ===== 화면 전환 (홈 · 지도 · 지갑 · 내 정보) =====
let NAV = null;
const RENDER = () => ({ home: renderHome, map: renderMap, wallet: renderWallet, me: renderMe });
$('#nav').addEventListener('click', (e) => { const b = e.target.closest('[data-view]'); if (b) go(b.dataset.view); });
function go(view) {
  S.view = view; stopQr(); destroyMap(); clearCounters();
  if (NAV) NAV.set(view); else document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $('#screen').className = 'screen' + (view === 'map' ? ' map-screen' : '');
  $('.appbar').classList.toggle('hidden', view === 'map');
  $('#screen').onclick = null;
  $('#screen').innerHTML = '<p class="muted">불러오는 중…</p>';
  RENDER()[view]().catch((e) => { $('#screen').innerHTML = `<p class="muted">${esc(e.message)}</p>`; });
}

// ===== 내 위치 (안 되면 데모 위치: 망원동) =====
const DEMO_LOC = { lat: 37.5555, lng: 126.9100 };
function distM(a, b) {
  const R = 6371000, r = (x) => (x * Math.PI) / 180;
  const d = Math.sin(r(b.lat - a.lat) / 2) ** 2 + Math.cos(r(a.lat)) * Math.cos(r(b.lat)) * Math.sin(r(b.lng - a.lng) / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(d));
}
function getLoc() {
  if (S.loc) return Promise.resolve(S.loc);
  return new Promise((resolve) => {
    const fallback = () => { S.loc = { ...DEMO_LOC, demo: true }; resolve(S.loc); };
    if (!navigator.geolocation) return fallback();
    const t = setTimeout(fallback, 4000);
    navigator.geolocation.getCurrentPosition((p) => {
      clearTimeout(t);
      const here = { lat: p.coords.latitude, lng: p.coords.longitude };
      // 데모 가맹점이 망원동에만 있어서, 3km 넘게 떨어져 있으면 데모 위치 사용
      if (distM(here, DEMO_LOC) > 3000) return fallback();
      S.loc = here; resolve(here);
    }, () => { clearTimeout(t); fallback(); }, { timeout: 3500, maximumAge: 60000 });
  });
}
const distText = (m) => m == null ? '' : m < 1000 ? `${m}m` : `${(m / 1000).toFixed(1)}km`;
const TAG_CLASS = { 단골: 'loyal', '지금 딱': 'now', 취향저격: 'taste', '새로운 발견': 'new', 가까운: 'near', 인기: 'hot' };
const noDist = (arr) => arr.filter((x) => !x.includes('걸어서') && !/^\d+m$/.test(x.trim()));  // 거리는 따로 보여주므로 이유에서 제외
const tagChip = (t) => t ? `<span class="tag ${TAG_CLASS[t] || ''}">${esc(t)}</span>` : '';
const SLOT_ICON = { 아침: '🌅', 점심: '☀️', 오후: '☕', 저녁: '🌆', 야식: '🌙' };

// ===== 홈 (시안 61:499): 결제 QR + 키오스크 QR 찍기 + 결제수단(전체 ∨) + 추천 =====
const methodName = () => S.selected === 0 ? '전체' : S.methods[S.selected - 1]?.display_name || '전체';
async function renderHome() {
  S.methods = await api('/api/me/payment-methods');
  if (S.selected > S.methods.length) S.selected = 0;
  $('#screen').innerHTML = `
    <div class="pay-hero">
      <h2>결제 QR코드</h2>
      <div class="pay-qr" id="qrBox"></div>
      <div class="pay-timer" id="qrTimerTxt">&nbsp;</div>
      <p class="pay-guide">키오스크 첫 화면에서 이 QR을 카메라에 보여주세요</p>
    </div>
    <div class="grad-bar"></div>
    <button class="method-pick" id="methodPick"><span id="methodLabel">${esc(methodName())}</span><svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>
      <small id="methodSub">${S.selected === 0 ? '등록한 순서대로 자동 결제' : ''}</small></button>
    <div class="method-list hidden" id="methodList">
      ${[{ id: null, display_name: '전체', sub: '등록한 순서대로 자동 결제' }, ...S.methods].map((m, i) => {
        const [bg, fg] = i === 0 ? ['var(--mint)', '#fff'] : CARD_STYLE[m.pay_type] || ['#555', '#fff'];
        return `<button class="m-opt ${i === S.selected ? 'sel' : ''}" data-i="${i}"><span class="dot" style="background:${bg};color:${fg}">${i === 0 ? 'ALL' : esc((m.display_name || '?')[0])}</span>
          <span><b>${esc(m.display_name)}</b><small>${i === 0 ? m.sub : esc(typeLabel(m.pay_type)) + ' ' + esc(m.masked_number || '')}</small></span></button>`;
      }).join('')}
    </div>
    <div class="pt-row" id="pointToggle"><span>포인트 먼저 사용</span><span class="switch ${S.usePoints ? 'on' : ''}"></span></div>
    <div id="homeReco"><p class="muted">추천을 불러오는 중…</p></div>`;
  $('#screen').onclick = (e) => {
    if (e.target.closest('#qrBox')) return openCardPicker();
    if (e.target.closest('#methodPick')) { $('#methodList').classList.toggle('hidden'); $('#methodPick').classList.toggle('open'); return; }
    const opt = e.target.closest('.m-opt');
    if (opt) {
      S.selected = +opt.dataset.i;
      document.querySelectorAll('.m-opt').forEach((x) => x.classList.toggle('sel', x === opt));
      $('#methodLabel').textContent = methodName();
      $('#methodSub').textContent = S.selected === 0 ? '등록한 순서대로 자동 결제' : '';
      $('#methodList').classList.add('hidden'); $('#methodPick').classList.remove('open');
      return issueQr();
    }
    if (e.target.closest('#pointToggle')) { S.usePoints = !S.usePoints; $('#pointToggle .switch').classList.toggle('on', S.usePoints); return issueQr(); }
    const b = e.target.closest('[data-store]'); if (b) return openStore(+b.dataset.store);
    if (e.target.closest('#toMap')) go('map');
  };
  issueQr();
  renderHomeReco().catch(() => { const el = $('#homeReco'); if (el) el.innerHTML = ''; });
}

async function renderHomeReco() {
  const loc = await getLoc();
  const q = `?lat=${loc.lat}&lng=${loc.lng}&limit=4`;
  const [p, beh, stores] = await Promise.all([api('/api/me/taste-profile'), api('/api/me/behavior'), api('/api/me/recommendations/stores' + q)]);
  const el = $('#homeReco'); if (!el || S.view !== 'home') return;
  const meter = (label, v) => v == null ? '' : `<div class="meter"><span style="width:62px">${label}</span><div class="bar"><i style="width:${(v / 5) * 100}%"></i></div><span>${v}</span></div>`;
  const hour = new Date().getHours();
  const slotNow = hour < 5 || hour >= 21 ? '야식' : hour < 10 ? '아침' : hour < 15 ? '점심' : hour < 17 ? '오후' : '저녁';
  const maxSlot = Math.max(1, ...beh.slots.map((x) => x.count));
  el.innerHTML = `
    <div class="section-title">${SLOT_ICON[slotNow]} 지금 ${slotNow}, 이런 곳 어때요?</div>
    ${stores.map((s, i) => `
      <button class="reco ${i === 0 ? 'first' : ''}" data-store="${s.store_id}">
        <span class="store-thumb" style="background:${colorFor(s.category || s.name)}">${esc(s.name[0])}</span>
        <span class="reco-body">
          <span class="reco-top"><b>${esc(s.name)}</b>${tagChip(s.tag)}</span>
          ${discBadge(s.discount)}
          <small>${esc(s.category)}${s.distance_m != null ? ' · ' + distText(s.distance_m) + ' · 도보 ' + s.walk_min + '분' : ''}${s.is_open ? '' : ' · <em>영업 전</em>'}</small>
          <span class="reco-why">${esc(s.ai_comment || noDist(s.reasons).slice(0, 2).join(' · '))}</span>
          <span>${s.recommended_menus.map((m) => `<span class="chip ai">${esc(m)}</span>`).join('')}</span>
        </span>
      </button>`).join('') || '<p class="muted">추천할 가게가 아직 없어요.</p>'}
    <button class="ghost-pill" id="toMap" style="margin:4px 0 8px">지도에서 보기</button>
    <div class="section-title">나의 외식 패턴</div>
    <div class="card">
      <p style="margin:0 0 14px;line-height:1.55">${esc(beh.summary)}</p>
      ${beh.visit_count ? `
      <div class="slots">${['아침', '점심', '오후', '저녁', '야식'].map((sl) => {
        const c = beh.slots.find((x) => x.slot === sl)?.count || 0;
        return `<div class="slot ${sl === slotNow ? 'now' : ''}"><i style="height:${(c / maxSlot) * 100}%"></i><span>${sl}</span></div>`;
      }).join('')}</div>
      <div class="stats">
        <div><b>${beh.visit_count}</b><span>방문</span></div>
        <div><b>${won(beh.avg_order_value)}</b><span>평균 결제</span></div>
        <div><b>${beh.avg_days_between_visits ?? '-'}일</b><span>방문 주기</span></div>
      </div>` : ''}
    </div>
    <div class="section-title">AI가 분석한 내 입맛</div>
    <div class="card profile">
      <p>${esc(p.summary)}</p>
      ${Object.keys(p.taste_tolerance || {}).length  // 직접 설정한 '잘 먹는 정도' 5가지 (없으면 주문 기록 기반 맵기·단맛)
        ? Object.entries(p.taste_tolerance).map(([k, v]) => meter(k, v)).join('')
        : meter('맵기', p.spicy_preference) + meter('단맛', p.sweet_preference)}
      <div style="margin-top:10px">${[...(p.allergies || []).map((a) => '⚠ ' + a), ...(p.diet || []), ...p.favorite_categories, ...p.favorite_menus.slice(0, 3)]
        .map((x) => `<span class="chip">${esc(x)}</span>`).join('')}</div>
    </div>`;
  hydrateCounters(el);
}

// ===== QR 탭 → 결제 카드 고르기 (React Bits Depth Carousel) =====
function cardFace(m, i) {
  if (i === 0) return `<div class="ccard" style="background:linear-gradient(135deg,var(--mint),var(--sky))"><span class="t">자동 결제</span>
    <span class="n">전체 · 우선순위대로</span><span class="m">${S.methods.slice(0, 3).map((x) => esc(x.display_name)).join(' → ') || '결제수단 등록 필요'}</span></div>`;
  const [bg, fg] = CARD_STYLE[m.pay_type] || ['#555', '#fff'];
  return `<div class="ccard" style="background:linear-gradient(135deg,${bg},${bg}cc);color:${fg}"><span class="t">${esc(typeLabel(m.pay_type))}${m.region ? ' · ' + esc(m.region) : ''}</span>
    <span class="chip-ic"></span><span><span class="n">${esc(m.display_name)}</span><br><span class="m">${esc(m.masked_number || '•••• ••••')}</span></span></div>`;
}
function openCardPicker() {
  const list = [null, ...S.methods];
  let pick = S.selected;
  openSheet(`<div class="picker-head"><h2>결제 카드 선택</h2><p>옆으로 넘기거나 카드를 눌러 고르세요</p></div>
    <div id="dcRoot"></div><div class="picker-name" id="pickName"></div>
    <button class="mint-btn sm" id="pickOk">이 카드로 QR 만들기</button>`);
  const name = (i) => (i === 0 ? '전체 (등록 순서대로 자동 결제)' : list[i].display_name);
  $('#pickName').textContent = name(pick);
  const dc = UFX.depthCarousel($('#dcRoot'), list.map((m, i) => cardFace(m, i)), {
    start: pick, cardWidth: 250, cardHeight: 158, onChange: (i) => { pick = i; $('#pickName').textContent = name(i); },
    onPick: () => $('#pickOk').click(),
  });
  $('#pickOk').onclick = () => {
    S.selected = pick; closeSheet();
    const lb = $('#methodLabel'); if (lb) { lb.textContent = methodName(); $('#methodSub').textContent = S.selected === 0 ? '등록한 순서대로 자동 결제' : ''; }
    document.querySelectorAll('.m-opt').forEach((x) => x.classList.toggle('sel', +x.dataset.i === S.selected));
    issueQr();
    toast(`${name(pick)}(으)로 결제 QR을 만들었어요`);
  };
}

// ===== 지도 =====
let MAP = null;
function destroyMap() { if (MAP) { MAP.remove(); MAP = null; } }
const CATS = ['전체', '한식', '분식', '일식', '중식', '양식', '카페', '샐러드', '고기', '주점'];

async function renderMap() {
  const loc = await getLoc();
  $('#screen').innerHTML = `
    <div class="map-wrap">
      <div id="map"></div>
      <div class="map-top">
        <div class="map-search">
          <label><input id="mapQ" placeholder="식당 검색" autocomplete="off"><svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg></label>
          <button class="ai-btn" id="aiPick" title="AI 추천">AI</button>
        </div>
        <div class="map-chips" id="mapChips">${CATS.map((c, i) => `<button class="mchip ${i === 0 ? 'on' : ''}" data-cat="${c}">${c}</button>`).join('')}<button class="mchip" id="openNow">영업 중</button></div>
      </div>
      <div class="ai-list hidden" id="aiList"></div>
      <button class="locate" id="locate" title="내 위치">◎</button>
      ${loc.demo ? '<div class="demo-note">데모 위치(망원동)</div>' : ''}
      <div class="pin-card hidden" id="pinCard"></div>
    </div>`;
  if (!window.L) { $('#map').innerHTML = '<p class="muted" style="padding:20px">지도를 불러오지 못했어요.</p>'; return; }
  MAP = L.map('map', { zoomControl: false, attributionControl: true }).setView([loc.lat, loc.lng], 16);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    maxZoom: 19, subdomains: 'abcd', attribution: '© OpenStreetMap © CARTO',
  }).addTo(MAP);
  L.marker([loc.lat, loc.lng], { icon: L.divIcon({ className: '', html: '<div class="me-dot"></div>', iconSize: [18, 18] }), zIndexOffset: 1000 }).addTo(MAP);
  const layer = L.layerGroup().addTo(MAP);
  const filt = { cat: '전체', open: false, q: '' };
  let PINS = [], MARKERS = {};

  async function load() {
    const qs = new URLSearchParams({ lat: loc.lat, lng: loc.lng });
    if (filt.cat !== '전체') qs.set('category', filt.cat);
    if (filt.open) qs.set('open_now', 'true');
    const pins = await api('/api/map/stores?' + qs);
    if (!MAP) return;
    PINS = pins; draw();
  }
  function draw() {
    layer.clearLayers(); MARKERS = {};
    const q = filt.q.toLowerCase();
    const shown = PINS.filter((p) => !q || [p.name, p.category, p.signature_menu, p.tagline].some((x) => (x || '').toLowerCase().includes(q)));
    shown.forEach((p) => {
      const hi = p.recommend?.highlight;
      const html = `<div class="pin ${hi ? 'hi' : ''} ${p.is_open ? '' : 'closed'}" style="--c:${colorFor(p.category || p.name)}">
        <span class="pin-dot"><i>${esc(p.name[0])}</i></span>${hi ? `<span class="pin-label">${esc(p.recommend.tag)}</span>` : ''}</div>`;
      const m = L.marker([p.lat, p.lng], { icon: L.divIcon({ className: '', html, iconSize: [40, 40], iconAnchor: [20, 40] }), zIndexOffset: hi ? 500 : 0 });
      m.on('click', () => showPin(p));
      m.addTo(layer); MARKERS[p.id] = p;
    });
    $('#pinCard').classList.add('hidden');
    if (q && shown.length) MAP.panTo([shown[0].lat, shown[0].lng]);
    if (q && !shown.length) toast('검색 결과가 없어요');
  }

  function showPin(p) {
    const r = p.recommend;
    const card = $('#pinCard');
    card.innerHTML = `
      <div class="pc-head">
        <span class="store-thumb" style="background:${colorFor(p.category || p.name)}">${esc(p.name[0])}</span>
        <div style="flex:1;min-width:0"><div class="reco-top"><b>${esc(p.name)}</b>${r ? tagChip(r.tag) : ''}</div>
          <small class="muted">${esc(p.category)} · ${p.is_open ? '<span class="open">영업 중</span>' : '<span class="closed-t">영업 전</span>'} · ${distText(p.distance_m)} · 도보 ${p.walk_min}분</small></div>
        <button class="x" id="pcClose">✕</button>
      </div>
      <p class="pc-line">${esc(p.tagline)}</p>
      ${p.discount ? `<div style="margin:0 0 8px">${discBadge(p.discount)}</div>` : ''}
      <div class="pc-meta"><span>대표 <b>${esc(p.signature_menu || '-')}</b></span>${p.price_range ? `<span>${won(p.price_range[0])} ~ ${won(p.price_range[1])}</span>` : ''}</div>
      ${r ? `<p class="reco-why" style="margin:8px 0 0">✦ ${esc(noDist(r.reason.split(' · ')).join(' · ') || r.reason)}</p>` : ''}
      <button class="btn primary big" id="pcMore" style="margin-top:12px">자세히 보기</button>`;
    hydrateCounters(card);
    card.classList.remove('hidden'); $('#aiList').classList.add('hidden'); $('#aiPick').classList.remove('on');
    MAP.panTo([p.lat, p.lng], { animate: true });
    $('#pcClose').onclick = () => card.classList.add('hidden');
    $('#pcMore').onclick = () => openStore(p.id);
  }

  $('#mapChips').onclick = (e) => {
    const b = e.target.closest('[data-cat]'); if (!b) return;
    filt.cat = b.dataset.cat;
    document.querySelectorAll('#mapChips .mchip').forEach((x) => x.classList.toggle('on', x === b));
    load();
  };
  $('#openNow').onclick = (e) => { e.stopPropagation(); filt.open = !filt.open; e.currentTarget.classList.toggle('on', filt.open); load(); };
  let qT; $('#mapQ').oninput = (e) => { clearTimeout(qT); qT = setTimeout(() => { filt.q = e.target.value.trim(); draw(); }, 200); };
  // AI 버튼: 내 패턴 기반 추천 가게 목록 → 누르면 지도에서 보여줌
  $('#aiPick').onclick = async () => {
    const box = $('#aiList'), btn = $('#aiPick');
    if (!box.classList.contains('hidden')) { box.classList.add('hidden'); btn.classList.remove('on'); return; }
    btn.classList.add('on'); $('#pinCard').classList.add('hidden');
    box.innerHTML = '<p class="muted">AI가 고르는 중…</p>'; box.classList.remove('hidden');
    try {
      const rs = await api(`/api/me/recommendations/stores?lat=${loc.lat}&lng=${loc.lng}&limit=3`);
      box.innerHTML = `<h3><span>✦ AI 추천</span><button class="x" id="aiClose">✕</button></h3>` + rs.map((s) => `
        <button class="reco" data-ai="${s.store_id}"><span class="store-thumb" style="background:${colorFor(s.category || s.name)}">${esc(s.name[0])}</span>
          <span class="reco-body"><span class="reco-top"><b>${esc(s.name)}</b>${tagChip(s.tag)}</span>
          <span class="reco-why">${esc(s.ai_comment || noDist(s.reasons).slice(0, 2).join(' · '))}</span></span></button>`).join('');
    } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; }
  };
  $('#aiList').onclick = (e) => {
    if (e.target.closest('#aiClose')) { $('#aiList').classList.add('hidden'); $('#aiPick').classList.remove('on'); return; }
    const b = e.target.closest('[data-ai]'); if (!b) return;
    const p = PINS.find((x) => x.id === +b.dataset.ai);
    $('#aiList').classList.add('hidden'); $('#aiPick').classList.remove('on');
    if (p) showPin(p); else openStore(+b.dataset.ai);
  };
  $('#locate').onclick = () => MAP.setView([loc.lat, loc.lng], 16);
  await load();
  setTimeout(() => MAP && MAP.invalidateSize(), 50);
}

// ===== 가게 상세 (지도·홈 공통) =====
async function openStore(id) {
  const loc = await getLoc();
  const d = await api(`/api/map/stores/${id}?lat=${loc.lat}&lng=${loc.lng}`);
  const f = d.for_me || {};
  openSheet(`
    <div class="detail-hero" style="background:${colorFor(d.category || d.name)}">${esc(d.name[0])}</div>
    <div class="reco-top" style="margin-top:14px;justify-content:space-between;flex-wrap:nowrap"><h2 style="margin:0">${esc(d.name)}</h2>${d.for_me ? '<button class="bt-host" id="storeBell"></button>' : ''}</div>
    <p class="muted" style="margin:4px 0 0">${esc(d.category)} · ${esc(d.tagline)}</p>
    ${d.discount ? `<div class="disc-card"><span class="rate">${d.discount.rate}%<small>OFF</small></span>
      <span style="flex:1;min-width:0"><b>${esc(d.discount.title)}</b><span class="l">끝나기까지</span><br><span data-count="${d.discount.seconds_left}"></span></span></div>` : ''}
    <div class="info-grid">
      <div><span>영업</span><b class="${d.is_open ? 'open' : 'closed-t'}">${d.is_open ? '영업 중' : '영업 전'}</b><small>${esc(d.hours)}</small></div>
      <div><span>거리</span><b>${distText(d.distance_m) || '-'}</b><small>${d.walk_min ? '도보 ' + d.walk_min + '분' : ''}</small></div>
      <div><span>내 포인트</span><b>${(f.point_balance || 0).toLocaleString()}P</b><small>적립 ${Math.round(d.point_rate * 100)}%</small></div>
    </div>
    ${noDist(f.why_this_store || []).length ? `<div class="why">✦ ${noDist(f.why_this_store).slice(0, 3).map(esc).join(' · ')}</div>` : ''}
    ${f.usual_items?.length ? `<div class="card usual"><b>늘 먹던 거</b><div>${f.usual_items.map((u) => `<span class="chip">${esc(u.name)} · ${u.order_count}번</span>`).join('')}</div></div>` : ''}
    ${f.recommended_menus?.length ? `<div class="card"><h3>✦ 나에게 추천</h3>${f.recommended_menus.map((r) => `
      <div class="menu-line"><span><b>${esc(r.menu.name)}</b><br><small class="muted">${esc(r.reason)}</small></span><b>${won(r.menu.price)}</b></div>`).join('')}</div>` : ''}
    ${d.popular_menus.length ? `<div class="card"><h3>🔥 인기 메뉴</h3>${d.popular_menus.map((m, i) => `<div class="menu-line"><span>${i + 1}. ${esc(m.name)}</span><small class="muted">최근 30일 ${m.sold_30d}개</small></div>`).join('')}</div>` : ''}
    <div class="card"><h3>메뉴</h3>${d.menus.map((g) => `<div class="menu-group">${esc(g.category)}</div>${g.items.map((m) => `
      <div class="menu-line"><span>${esc(m.name)} <small class="muted">${m.spicy_level ? '🌶'.repeat(Math.min(m.spicy_level, 3)) : ''}</small><br><small class="muted">${esc(m.description)}</small></span><span>${won(m.price)}</span></div>`).join('')}`).join('')}</div>
    <div class="card"><h3>가게 정보</h3>
      <div class="menu-line"><span class="muted">주소</span><span>${esc(d.address)}</span></div>
      <div class="menu-line"><span class="muted">전화</span><a href="tel:${esc(d.phone)}">${esc(d.phone)}</a></div>
      <div class="menu-line"><span class="muted">결제</span><span style="text-align:right">${d.pay_types.map(esc).join(', ')}</span></div>
    </div>
    <button class="btn ghost big" data-close>닫기</button>`);
  hydrateCounters($('#sheetBody'));
  const bell = $('#storeBell');
  if (bell) UFX.bellToggle(bell, {
    on: !!f.alert_on, onLabel: '알림 켜짐', offLabel: '알림 받기',
    onChange: async (on) => {
      try { await api(`/api/me/store-alerts/${d.id}`, { method: 'PUT', body: { on } }); toast(on ? `${d.name}의 할인·새 메뉴 소식을 알려드릴게요` : '알림을 껐어요', '', ); }
      catch (e) { toast(e.message, 'error'); throw e; }
    },
  });
}

async function issueQr() {
  stopQr();
  const box = $('#qrBox'); if (!box) return;
  const method_id = S.selected === 0 ? null : S.methods[S.selected - 1]?.id ?? null;
  box.classList.add('dim');
  const seq = (S.qrSeq = (S.qrSeq || 0) + 1);
  let qr;
  try {
    qr = await api('/api/me/payment-qr', { method: 'POST', body: { method_id, use_points: S.usePoints } });
  } catch (e) { box.innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  if (seq !== S.qrSeq || S.view !== 'home') return; // 더 최근 요청이 있으면 무시
  S.qr = qr;
  const q = qrcode(0, 'M'); q.addData(S.qr.qr_payload); q.make();
  box.classList.remove('dim');
  box.innerHTML = q.createSvgTag({ cellSize: 6, margin: 2, scalable: true });
  // 서버 유효시간(기본 60초)보다 조금 일찍 새 QR로 교체
  const until = Date.now() + 55 * 1000;
  const tick = () => {
    const left = Math.max(0, Math.round((until - Date.now()) / 1000));
    const el = $('#qrTimerTxt'); if (el) el.innerHTML = `<b>${left}</b>초 후 새 QR로 바뀌어요`;
    if (left <= 0) issueQr();
  };
  tick(); S.qrTimer = setInterval(tick, 1000);
  S.pollTimer = setInterval(pollQr, 1500);
}
function stopQr() { S.qrSeq = (S.qrSeq || 0) + 1; clearInterval(S.qrTimer); clearInterval(S.pollTimer); S.qrTimer = S.pollTimer = null; }

async function pollQr() {
  if (!S.qr) return;
  let st; try { st = await api('/api/me/payment-qr/' + S.qr.token); } catch { return; }
  if (!st.used || !st.result) return;
  stopQr();
  if (st.result.type === 'identified') return showLinked(S.qr.token, st.result);
  showPaidResult(st.result);
}

// 키오스크 첫 화면에서 QR을 찍음 → '연결됨' 표시 후, 키오스크에서 결제하면 결과까지 이어서 보여줌
function showLinked(token, info) {
  S.linked = true; stopQr();
  openSheet(`
    <div class="result"><div class="icon ok" style="background:var(--mint)">⇄</div>
      <h2>키오스크와 연결됐어요</h2>
      <p class="muted">${esc(info.store)} · ${esc(info.kiosk || '')}</p></div>
    <div class="card" style="text-align:center"><b>💳 ${info.method ? esc(info.method) + '로 결제돼요' : '등록한 결제수단 순서대로 결제돼요'}</b>
      <p class="muted" style="margin:6px 0 0">키오스크에서 주문하고 ‘결제 계속하기’를 누르면 바로 결제돼요.<br>다른 카드는 키오스크에서 ‘결제 방식 바꾸기’로 고를 수 있어요.</p></div>
    <button class="mint-btn sm" data-close>확인</button>`, () => { S.linked = false; go('home'); });  // 다 쓴 QR 대신 새 QR
  clearInterval(S.linkTimer);
  const until = Date.now() + 30 * 60 * 1000;
  S.linkTimer = setInterval(async () => {
    if (Date.now() > until || !TOKEN) return clearInterval(S.linkTimer);
    let st; try { st = await api('/api/me/payment-qr/' + token); } catch { return; }
    if (st.result?.type === 'paid') { clearInterval(S.linkTimer); showPaidResult(st.result); }
  }, 2000);
}

function showPaidResult(r) {
  const attempts = (r.attempts || []).map((a) => `<li class="${a.success ? 'ok' : 'fail'}"><div><b>${esc(a.label)}</b><small>${esc(a.message)}</small></div><b>${won(a.amount)}</b></li>`).join('');
  openSheet(r.success ? `
      <div class="result"><div class="icon ok">✓</div><h2>${won(r.paid_amount)} 결제 완료</h2>
      <p class="muted">포인트 ${(r.points_used || 0).toLocaleString()}P 사용 · ${(r.points_earned || 0).toLocaleString()}P 적립</p></div>
      <ul class="attempts">${attempts}</ul><button class="btn primary big" data-close>확인</button>` : `
      <div class="result"><div class="icon fail">!</div><h2>결제 실패</h2><p class="muted">등록된 결제수단으로 결제하지 못했어요.</p></div>
      <ul class="attempts">${attempts}</ul><button class="btn primary big" data-close>다시 시도</button>`, () => go('home'));
}

// ===== 지갑 (시안 109:513): 지금까지 받은 포인트 + 결제 =====
const LINKS = [['naver_pay', 'N', '네이버 결제수단'], ['kakao_pay', 'K', '카카오 결제수단'], ['samsung_pay', 'S', '삼성페이 연동하기']];
async function renderWallet() {
  const [methods, points] = await Promise.all([api('/api/me/payment-methods'), api('/api/me/points')]);
  S.methods = methods;
  const has = (t) => methods.some((m) => m.pay_type === t);
  $('#screen').innerHTML = `
    <div class="w-title">지금까지 받은 포인트</div>
    <div class="gray-card">
      ${points.map((p) => `<div class="pt-item"><span class="won">₩</span>
        <span><b>${esc(p.store_name)}</b><small>${(p.total_spent || 0).toLocaleString()}원 결제 · <span class="pt-bal">잔액 ${p.balance.toLocaleString()}P</span></small></span>
        <span class="pt-pill">+${(p.last_earned || 0).toLocaleString()} 포인트</span></div>`).join('') || '<p class="muted" style="padding:10px">아직 적립된 포인트가 없어요. 유니오더 가맹점에서 결제하면 그 가게 포인트가 쌓여요.</p>'}
    </div>
    <div class="w-title">결제</div>
    <div class="gray-card">
      ${LINKS.map(([t, l, label]) => {
        const [bg, fg] = CARD_STYLE[t];
        return `<button class="link-row ${has(t) ? 'done' : ''}" data-link="${t}"><span class="lg" style="background:${bg};color:${fg}">${l}</span>${label}<em>${has(t) ? '연동됨' : '연동하기 ›'}</em></button>`;
      }).join('')}
    </div>
    <div class="w-title" style="font-size:17px">결제 우선순위 <small class="muted" style="font-weight:500">위에서부터 차례로 결제해요</small></div>
    <div class="gray-card">
      ${methods.map((m, i) => `
        <div class="method"><span class="rank">${i + 1}</span>
          <div class="info"><b>${esc(m.display_name)}</b><small>${esc(typeLabel(m.pay_type))} ${esc(m.masked_number)} ${esc(m.region)}</small></div>
          <div class="arrows"><button data-up="${i}" ${i === 0 ? 'disabled' : ''}>↑</button><button data-down="${i}" ${i === methods.length - 1 ? 'disabled' : ''}>↓</button><button data-del="${m.id}">✕</button></div>
        </div>`).join('') || '<p class="muted">등록된 결제수단이 없어요.</p>'}
      <button class="mint-btn sm" id="addMethod" style="margin-top:12px">+ 결제수단 등록</button>
    </div>`;
  $('#screen').onclick = async (e) => {
    const up = e.target.closest('[data-up]'), down = e.target.closest('[data-down]'), del = e.target.closest('[data-del]'), link = e.target.closest('[data-link]');
    if (up || down) {
      const i = +(up ? up.dataset.up : down.dataset.down), j = up ? i - 1 : i + 1;
      const ids = S.methods.map((m) => m.id);[ids[i], ids[j]] = [ids[j], ids[i]];
      await api('/api/me/payment-methods/priority', { method: 'PUT', body: { method_ids: ids } });
      renderWallet();
    }
    if (del) { await api('/api/me/payment-methods/' + del.dataset.del, { method: 'DELETE' }); toast('삭제했어요'); renderWallet(); }
    if (link) { if (link.classList.contains('done')) toast('이미 연동돼 있어요'); else openAddMethod(link.dataset.link); }
    if (e.target.closest('#addMethod')) openAddMethod();
  };
}

function openAddMethod(preset) {
  openSheet(`
    <h2>결제수단 등록</h2><p class="muted">데모라 실제 카드 정보는 입력하지 마세요.</p>
    <form class="form" id="methodForm" style="margin-top:14px">
      <label>종류<select name="pay_type">${PAY_TYPES.filter((p) => p.value !== 'dodo_point').map((p) => `<option value="${p.value}" ${p.value === preset ? 'selected' : ''}>${esc(p.label)}</option>`).join('')}</select></label>
      <label>이름<input name="display_name" placeholder="예) 국민 체크카드, 성남사랑상품권" value="${preset ? esc(typeLabel(preset)) : ''}" required></label>
      <label>카드 끝 4자리 (선택)<input name="last4" maxlength="4" inputmode="numeric" placeholder="1234"></label>
      <label>지역 (지역화폐만)<input name="region" placeholder="예) 서울 마포구"></label>
      <label>데모 잔액 (페이머니·상품권, 선택)<input name="mock_balance" type="number" placeholder="비우면 무제한"></label>
      <button class="mint-btn sm">등록</button>
    </form>`);
  $('#methodForm').onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try {
      await api('/api/me/payment-methods', { method: 'POST', body: {
        pay_type: f.pay_type, display_name: f.display_name, region: f.region,
        masked_number: f.last4 ? '****-' + f.last4 : '', mock_balance: f.mock_balance ? +f.mock_balance : null } });
      closeSheet(); toast('등록했어요'); renderWallet();
    } catch (err) { toast(err.message); }
  };
}

// ===== 내 정보 (시안 109:567) =====
const IC = {"food": "<path d=\"M7 3v8M5 3v4a2 2 0 0 0 4 0V3M7 11v10M16 3c-2 1.5-2.5 4-2.5 7h2.5v11\"/>", "gear": "<circle cx=\"12\" cy=\"12\" r=\"3\"/><path d=\"M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1\"/>", "bell": "<path d=\"M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z\"/><path d=\"M10 20a2 2 0 0 0 4 0\"/>", "list": "<path d=\"M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01\"/>", "tip": "<path d=\"M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9V16h7v-2.1A6 6 0 0 0 12 3z\"/>", "info": "<circle cx=\"12\" cy=\"12\" r=\"9\"/><path d=\"M12 11v5M12 8h.01\"/>"};
const mItem = (id, ic, label) => `<button class="menu-item" data-m="${id}"><span class="ic"><svg viewBox="0 0 24 24">${IC[ic]}</svg></span>${label}<i>›</i></button>`;
async function renderMe() {
  $('#screen').innerHTML = `
    <div class="prof"><span class="avatar">${esc((ME.name || '손')[0])}</span><div><b>${esc(ME.name)}</b><small>${esc(ME.email)}</small></div></div>
    <div class="menu-box">${mItem('taste', 'food', '내 입맛 설정하기')}</div>
    <div class="menu-box">${mItem('settings', 'gear', '일반설정')}${mItem('notify', 'bell', '알림')}</div>
    <div class="menu-box">${mItem('orders', 'list', '주문 내역')}${mItem('tips', 'tip', '팁과 사용 설명서')}${mItem('about', 'info', '앱 정보')}</div>
    <button class="ghost-pill" id="logout">로그아웃</button>`;
  $('#screen').onclick = (e) => {
    if (e.target.closest('#logout')) return logout();
    const m = e.target.closest('[data-m]')?.dataset.m; if (!m) return;
    ({ taste: openTaste, orders: openOrders, settings: openSettings, notify: openNotify, tips: openTips, about: openAbout })[m]();
  };
}
// ===== 입맛 설정 (가입 직후 + 내 정보 › 선호 음식 설정하기) =====
const TASTES = [['spicy', '매운맛', '🌶'], ['salty', '짠맛', '🧂'], ['sour', '신맛', '🍋'], ['sweet', '단맛', '🍯'], ['oily', '느끼한 맛', '🧈']];
const LEVEL_TXT = ['전혀 못 먹어요', '조금만 먹어요', '약간 먹어요', '보통이에요', '잘 먹어요', '아주 잘 먹어요'];
// 값은 메뉴의 알레르기 표기와 같은 단어 (추천에서 걸러냄)
const ALLERGY_CHIPS = [['땅콩', '땅콩'], ['갑각류', '갑각류(새우·게)'], ['조개', '조개'], ['생선', '생선'], ['우유', '우유'],
  ['계란', '계란'], ['밀', '밀'], ['대두', '대두'], ['돼지고기', '돼지고기'], ['소고기', '소고기']];
const DIET_CHIPS = ['채식', '비건', '할랄', '저염', '저당', '다이어트'];
function openTaste(onboarding = false) {
  const p = ME.preferences || {};
  const chips = (id, items, chosen) => `<div class="pick-chips" id="${id}">${items.map(([v, label]) =>
    `<button type="button" data-v="${esc(v)}" class="${chosen.includes(v) ? 'on' : ''}">${esc(label)}</button>`).join('')}</div>`;
  const known = ALLERGY_CHIPS.map(([v]) => v);
  const extraAllergy = (p.allergies || []).filter((a) => !known.includes(a));  // 특이사항 글에서 뽑힌 것 등
  openSheet(`<div class="taste">
    ${onboarding ? `<h2>반가워요, ${esc(ME.name)}님!</h2><p class="muted lead">입맛을 알려주시면 키오스크 AI 직원이 기억하고 챙겨드려요</p>`
      : `<h2>내 입맛 설정</h2><p class="muted lead">키오스크 AI 직원과 가게 추천이 이걸 보고 골라드려요</p>`}
    <h3>얼마나 잘 드세요?</h3>
    ${TASTES.map(([k, label, ic]) => `<div class="t-row"><div class="t-head"><span>${ic} ${label}</span><b id="tv-${k}">${LEVEL_TXT[p[k] ?? 3]}</b></div>
      <input type="range" min="0" max="5" step="1" data-taste="${k}" value="${p[k] ?? 3}" style="--v:${(p[k] ?? 3) * 20}%"></div>`).join('')}
    <h3>알레르기 <small>있는 것만 눌러주세요</small></h3>
    ${chips('allergyChips', ALLERGY_CHIPS, p.allergies || [])}
    ${extraAllergy.length ? `<p class="muted tiny">특이사항에서 찾은 알레르기: ${esc(extraAllergy.join(', '))}</p>` : ''}
    <h3>식단</h3>
    ${chips('dietChips', DIET_CHIPS.map((d) => [d, d]), p.diet || [])}
    <h3>이런 거 좋아요</h3>
    <textarea id="likesText" rows="2" maxlength="500" placeholder="예) 꾸덕한 크림 파스타, 새우 들어간 요리 좋아해요">${esc(p.likes_text || '')}</textarea>
    <h3>이런 거 싫어요</h3>
    <textarea id="dislikesText" rows="2" maxlength="500" placeholder="예) 오이랑 고수는 못 먹어요. 너무 단 소스는 별로예요">${esc(p.dislikes_text || '')}</textarea>
    <h3>특이사항</h3>
    <textarea id="notesText" rows="2" maxlength="500" placeholder="예) 임신 중이라 날음식은 피해요 · 아이와 자주 와요 · 교정 중이라 딱딱한 건 힘들어요">${esc(p.notes || '')}</textarea>
    <button class="mint-btn" id="savePref">${onboarding ? '이대로 시작하기' : '저장하기'}</button>
    ${onboarding ? '<button class="link-sm skip" data-close>나중에 할게요</button>' : ''}
  </div>`);
  $('#sheetBody').oninput = (e) => {
    const k = e.target.dataset.taste; if (!k) return;
    $('#tv-' + k).textContent = LEVEL_TXT[+e.target.value]; e.target.style.setProperty('--v', e.target.value * 20 + '%');
  };
  $('#sheetBody').onclick = async (e) => {
    const chip = e.target.closest('.pick-chips [data-v]');
    if (chip) return chip.classList.toggle('on');
    if (!e.target.closest('#savePref')) return;
    const picked = (id) => [...document.querySelectorAll(`#${id} .on`)].map((b) => b.dataset.v);
    const body = { allergies: [...picked('allergyChips'), ...extraAllergy], diet: picked('dietChips'),
      likes_text: $('#likesText').value.trim(), dislikes_text: $('#dislikesText').value.trim(), notes: $('#notesText').value.trim() };
    document.querySelectorAll('[data-taste]').forEach((r) => (body[r.dataset.taste] = +r.value));
    const btn = $('#savePref'); btn.disabled = true; btn.textContent = 'AI가 입맛을 정리하는 중…';
    try {
      ME = await api('/api/auth/me/preferences', { method: 'PUT', body });
      closeSheet(); toast('입맛을 저장했어요'); if (S.view === 'home') go('home');
    } catch (err) { toast(err.message); btn.disabled = false; btn.textContent = '다시 저장하기'; }
  };
}
async function openOrders() {
  const orders = await api('/api/me/orders');
  openSheet(`<h2>주문 내역</h2>
    ${orders.map((o) => `<div class="order-row"><div class="top"><span>${esc(o.store_name || '주문 #' + o.id)}</span><span>${won(o.total_amount)}</span></div>
      <span class="muted">${new Date(o.created_at).toLocaleDateString('ko-KR')} · ${o.items.map((i) => esc(i.name) + (i.quantity > 1 ? '×' + i.quantity : '')).join(', ')} · ${o.status === 'paid' ? '결제완료' : o.status}</span></div>`).join('') || '<p class="muted">주문 내역이 없어요.</p>'}
    <button class="ghost-pill" data-close style="margin-top:14px">닫기</button>`);
}
const toggleRow = (k, label, sub) => `<div class="pt-row" data-tg="${k}"><span>${label}<br><small class="muted">${sub}</small></span><span class="switch ${ls(k) !== '0' ? 'on' : ''}"></span></div>`;
function bindToggles() { $('#sheetBody').onclick = (e) => { const r = e.target.closest('[data-tg]'); if (!r) return; const on = ls(r.dataset.tg) === '0'; ls(r.dataset.tg, on ? '1' : '0'); r.querySelector('.switch').classList.toggle('on', on); }; }
function openSettings() {
  openSheet(`<h2>일반설정</h2>${toggleRow('set_points', '포인트 먼저 사용', '결제할 때 그 가게 포인트를 먼저 차감')}${toggleRow('set_loc', '위치 사용', '내 주변 가맹점 추천에 사용')}
    <button class="ghost-pill" data-close style="margin-top:14px">닫기</button>`, () => { S.usePoints = ls('set_points') !== '0'; });
  bindToggles();
}
function openNotify() {
  openSheet(`<h2>알림</h2>${toggleRow('ntf_pay', '결제 알림', '키오스크에서 결제되면 바로 알려드려요')}${toggleRow('ntf_point', '포인트 적립 알림', '적립·소멸 예정 안내')}${toggleRow('ntf_ad', '혜택·이벤트 알림', '가맹점 이벤트 소식 (선택)')}
    <button class="ghost-pill" data-close style="margin-top:14px">닫기</button>`);
  bindToggles();
}
function openTips() {
  openSheet(`<h2>팁과 사용 설명서</h2>
    <div class="card"><b>1. 키오스크와 연결</b><p class="muted" style="margin:6px 0 0">키오스크 첫 화면의 QR을 홈 화면 ‘키오스크 QR 찍기’로 찍으면, 고른 결제수단으로 주문·결제가 이어져요.</p></div>
    <div class="card"><b>2. 결제수단 고르기</b><p class="muted" style="margin:6px 0 0">홈의 ‘전체 ∨’에서 이번에 쓸 카드를 고를 수 있어요. ‘전체’면 지갑의 우선순위대로 자동 결제돼요.</p></div>
    <div class="card"><b>3. 늘 먹던 거</b><p class="muted" style="margin:6px 0 0">가게마다 대화와 주문을 기억해서, 다음 방문 때 AI 직원이 먼저 추천해 드려요.</p></div>
    <button class="ghost-pill" data-close>닫기</button>`);
}
function openAbout() {
  openSheet(`<div style="text-align:center;padding:10px 0"><div class="brand" style="justify-content:center"><img src="img/logo-mark.png" alt=""><b>UNIORDER</b></div>
    <p class="muted">사장님과 손님의 통합 테이블오더<br>버전 0.1.0 (데모)</p></div>
    <button class="ghost-pill" data-close>닫기</button>`);
}

// ===== 시트 =====
let onSheetClose = null;
function openSheet(html, onClose) { const b = $('#sheetBody'); b.onclick = b.oninput = null; b.innerHTML = html; $('#sheet').classList.remove('hidden'); onSheetClose = onClose || null; }
function closeSheet() { $('#sheet').classList.add('hidden'); const f = onSheetClose; onSheetClose = null; f && f(); }
$('#sheet').addEventListener('click', (e) => { if (e.target.id === 'sheet' || e.target.closest('[data-close]')) closeSheet(); });

// ===== 시작 =====
if (TOKEN) start(); else $('#loginView').classList.remove('hidden');
