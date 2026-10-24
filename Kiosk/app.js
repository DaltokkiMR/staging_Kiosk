// ===== 설정 =====
const API = location.protocol === 'file:' ? 'http://localhost:8000' : '';
const store_ = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch { return null; } };
let KIOSK_KEY = store_('kioskKey') || 'rolling-kiosk-key';

const S = {
  store: null, menus: [], cart: [], tab: null, health: {}, q: '',
  lang: 'ko', orderType: 'dine_in', startAI: false,
  customer: null,            // /identify 결과
  chatSession: 'k-' + Math.random().toString(36).slice(2),
  aiRecoIds: new Set(),
  scanner: null,
};

const $ = (s) => document.querySelector(s);
const won = (n) => (n ?? 0).toLocaleString('ko-KR') + ' ₩';

// 1440×960 시안을 화면 크기에 맞춰 확대/축소
// 화면을 꽉 채움: 높이 960 기준으로 배율을 잡고, 남는 가로폭은 레이아웃이 늘어나서 채움
function fitStage() {
  let k = innerHeight / 960, W = innerWidth / k, H = 960;
  if (W < 1200) { k = innerWidth / 1200; W = 1200; H = innerHeight / k; }  // 세로로 긴 화면
  const st = $('#stage');
  st.style.width = W + 'px'; st.style.height = H + 'px';
  st.style.transform = `scale(${k})`;
}
addEventListener('resize', fitStage);
// 숨은 대화창 안 입력칸에 포커스가 가도 화면이 옆으로 밀리지 않게
$('#stage').addEventListener('scroll', (e) => { e.currentTarget.scrollLeft = 0; e.currentTarget.scrollTop = 0; });

// ===== 한국어 / English =====
const I18N = {
  en: {
    touch: 'Touch the screen to start', dineIn: 'Dine in', takeout: 'Take out', aiOrder: 'Order with AI', back: '← Home',
    haveApp: 'Do you have the app?', haveAppSub: 'Show the payment QR in the app to the camera', haveAppNote: 'Your chosen payment carries through, and we remember what you liked here.', appDl: 'Download the app',
    ok: 'OK', demoQr: 'Demo QR', no: 'No', noSub: 'Order without the app', searchPh: 'Search for food...', foodOrder: 'Your order',
    cartEmpty: 'Tap a menu to add it', count: 'Items', order: 'Order', aiStaff: 'AI Staff', aiStaffSub: 'Ask anything — spiciness, allergies, recommendations',
    chatPh: 'Speak or type', send: 'Send', end: 'End', menuTitle: 'Menu', quick: 'Quick',
  },
};
const KO = {};
document.querySelectorAll('[data-i18n]').forEach((el) => (KO[el.dataset.i18n] = el.textContent));
document.querySelectorAll('[data-i18n-ph]').forEach((el) => (KO[el.dataset.i18nPh] = el.placeholder));
KO.menuTitle = '메뉴';
const t = (k) => (S.lang === 'en' && I18N.en[k]) || KO[k] || k;
const CAT_EN = { 메뉴: 'Menu', 에피타이저: 'Appetizer', 음료: 'Drinks', 디저트: 'Dessert' };
const catLabel = (c) => (S.lang === 'en' ? CAT_EN[c] || c : c);
const menuName = (m) => (S.lang === 'en' && m.name_en ? m.name_en : m.name);
function applyLang() {
  document.documentElement.lang = S.lang;
  document.querySelectorAll('[data-i18n]').forEach((el) => (el.textContent = t(el.dataset.i18n)));
  document.querySelectorAll('[data-i18n-ph]').forEach((el) => (el.placeholder = t(el.dataset.i18nPh)));
  $('#langBtn').textContent = S.lang === 'en' ? '한국어' : 'English';
  renderTabs(); renderMenus(); renderCart();
}
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', 'X-Kiosk-Key': KIOSK_KEY, ...(opts.headers || {}) },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '요청에 실패했어요');
  return data;
}

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 2600);
}

// ===== 초기화 =====
async function init() {
  try {
    S.health = await api('/api/health');
    S.store = await api('/api/kiosk/store');
    S.menus = await api('/api/kiosk/menus');
  } catch (e) {
    $('#welcomeStore').textContent = '— 서버 연결 실패';
    toast(e.message + ' · 메뉴 화면 ⋮ 에서 기기 키를 확인하세요');
    $('#splash').classList.add('hidden'); $('#welcome').classList.add('hidden'); $('#start').classList.add('hidden');
    return;
  }
  $('#welcomeStore').textContent = S.store.name;
  renderTabs(); renderMenus(); renderCart(); setupChat();
  $('#micBtn').classList.toggle('off', !S.health.stt_enabled);
  $('#micBtn').title = S.health.stt_enabled ? '말로 물어보기' : '음성 인식 미설정 (GROQ_API_KEY)';
  buildAds(); buildLogoLoop();
  showSplash();
}

// ===== ① 스플래시: 광고 =====
const AD = { i: 0, t: 0, list: [], timers: [] };
function buildAds() {
  const st = S.store, ms = S.menus.filter((m) => m.is_available !== false);
  const best = ms.filter((m) => m.image_url && m.category === '메뉴');
  const pick = (k) => best.length ? best[k % best.length] : ms[k % Math.max(1, ms.length)];
  const d = st.discount;
  const priceHtml = (m) => d ? `<s>${won(m.price)}</s>${won(Math.floor(m.price * (100 - d.rate) / 1000) * 10)}` : won(m.price);
  const ads = [];
  const hero = best.find((m) => /쉬림프|로제/.test(m.name)) || pick(0);
  if (hero) ads.push(`<div class="ad"><div class="ad-copy"><span class="ad-kicker">✦ 오늘의 추천</span>
      <h2>${esc(menuName(hero))}</h2><p>${esc(hero.description || st.tagline || '')}</p><div class="ad-price">${priceHtml(hero)}</div></div>
      ${hero.image_url ? `<img class="ad-img" src="${esc(hero.image_url)}" alt="">` : ''}</div>`);
  if (d) {
    const m2 = pick(3);
    ads.push(`<div class="ad dark"><div class="ad-badge"><span><b>${d.rate}%</b>OFF</span></div><div class="ad-copy"><span class="ad-kicker">⏰ 할인 행사</span>
      <h2>${esc(d.title)}</h2><p>${esc(st.name)} 전 메뉴에 자동 적용돼요</p>
      <div class="ad-count"><span>끝나기까지</span><span class="ufx-counter" data-count="${d.seconds_left}"></span></div></div>
      ${m2?.image_url ? `<img class="ad-img" src="${esc(m2.image_url)}" alt="">` : ''}</div>`);
  }
  ads.push(`<div class="ad" style="--ad-bg:linear-gradient(120deg,var(--mint-soft),#E4F8FF)"><div class="ad-copy"><span class="ad-kicker">📱 UNIORDER 앱</span>
      <h2>QR 한 번이면<br><em>늘 먹던 메뉴</em>까지</h2><p>앱으로 연결하면 고른 카드로 바로 결제되고<br>이 가게에서 드신 메뉴를 기억해 추천해 드려요</p>
      <div class="ad-price" style="font-size:30px">결제할 때마다 포인트 ${Math.round((st.point_rate || 0) * 100)}% 적립</div></div>
      <img class="ad-img" src="img/tile-dinein.png" alt="" style="width:400px;height:400px"></div>`);
  ads.push(`<div class="ad" style="--ad-bg:linear-gradient(120deg,#EFFFFA,var(--mint-soft))"><div class="ad-copy"><span class="ad-kicker">🎙 AI 직원</span>
      <h2>"덜 맵게 해줘"<br><em>말로 주문</em>하세요</h2><p>맵기 · 알레르기 · 추천, 무엇이든 편하게 물어보세요</p></div>
      <img class="ad-img" src="img/tile-ai.png" alt="" style="width:420px;height:420px"></div>`);
  $('#adStage').innerHTML = ads.join('');
  $('#adDots').innerHTML = ads.map(() => '<i></i>').join('');
  AD.list = [...$('#adStage').children];
  AD.list.forEach((el) => el.querySelectorAll('[data-count]').forEach((c) => UFX.countdown(c, Date.now() + +c.dataset.count * 1000)));
}
function showAd(i) {
  const n = AD.list.length; if (!n) return;
  const prev = AD.list[AD.i];
  AD.i = (i + n) % n;
  AD.list.forEach((el, k) => { el.classList.toggle('on', k === AD.i); el.classList.toggle('out', el === prev && k !== AD.i); });
  setTimeout(() => prev && prev.classList.remove('out'), 900);
  [...$('#adDots').children].forEach((d, k) => d.classList.toggle('on', k === AD.i));
}
function startAds() { stopAds(); showAd(AD.i); AD.t = setInterval(() => showAd(AD.i + 1), 4800); }
function stopAds() { clearInterval(AD.t); }

// 결제수단 로고가 끝없이 흐르는 띠 (React Bits Logo Loop 방식: 같은 묶음 2번 → -50% 이동)
const BRANDS = [
  ['K', '#FEE500', '#191600', '카카오페이'], ['N', '#03C75A', '#fff', '네이버페이'], ['S', '#1428A0', '#fff', '삼성페이'],
  ['₩', '#6A994E', '#fff', '지역사랑상품권'], ['온', '#B5462F', '#fff', '온누리상품권'], ['V', '#1A1F71', '#fff', 'VISA'],
  ['M', '#EB001B', '#fff', 'Mastercard'], ['P', 'var(--mint-deep)', '#fff', '유니 포인트'], ['U', '#0C3481', '#fff', 'UNIORDER Pay'],
];
function buildLogoLoop() {
  const set = `<div class="loop-set">${BRANDS.map(([l, bg, fg, name]) => `<span class="brand-pill"><i style="background:${bg};color:${fg}">${l}</i>${name}</span>`).join('')}</div>`;
  $('#logoLoop').innerHTML = `<div class="loop-track">${set}${set}</div>`;
}

// ===== ① 스플래시 → ② 환영 =====
function showSplash() {
  ['#welcome', '#start'].forEach((x) => $(x).classList.add('hidden'));
  $('#splash').classList.remove('hidden');
  startAds();
}
function showWelcome() {
  stopStartScanner(); stopAds();
  $('#splash').classList.add('hidden'); $('#start').classList.add('hidden');
  $('#welcome').classList.remove('hidden');
}
$('#splash').addEventListener('click', showWelcome);
$('#langBtn').addEventListener('click', () => { S.lang = S.lang === 'en' ? 'ko' : 'en'; applyLang(); });
$('#welcome .tiles').addEventListener('click', (e) => {
  const b = e.target.closest('[data-mode]'); if (!b) return;
  S.startAI = b.dataset.mode === 'ai';
  S.orderType = b.dataset.mode === 'takeout' ? 'takeout' : 'dine_in';
  $('#welcome').classList.add('hidden');
  showStart();  // ③ UNIORDER 앱 있나요?
});
$('#startBack').addEventListener('click', showWelcome);

// ===== 메뉴 =====
const PALETTE = ['#E2572B', '#D98B2B', '#8A6B3E', '#6F8F3A', '#3B7A8F', '#8F3B6B', '#5A4FA0'];
function colorFor(text) { let h = 0; for (const c of text) h = (h * 31 + c.charCodeAt(0)) >>> 0; return PALETTE[h % PALETTE.length]; }
const dots = (n, cls) => `<span class="dots ${cls}">${[0, 1, 2, 3, 4].map((i) => `<i class="${i < n ? 'on' : ''}"></i>`).join('')}</span>`;

const CAT_IMG = { 메뉴: 'img/cat-menu.png', 에피타이저: 'img/cat-appetizer.png', 음료: 'img/cat-drink.png', 디저트: 'img/cat-dessert.png' };
const AI_TAB = '__ai__';

function categories() { return [...new Set(S.menus.map((m) => m.category).filter(Boolean))]; }

function renderTabs() {
  const cats = categories();
  if (!S.tab || (S.tab !== AI_TAB && !cats.includes(S.tab))) S.tab = cats[0] || null;
  const items = (S.aiRecoIds.size ? [AI_TAB] : []).concat(cats);
  $('#cats').innerHTML = items.map((c) => {
    const on = c === S.tab && !S.q ? 'on' : '';
    if (c === AI_TAB) return `<button class="cat ${on}" data-tab="${AI_TAB}"><span class="spark">✦</span><span>${S.lang === 'en' ? 'For you' : 'AI 추천'}</span></button>`;
    const icon = CAT_IMG[c] ? `<img src="${CAT_IMG[c]}" alt="">` : `<span class="ph">${esc(c[0])}</span>`;
    return `<button class="cat ${on}" data-tab="${esc(c)}">${icon}<span>${esc(catLabel(c))}</span></button>`;
  }).join('');
}
$('#cats').addEventListener('click', (e) => {
  const b = e.target.closest('[data-tab]'); if (!b) return;
  S.tab = b.dataset.tab; S.q = ''; $('#search').value = '';
  renderTabs(); renderMenus();
});
$('#search').addEventListener('input', (e) => { S.q = e.target.value.trim(); renderTabs(); renderMenus(); });

function menuImg(m, cls = '') {
  return m.image_url ? `<img src="${esc(m.image_url)}" alt="" class="${cls}">` : `<span class="ph">${esc(m.name[0])}</span>`;
}

function renderMenus() {
  let list = S.menus, title;
  if (S.q) {
    const q = S.q.toLowerCase();
    list = S.menus.filter((m) => (m.name + ' ' + (m.name_en || '') + ' ' + m.description + ' ' + m.tags.join(' ')).toLowerCase().includes(q));
    title = `‘${esc(S.q)}’`;
  } else if (S.tab === AI_TAB) {
    list = S.menus.filter((m) => S.aiRecoIds.has(m.id)); title = S.lang === 'en' ? 'Picked for you' : 'AI 추천';
  } else {
    list = S.menus.filter((m) => m.category === S.tab); title = esc(catLabel(S.tab || t('menuTitle')));
  }
  $('#catTitle').innerHTML = title;
  const second = (m) => (S.lang === 'en' ? m.name : m.name_en);
  $('#menuGrid').innerHTML = list.map((m) => `
    <button class="card" data-menu="${m.id}">
      ${m.tags.includes('BEST') ? '<span class="badge best">BEST</span>' : S.aiRecoIds.has(m.id) ? '<span class="badge">AI 추천</span>' : ''}
      <div class="img">${menuImg(m)}</div>
      <div class="names"><p>${esc(menuName(m))}</p>${second(m) ? `<p>${esc(second(m))}</p>` : ''}</div>
      <span class="price">${won(m.price)}</span>
    </button>`).join('') || `<p class="empty-msg">${S.lang === 'en' ? 'No menu found.' : '찾는 메뉴가 없어요.'}</p>`;
}
$('#menuGrid').addEventListener('click', (e) => {
  const c = e.target.closest('[data-menu]'); if (!c) return;
  openMenu(S.menus.find((m) => m.id === +c.dataset.menu));
});

function openMenu(menu) {
  const groups = {};
  menu.options.forEach((o) => (groups[o.group] ||= []).push(o));
  const chosen = new Set();
  showModal(`
    <div class="menu-hero">${menuImg(menu)}
      <div><h2>${esc(menuName(menu))}</h2><div class="en">${esc(S.lang === 'en' ? menu.name : menu.name_en || '')}</div>
      <p>${esc(menu.description)}</p>
      <div class="meters"><span>맵기${dots(menu.spicy_level, 'spicy')}</span><span>단맛${dots(menu.sweetness, 'sweet')}</span></div></div>
    </div>
    ${Object.entries(groups).map(([g, opts]) => `
      <div class="opt-group"><h4>${esc(g)} <small>(선택)</small></h4>
        ${opts.map((o) => `<button class="opt" data-opt="${o.id}" data-group="${esc(g)}"><span>${esc(o.name)}</span><span>${o.extra_price ? '+' + won(o.extra_price) : ''}</span></button>`).join('')}
      </div>`).join('')}
    <div class="modal-actions"><button class="btn ghost" data-act="close">${S.lang === 'en' ? 'Cancel' : '취소'}</button><button class="btn primary" data-act="add">${S.lang === 'en' ? 'Add' : '담기'} · ${won(menu.price)}</button></div>`);
  const body = $('#modalBody');
  const addBtn = body.querySelector('[data-act="add"]');
  body.onclick = (e) => {
    const o = e.target.closest('[data-opt]');
    if (o) {
      const id = +o.dataset.opt;
      const had = chosen.has(id);
      body.querySelectorAll(`[data-group="${CSS.escape(o.dataset.group)}"]`).forEach((x) => { chosen.delete(+x.dataset.opt); x.classList.remove('on'); });
      if (!had) { chosen.add(id); o.classList.add('on'); }
      const extra = menu.options.filter((x) => chosen.has(x.id)).reduce((s, x) => s + x.extra_price, 0);
      addBtn.textContent = `${S.lang === 'en' ? 'Add' : '담기'} · ${won(menu.price + extra)}`;
    }
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'close') closeModal();
    if (act === 'add') { addToCart(menu, menu.options.filter((x) => chosen.has(x.id))); closeModal(); }
  };
}

// ===== 장바구니 =====
function addToCart(menu, options, silent) {
  const key = menu.id + ':' + options.map((o) => o.id).sort().join(',');
  const found = S.cart.find((c) => c.key === key);
  if (found) found.qty++;
  else S.cart.push({ key, menu, options, qty: 1 });
  renderCart();
  if (!silent) toast(`${menuName(menu)} ${S.lang === 'en' ? 'added' : '담았어요'}`);
}
const unitPrice = (c) => c.menu.price + c.options.reduce((s, o) => s + o.extra_price, 0);
const cartTotal = () => S.cart.reduce((s, c) => s + unitPrice(c) * c.qty, 0);

function renderCart() {
  $('#cartList').innerHTML = S.cart.map((c, i) => `
    <li class="cart-item">
      <span class="ci-img">${menuImg(c.menu)}</span>
      <span class="ci-name">${esc(menuName(c.menu))}</span>
      <span class="ci-sub">${won(unitPrice(c))}${c.options.length ? `<em>✎ ${c.options.map((o) => esc(o.name)).join(', ')}</em>` : ''}</span>
      <div class="step"><button data-q="${i}" data-d="-1" aria-label="빼기">−</button><b>${c.qty}</b><button data-q="${i}" data-d="1" aria-label="더하기">+</button></div>
    </li>`).join('');
  $('#cartEmpty').classList.toggle('hidden', S.cart.length > 0);
  $('#cartCount').textContent = S.cart.reduce((s, c) => s + c.qty, 0);
  const sum = cartTotal(), dc = S.store?.discount ? Math.floor(sum * S.store.discount.rate / 1000) * 10 : 0;
  $('#cartTotal').innerHTML = dc ? `<s class="was">${won(sum)}</s>${won(sum - dc)}` : won(sum);
  $('#btnOrder').disabled = !S.cart.length;
  const type = S.orderType === 'takeout' ? (S.lang === 'en' ? 'Take out' : '포장') : (S.lang === 'en' ? 'Dine in' : '매장 식사');
  $('#orderMeta').textContent = `${type}${S.store?.name ? ' · ' + S.store.name : ''}${dc ? ` · ${S.store.discount.rate}% 할인 -${won(dc)}` : ''}`;
}
$('#cartList').addEventListener('click', (e) => {
  const b = e.target.closest('[data-q]'); if (!b) return;
  const c = S.cart[+b.dataset.q];
  c.qty += +b.dataset.d;
  if (c.qty <= 0) S.cart.splice(+b.dataset.q, 1);
  renderCart();
});
$('#btnClear').addEventListener('click', () => { if (S.cart.length) { S.cart = []; renderCart(); toast(S.lang === 'en' ? 'Cleared' : '장바구니를 비웠어요'); } });

// ===== 모달 =====
function showModal(html) { $('#modalBody').innerHTML = html; $('#modal').classList.remove('hidden'); }
async function closeModal() { await stopScanner(); $('#modal').classList.add('hidden'); $('#modalBody').onclick = null; }
$('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal') closeModal(); });

// ===== QR 스캔 (카메라 + 직접 입력 + 데모) =====
function scanUI(title, sub) {
  return `
    <h2>${title}</h2><p class="sub">${sub}</p>
    <div id="reader">카메라 준비 중…</div>
    <div class="manual"><input id="manualQr" placeholder="QR 내용 직접 입력 (STGPAY:…)"><button class="btn ghost small" data-act="manual">확인</button></div>
    <div class="modal-actions">
      <button class="btn ghost" data-act="close">취소</button>
      ${S.health.demo_mode ? '<button class="btn primary" data-act="demo">데모 손님 QR로 진행</button>' : ''}
    </div>`;
}

async function startScanner(onScan) {
  if (!window.Html5Qrcode) { $('#reader').textContent = '카메라 모듈을 불러오지 못했어요. 직접 입력을 이용하세요.'; return; }
  try {
    S.scanner = new Html5Qrcode('reader');
    let done = false;
    await S.scanner.start({ facingMode: 'user' }, { fps: 10, qrbox: 220 }, (text) => {
      if (done) return; done = true; onScan(text);
    });
  } catch {
    $('#reader').textContent = '카메라를 사용할 수 없어요. 아래에 직접 입력하거나 데모 버튼을 눌러주세요.';
    S.scanner = null;
  }
}
async function stopScanner() {
  if (S.scanner) { try { await S.scanner.stop(); } catch {} S.scanner = null; }
}

function bindScan(onPayload) {
  $('#modalBody').onclick = async (e) => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'close') closeModal();
    if (act === 'manual') { const v = $('#manualQr').value.trim(); if (v) { await stopScanner(); onPayload(v); } }
    if (act === 'demo') {
      await stopScanner();
      try { const d = await api('/api/demo/qr', { method: 'POST' }); onPayload(d.qr_payload); } catch (err) { toast(err.message); }
    }
  };
  startScanner(async (text) => { await stopScanner(); onPayload(text); });
}

// ===== 첫 화면: "UNIORDER 앱 있나요?" =====
// 있다 → 앱 QR 찍기 (앱에서 고른 결제카드가 결제까지 이어짐 + 이 가게 대화 기억으로 추천)
// 없다 → 그냥 주문
let IDLE_T = 0;
const IDLE_MS = 120000;  // 2분 동안 아무 터치 없으면 첫 화면으로

// 손님이 앱의 결제 QR을 키오스크 카메라에 보여줌 → 누구인지 알고(이 가게 방문·대화·주문 기억) 고른 결제수단을 이어감
let START_SCANNER = null;

async function showStart() {
  $('#start').classList.remove('hidden');
  $('#startWelcome').classList.add('hidden');
  $('#startAsk').classList.remove('hidden');
  $('#demoRow').classList.toggle('hidden', !S.health.demo_mode);
  $('#startManual').value = '';
  scanMsg('');
  await startStartScanner();
}
function scanMsg(t) { const m = $('#scanMsg'); m.textContent = t; m.classList.toggle('hidden', !t); }

async function startStartScanner() {
  await stopStartScanner();
  const box = $('#startReader');
  if (!window.Html5Qrcode) { box.innerHTML = '<p>카메라 모듈을 불러오지 못했어요<br>‘없습니다’를 눌러 주문해 주세요</p>'; return; }
  box.innerHTML = '';
  try {
    START_SCANNER = new Html5Qrcode('startReader', { verbose: false });
    let done = false;
    // 태블릿 앞쪽 카메라 = 손님 쪽
    await START_SCANNER.start({ facingMode: 'user' }, { fps: 12, qrbox: { width: 300, height: 300 } },
      (text) => { if (done) return; done = true; onStartQr(text); });
  } catch {
    START_SCANNER = null;
    box.innerHTML = '<p>카메라를 켤 수 없어요<br><small>카메라 권한을 확인하거나 ‘없습니다’를 눌러 주문해 주세요</small></p>';
  }
}
async function stopStartScanner() {
  if (START_SCANNER) { const sc = START_SCANNER; START_SCANNER = null; try { await sc.stop(); } catch {} try { sc.clear(); } catch {} }
}

$('#startNo').addEventListener('click', async () => { await stopStartScanner(); beginVisit(null); });
$('#appDl').addEventListener('click', () => toast(S.lang === 'en' ? 'Search "UNIORDER" in the app store' : '앱스토어에서 "유니오더"를 검색해 주세요'));
$('#startDemo').addEventListener('click', async () => {
  try { const d = await api('/api/demo/qr', { method: 'POST' }); onStartQr(d.qr_payload); } catch (e) { toast(e.message); }
});
$('#startManualGo').addEventListener('click', () => { const v = $('#startManual').value.trim(); if (v) onStartQr(v); });

// (카메라 달린 기기용) 손님 결제 QR을 직접 받은 경우
async function onStartQr(payload) {
  if (!payload.startsWith('STGPAY:')) { scanMsg('유니오더 앱의 결제 QR을 보여주세요'); return startStartScanner(); }
  scanMsg('확인했어요!');
  await stopStartScanner();
  $('#startAsk').classList.add('hidden');
  $('#startWelcome').classList.remove('hidden');
  $('#startWelcome').innerHTML = '<div class="w-loading">반가워요! 잠시만요…</div>';
  try {
    const c = await api('/api/kiosk/session/start', { method: 'POST', body: { qr_payload: payload } });
    renderWelcome(c);
  } catch (e) {
    toast(e.message);
    showStart();
  }
}

function renderWelcome(c) {
  const m = c.selected_method;
  $('#startWelcome').innerHTML = `
    <div class="w-hello">${esc(c.name)}님</div>
    <p class="w-greet">${esc(c.greeting)}</p>
    <div class="w-chips">
      <span class="w-chip">💳 ${m ? `${esc(m.display_name)} ${esc(m.masked_number)}로 결제돼요` : '등록한 결제수단 순서대로 결제돼요'}</span>
      <span class="w-chip">유니 포인트 ${c.point_balance.toLocaleString()}P</span>
    </div>
    ${c.recommended_menus.length ? `<div class="w-reco-title">✦ 오늘 추천</div>
    <div class="w-recos">${[...c.usual_items.slice(0, 1).map((u) => S.menus.find((x) => x.id === u.menu_item_id)).filter(Boolean).map((x) => ({ ...x, usual: true })),
      ...c.recommended_menus].filter((x, i, arr) => arr.findIndex((y) => y.id === x.id) === i).slice(0, 4).map((x) => `
      <button class="w-reco" data-add="${x.id}">
        ${menuImg(x)}
        <b>${esc(menuName(x))}</b><small>${x.usual ? '늘 드시던 메뉴' : '맵기 ' + x.spicy_level}</small><span>${won(x.price)}</span>
        <i>+ 담기</i>
      </button>`).join('')}</div>` : ''}
    <button class="big-btn" id="startGo">${S.startAI ? (S.lang === 'en' ? 'Talk to AI staff' : 'AI 직원과 대화 시작') : (S.lang === 'en' ? 'Start ordering' : '주문 시작하기')}</button>`;
  speak(c.greeting);
  $('#startWelcome').onclick = (e) => {
    const b = e.target.closest('[data-add]');
    if (b) { const mm = S.menus.find((x) => x.id === +b.dataset.add); if (mm) { addToCart(mm, []); b.classList.add('added'); } }
    if (e.target.closest('#startGo')) beginVisit(c);
  };
}

function beginVisit(customer) {
  S.customer = customer;
  S.chatSession = 'k-' + Math.random().toString(36).slice(2);
  $('#chatLog').innerHTML = '';
  setupChat();
  if (customer) {
    addMsg('bot', esc(customer.greeting));
    customer.recommended_menus.forEach((m) => S.aiRecoIds.add(m.id));
    renderTabs(); renderMenus();
  }
  renderCustomer(); renderCart();
  $('#start').classList.add('hidden');
  bumpIdle();
  if (S.startAI) {  // 'AI로 주문하기'로 들어온 경우 바로 대화 시작
    S.startAI = false;
    openChat();
    if (S.health.stt_enabled) setTimeout(liveStart, 300); else setTimeout(() => $('#chatText').focus(), 300);
  }
}

function resetVisit() {
  liveStop();
  if (window.speechSynthesis) speechSynthesis.cancel();
  S.customer = null; S.cart = []; S.aiRecoIds = new Set(); S.tab = '전체';
  renderCart(); renderTabs(); renderMenus(); renderCustomer();
  $('#chatDrawer').classList.remove('open');
  closeModal();
  S.orderType = 'dine_in';
  showWelcome();
}
$('#btnHome').addEventListener('click', resetVisit);

function bumpIdle() {
  clearTimeout(IDLE_T);
  IDLE_T = setTimeout(() => {
    const busy = LIVE.on || !$('#modal').classList.contains('hidden') || !$('#start').classList.contains('hidden');
    if (busy) return bumpIdle();
    resetVisit(); showSplash();
  }, IDLE_MS);
}
['pointerdown', 'keydown'].forEach((ev) => document.addEventListener(ev, () => { if ($('#start').classList.contains('hidden')) bumpIdle(); }));

function renderCustomer() {
  const c = S.customer, el = $('#customerBanner');
  if (!c) return el.classList.add('hidden');
  el.classList.remove('hidden');
  const m = c.selected_method;
  el.innerHTML = `<span>👋 ${esc(c.name)}님 · 💳 ${m ? esc(m.display_name) : '우선순위 결제'} · 유니 ${c.point_balance.toLocaleString()}P</span>
    ${c.usual_items.length ? `<button class="chip-btn" id="btnUsual">늘 먹던 거 담기</button>` : ''}`;
  $('#btnUsual')?.addEventListener('click', () => {
    const mm = S.menus.find((x) => x.id === c.usual_items[0].menu_item_id);
    if (mm) addToCart(mm, []); else toast('지금은 주문할 수 없는 메뉴예요');
  });
}

// ===== 주문 + 결제 =====
$('#btnOrder').addEventListener('click', async () => {
  let order;
  try {
    order = await api('/api/kiosk/orders', {
      method: 'POST',
      body: { order_type: S.orderType, items: S.cart.map((c) => ({ menu_item_id: c.menu.id, quantity: c.qty, option_ids: c.options.map((o) => o.id) })) },
    });
  } catch (e) { return toast(e.message); }
  showPayChoice(order);
});

function showPayChoice(order) {
  const c = S.customer, m = c?.selected_method;
  const head = `<h2>결제하기</h2><p class="sub">주문번호 ${order.id} · <b style="color:var(--ink)">${won(order.total_amount)}</b></p>`;
  showModal(c ? `${head}
    <button class="pay-main" data-act="continue">
      <span class="pm-card">💳</span>
      <span class="pm-body"><b>결제 계속하기</b><small>선택한 방식으로 결제가 진행됩니다 · ${m ? `${esc(m.display_name)} ${esc(m.masked_number)}` : '등록한 결제수단 순서대로'}${c.point_balance ? ` · 유니 포인트 ${c.point_balance.toLocaleString()}P 먼저 사용` : ''}</small></span>
      <span class="pm-go">›</span>
    </button>
    <div class="pay-choices">
      <button class="pay-choice" data-act="change"><b>결제 방식 바꾸기</b><span>앱에 등록한 다른 카드·페이, 또는 실물 카드</span></button>
    </div>
    <div class="modal-actions"><button class="btn ghost" data-act="later">나중에 결제</button></div>` : `${head}
    <div class="pay-choices">
      <button class="pay-choice main" data-act="app"><b>UNIORDER 앱으로 결제</b><span>앱 QR 한 번이면 끝. 카드·페이·지역화폐·온누리·포인트</span></button>
      <button class="pay-choice" data-act="card"><b>카드결제</b><span>IC 카드 / 삼성페이 단말기</span></button>
    </div>
    <div class="modal-actions"><button class="btn ghost" data-act="later">나중에 결제</button></div>`);
  $('#modalBody').onclick = (e) => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'later') { closeModal(); toast('주문이 접수됐어요. 결제는 나중에 해주세요.'); clearCart(); }
    if (act === 'continue') paySession(order, null);
    if (act === 'change') showChangeCard(order);
    if (act === 'card') payCard(order);
    if (act === 'app') showAppPay(order);
  };
}

async function paySession(order, methodId) {
  showModal('<h2>결제 중…</h2><p class="sub">잠시만 기다려 주세요.</p>');
  try {
    const r = await api('/api/kiosk/payments/session', { method: 'POST',
      body: { order_id: order.id, customer_session: S.customer.customer_session, method_id: methodId } });
    showPayResult(order, r);
  } catch (e) { payError(order, e.message); }
}

async function showChangeCard(order) {
  let list;
  try { list = await api('/api/kiosk/session/methods', { method: 'POST', body: { customer_session: S.customer.customer_session } }); }
  catch (e) { return payError(order, e.message); }
  showModal(`<h2>결제 방식 바꾸기</h2><p class="sub">${won(order.total_amount)} · 사용할 결제수단을 골라주세요</p>
    <div class="card-list">${list.map((m) => `
      <button class="card-row ${m.selected ? 'sel' : ''}" data-m="${m.id}" ${m.supported ? '' : 'disabled'}>
        <span class="cr-type">${esc(m.label)}</span><b>${esc(m.display_name)}</b><small>${esc(m.masked_number)}${m.supported ? '' : ' · 이 가게에서 안 돼요'}</small>
        ${m.selected ? '<em>처음 선택</em>' : ''}
      </button>`).join('')}
      <button class="card-row" data-act="card"><span class="cr-type">실물 카드</span><b>카드결제</b><small>IC 카드 / 삼성페이 단말기</small></button></div>
    <div class="modal-actions"><button class="btn ghost" data-act="back">뒤로</button><button class="btn ghost" data-act="qr">다른 앱 QR 보여주기</button></div>`);
  $('#modalBody').onclick = (e) => {
    const r = e.target.closest('[data-m]');
    if (r && !r.disabled) return paySession(order, +r.dataset.m);
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'back') showPayChoice(order);
    if (act === 'card') payCard(order);
    if (act === 'qr') showAppPay(order);
  };
}

async function payCard(order) {
  showModal(`<div class="card-insert"><div class="ci-slot"></div><div class="ci-card"></div></div>
    <h2 style="text-align:center">카드를 꽂아주세요</h2><p class="sub" style="text-align:center">IC 카드 또는 삼성페이를 단말기에 대주세요 · ${won(order.total_amount)}</p>`);
  await new Promise((r) => setTimeout(r, 1600));  // [데모] 실제로는 단말기 응답 대기
  try {
    const r = await api('/api/kiosk/payments/card', { method: 'POST',
      body: { order_id: order.id, customer_session: S.customer?.customer_session || null } });
    showPayResult(order, r);
  } catch (e) { payError(order, e.message); }
}

function showAppPay(order) {
  showModal(scanUI('앱 QR을 카메라에 보여주세요', `앱에서 고른 결제수단으로 결제돼요 · ${won(order.total_amount)}`));
  bindScan(async (payload) => {
    showModal('<h2>결제 중…</h2><p class="sub">등록된 결제수단을 순서대로 확인하고 있어요.</p>');
    try {
      const r = await api('/api/kiosk/payments/qr', { method: 'POST', body: { order_id: order.id, qr_payload: payload } });
      showPayResult(order, r);
    } catch (e) { payError(order, e.message); }
  });
}

function payError(order, msg) {
  showModal(`<div class="result-icon fail">!</div><h2>결제할 수 없어요</h2><p class="sub">${esc(msg)}</p>
    <div class="modal-actions"><button class="btn ghost" data-act="close">닫기</button><button class="btn primary" data-act="retry">다른 방법으로</button></div>`);
  $('#modalBody').onclick = (ev) => {
    const act = ev.target.closest('[data-act]')?.dataset.act;
    if (act === 'close') closeModal();
    if (act === 'retry') showPayChoice(order);
  };
}

function showPayResult(order, r) {
  const attempts = r.attempts.map((a) => `
    <li class="${a.success ? 'ok' : 'fail'}">
      <div><b>${esc(a.label)}</b><small>${esc(a.message)}</small></div>
      <div style="text-align:right"><b>${won(a.amount)}</b><small>${a.success ? '승인' : '실패 → 다음 수단'}</small></div>
    </li>`).join('');
  showModal(r.success ? `
      <div class="result-icon ok">✓</div><h2>결제 완료</h2><p class="sub">${esc(r.message)}</p>
      <ul class="attempts">${attempts}</ul>
      <div class="points-line"><div>포인트 사용<strong>${r.points_used.toLocaleString()}P</strong></div><div>새로 적립<strong>+${r.points_earned.toLocaleString()}P</strong></div></div>
      <div class="modal-actions"><button class="btn primary" data-act="done">확인</button></div>` : `
      <div class="result-icon fail">!</div><h2>결제 실패</h2><p class="sub">${esc(r.message)}</p>
      <ul class="attempts">${attempts}</ul>
      <div class="modal-actions"><button class="btn ghost" data-act="close">닫기</button><button class="btn primary" data-act="retry">다른 방법으로</button></div>`);
  if (r.success) speak('결제가 완료됐어요. 맛있게 드세요!');
  $('#modalBody').onclick = (e) => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'done') { toast('주문이 주방으로 전달됐어요!'); resetVisit(); }
    if (act === 'close') closeModal();
    if (act === 'retry') showPayChoice(order);
  };
}
function clearCart() { S.cart = []; renderCart(); }

// ===== AI 대화 =====
const QUICK = [['✦', '추천해 주세요', '오늘 뭐 먹지?'], ['🌶', '안 매운 메뉴 있어요?', '맵기'], ['🍯', '좀 덜 단 음식은 없어요?', '단맛'],
  ['🔥', '맵기 조절 되나요?', '요청'], ['🥜', '땅콩 알레르기 있어요', '알레르기'], ['🧾', '결제할게요', '주문 끝']];

// ===== 프롬프트 바: / 빠른 질문 메뉴 · 음성 답변 토글 · 자동 높이 =====
const PB = { open: false, idx: 0, list: QUICK, tts: true };
function pbRender() {
  $('#pbRows').innerHTML = PB.list.map(([i, q, d], k) => `<button type="button" class="pb-row" data-k="${k}"><i>${i}</i>${esc(q)}<small>${esc(d)}</small></button>`).join('')
    || '<div class="pb-row" style="color:var(--muted)">맞는 빠른 질문이 없어요</div>';
  pbGlow();
}
function pbGlow() {
  const row = $('#pbRows').children[PB.idx], g = $('#pbGlow');
  if (!row || !row.dataset.k) { g.style.opacity = 0; return; }
  g.style.top = row.offsetTop + 'px'; g.style.height = row.offsetHeight + 'px'; g.style.opacity = 1;
}
function pbOpen(filter = '') {
  PB.list = QUICK.filter(([, q, d]) => !filter || q.includes(filter) || d.includes(filter));
  PB.idx = 0; PB.open = true; $('#pbMenu').classList.remove('hidden'); $('#pbSlash').classList.add('on'); pbRender();
}
function pbClose() { PB.open = false; $('#pbMenu').classList.add('hidden'); $('#pbSlash').classList.remove('on'); }
function pbAuto() {
  const t = $('#chatText'); t.style.height = 'auto'; t.style.height = Math.min(104, t.scrollHeight) + 'px';
  $('#pbSend').disabled = !t.value.trim() || t.value.trim().startsWith('/');
}
$('#pbSlash').addEventListener('click', () => (PB.open ? pbClose() : pbOpen()));
$('#pbRows').addEventListener('pointermove', (e) => { const r = e.target.closest('[data-k]'); if (r && +r.dataset.k !== PB.idx) { PB.idx = +r.dataset.k; pbGlow(); } });
$('#pbRows').addEventListener('click', (e) => {
  const r = e.target.closest('[data-k]'); if (!r) return;
  pbClose(); $('#chatText').value = ''; pbAuto(); sendChat(PB.list[+r.dataset.k][1]);
});
$('#chatText').addEventListener('input', () => {
  const v = $('#chatText').value;
  if (v.startsWith('/')) pbOpen(v.slice(1).trim()); else if (PB.open) pbClose();
  pbAuto();
});
$('#chatText').addEventListener('keydown', (e) => {
  if (PB.open && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { e.preventDefault(); PB.idx = (PB.idx + (e.key === 'ArrowDown' ? 1 : -1) + PB.list.length) % PB.list.length; pbGlow(); return; }
  if (e.key === 'Escape') return pbClose();
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (PB.open && PB.list[PB.idx]) { const q = PB.list[PB.idx][1]; pbClose(); $('#chatText').value = ''; pbAuto(); return sendChat(q); }
    $('#chatForm').requestSubmit();
  }
});
$('#pbTts').addEventListener('click', () => {
  PB.tts = !PB.tts; $('#pbTts').classList.toggle('on', PB.tts);
  $('#pbTtsLabel').textContent = PB.tts ? '음성 답변' : '글자만';
  if (!PB.tts && window.speechSynthesis) speechSynthesis.cancel();
});
$('#pbTts').classList.add('on');

function setupChat() {
  pbClose();
  addMsg('bot', `안녕하세요! ${S.store.name}입니다 😊 메뉴가 고민되시면 편하게 물어보세요.`);
}
// 대화창 닫으면 녹음도 취소
document.querySelector('[data-close="chatDrawer"]').addEventListener('click', () => liveStop());
document.addEventListener('click', (e) => {
  const c = e.target.closest('[data-close]'); if (c) $('#' + c.dataset.close).classList.remove('open');
});
$('#chatForm').addEventListener('submit', (e) => { e.preventDefault(); const v = $('#chatText').value.trim(); if (v && !v.startsWith('/')) { $('#chatText').value = ''; pbAuto(); sendChat(v); } });

function addMsg(who, html) {
  const d = document.createElement('div');
  d.className = 'msg ' + who; d.innerHTML = html;
  $('#chatLog').appendChild(d); $('#chatLog').scrollTop = 1e9;
  return d;
}

function renderReply(r) {
  const reco = r.recommended_menus.map((m) => `
    <div class="reco-item">${m.image_url ? `<img src="${esc(m.image_url)}" alt="">` : ''}<span><b>${esc(menuName(m))}</b> · ${won(m.price)}</span>
    <button data-add="${m.id}">담기</button></div>`).join('');
  addMsg('bot', esc(r.reply) + (reco ? `<div class="reco-list">${reco}</div>` : '') +
    (r.unmet_requests.length ? `<div class="unmet">📝 사장님께 전달했어요: ${r.unmet_requests.map(esc).join(', ')}</div>` : ''));
  if (r.recommended_menus.length) {
    r.recommended_menus.forEach((m) => S.aiRecoIds.add(m.id));
    renderTabs(); renderMenus();
  }
}

async function sendChat(text) {
  addMsg('user', esc(text));
  const typing = addMsg('bot typing', '생각하는 중…');
  try {
    const r = await api('/api/kiosk/ai/chat', {
      method: 'POST',
      body: { session_id: S.chatSession, message: text, customer_session: S.customer?.customer_session || null },
    });
    typing.remove(); renderReply(r);
    if (runActions(r.actions || [])) { liveStop(); goCheckout(); }
  } catch (e) {
    typing.remove(); addMsg('bot', '앗, 지금은 답을 못 드렸어요. (' + esc(e.message) + ')');
  }
}

// ===== 음성 대화 (Whisper) — 버튼 한 번 누르면 멈출 때까지 계속 대화 =====
// 듣기 → (말 끝나면 자동) 인식 → AI 답변을 소리로 → 다시 듣기 … 종료 버튼까지 반복
// 잡음 처리: 브라우저 잡음제거 + 목소리 대역 필터 + 주변 소음 자동 측정 + 짧은 소리/먼 목소리 무시 + 서버에서 한 번 더 거름
const LIVE = {
  on: false, state: 'idle', stream: null, ctx: null, rec: null, chunks: [], raf: 0,
  floor: 0.01, calibUntil: 0, voicedMs: 0, aboveMs: 0, belowMs: 0, speaking: false, segStart: 0, recStart: 0,
  lastSpeechAt: 0, bargeMs: 0, lastTick: 0, busy: false,
};
const VAD = {
  START_X: 3.0,        // 주변 소음보다 3배 이상 커야 '손님 목소리'로 판단 (멀리 있는 다른 사람 목소리는 작음)
  MIN_START: 0.02,     // 아주 조용한 곳에서도 이 이상은 돼야 함
  START_MS: 200,       // 이만큼 이어져야 말 시작 (그릇 부딪히는 소리 같은 짧은 소리 무시)
  END_MS: 850,         // 이만큼 조용하면 말 끝
  MIN_VOICED_MS: 350,  // 실제 목소리가 이보다 짧으면 버림
  MAX_UTTER_MS: 12000, // 한 번에 최대 12초
  BAND_RATIO: 0.45,    // 전체 소리 중 목소리 대역(150~3800Hz) 비율
  BARGE_X: 2.2,        // AI가 말하는 중 끼어들기: 평소보다 훨씬 크게 말해야 (스피커 소리 오인 방지)
  BARGE_MS: 350,
  IDLE_END_MS: 45000,  // 45초 동안 아무 말 없으면 대화 종료
};

function openChat() { $('#chatDrawer').classList.add('open'); }
// 'AI로 주문하기': 대화창 열고 음성 대화 시작 (음성 미설정이면 글자 입력)
$('#btnVoice').addEventListener('click', () => {
  if (LIVE.on) return liveStop();
  openChat();
  if (S.health.stt_enabled) setTimeout(liveStart, 200); else setTimeout(() => $('#chatText').focus(), 250);
});
$('#micBtn').addEventListener('click', () => (LIVE.on ? liveStop() : liveStart()));
$('#voiceDone').addEventListener('click', () => liveStop());
$('#voicePill').addEventListener('click', (e) => { if (e.target.closest('#voiceDone')) return; if (LIVE.state === 'speaking') interruptSpeech(); });

function sttReady() {
  if (!S.health.stt_enabled) { toast('음성 인식이 아직 설정되지 않았어요. 글자로 입력해 주세요. (GROQ_API_KEY)'); $('#chatText').focus(); return false; }
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) { toast('이 기기에서는 마이크를 쓸 수 없어요. 글자로 입력해 주세요.'); return false; }
  return true;
}

async function liveStart() {
  if (LIVE.on || !sttReady()) return;
  try {
    LIVE.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
  } catch { toast('마이크 권한이 필요해요. 글자로 입력해도 돼요.'); $('#chatText').focus(); return; }
  if (window.speechSynthesis) speechSynthesis.cancel();
  LIVE.on = true;
  LIVE.ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = LIVE.ctx.createMediaStreamSource(LIVE.stream);
  // 전체 소리
  LIVE.raw = LIVE.ctx.createAnalyser(); LIVE.raw.fftSize = 1024;
  src.connect(LIVE.raw);
  // 목소리 대역만 (저음 웅웅거림·고음 달그락 제거)
  const hp = LIVE.ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 150;
  const lp = LIVE.ctx.createBiquadFilter(); lp.type = 'lowpass'; lp.frequency.value = 3800;
  LIVE.band = LIVE.ctx.createAnalyser(); LIVE.band.fftSize = 1024;
  src.connect(hp); hp.connect(lp); lp.connect(LIVE.band);
  LIVE.bufRaw = new Float32Array(LIVE.raw.fftSize); LIVE.bufBand = new Float32Array(LIVE.band.fftSize);
  LIVE.floor = 0.01; LIVE.calibUntil = performance.now() + 700; LIVE.lastSpeechAt = performance.now();
  LIVE.lastTick = performance.now();
  $('#btnVoice').classList.add('live');
  $('#micBtn').classList.add('live');
  $('#voicePill').classList.remove('hidden');
  VP.hist = []; VP.tick = 0; VP.acc = 0; VP.env = 0; VP.start = performance.now();
  setLiveState('listening');
  startSegment();
  tick();
}

function liveStop(msg) {
  if (!LIVE.on) return;
  LIVE.on = false;
  cancelAnimationFrame(LIVE.raf);
  if (window.speechSynthesis) speechSynthesis.cancel();
  if (LIVE.rec && LIVE.rec.state !== 'inactive') { LIVE.rec.onstop = null; LIVE.rec.stop(); }
  LIVE.rec = null;
  LIVE.stream?.getTracks().forEach((t) => t.stop());
  LIVE.ctx?.close().catch(() => {});
  $('#voicePill').classList.add('hidden');
  $('#btnVoice').classList.remove('live');
  $('#micBtn').classList.remove('live');
  setLiveState('idle');
  if (msg) addMsg('bot', esc(msg));
}

function rms(an, buf) {
  an.getFloatTimeDomainData(buf);
  let s = 0; for (let i = 0; i < buf.length; i++) s += buf[i] * buf[i];
  return Math.sqrt(s / buf.length);
}

// 녹음 구간 시작 (말 시작 전 약간의 앞부분도 같이 담기도록 미리 녹음)
function startSegment() {
  const mime = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg'].find((t) => MediaRecorder.isTypeSupported?.(t)) || '';
  LIVE.rec = new MediaRecorder(LIVE.stream, mime ? { mimeType: mime } : undefined);
  LIVE.chunks = [];
  LIVE.rec.ondataavailable = (e) => e.data.size && LIVE.chunks.push(e.data);
  LIVE.rec.start(250);
  LIVE.recStart = performance.now();
  LIVE.speaking = false; LIVE.voicedMs = 0; LIVE.aboveMs = 0; LIVE.belowMs = 0;
}

function tick() {
  if (!LIVE.on) return;
  const now = performance.now(), dt = Math.min(100, now - LIVE.lastTick); LIVE.lastTick = now;
  const raw = rms(LIVE.raw, LIVE.bufRaw), band = rms(LIVE.band, LIVE.bufBand);
  const ratio = raw > 1e-6 ? band / raw : 0;
  const startTh = Math.max(LIVE.floor * VAD.START_X, LIVE.floor + 0.012, VAD.MIN_START);
  const keepTh = startTh * 0.6;
  const isVoice = band > startTh && ratio > VAD.BAND_RATIO;

  // 보이스 필 파형: 듣는 중엔 실제 마이크 크기, 말하는 중엔 말소리 흉내, 생각 중엔 잔잔하게
  const lvl = Math.min(1, band / (startTh * 2));
  const target = LIVE.state === 'listening' ? lvl : LIVE.state === 'speaking' ? simLevel(now / 1000) : 0.12 + 0.08 * Math.sin(now / 160);
  drawVoiceWave(target, dt);

  if (now < LIVE.calibUntil) {
    LIVE.floor = Math.max(0.004, Math.max(LIVE.floor * 0.8, band));  // 처음 0.7초: 주변 소음 측정
  } else if (LIVE.state === 'listening') {
    if (!LIVE.speaking) {
      // 말하기 전: 주변 소음 수준을 계속 따라감 (식당이 시끄러워지면 기준도 올라감)
      if (!isVoice) LIVE.floor = Math.max(0.004, LIVE.floor * 0.97 + band * 0.03);
      // 음절 사이 짧은 끊김은 봐주고, 짧게 '탁' 하는 소리는 누적이 안 되게
      LIVE.aboveMs = isVoice ? LIVE.aboveMs + dt : Math.max(0, LIVE.aboveMs - dt * 1.5);
      if (LIVE.aboveMs >= VAD.START_MS) {
        LIVE.speaking = true; LIVE.segStart = now; LIVE.voicedMs = LIVE.aboveMs; LIVE.belowMs = 0;
        setLiveState('listening', true);
      } else if (now - LIVE.recStart > 5000) {
        // 말이 없으면 녹음을 짧게 유지 (앞부분 잡음이 길게 쌓이지 않도록)
        LIVE.rec.onstop = null; LIVE.rec.stop(); startSegment();
      }
      if (now - LIVE.lastSpeechAt > VAD.IDLE_END_MS) return liveStop('한동안 말씀이 없어서 음성 대화를 마칠게요. 필요하면 다시 눌러주세요.');
    } else {
      if (band > keepTh && ratio > VAD.BAND_RATIO * 0.8) { LIVE.voicedMs += dt; LIVE.belowMs = 0; } else LIVE.belowMs += dt;
      if (LIVE.belowMs >= VAD.END_MS || now - LIVE.segStart > VAD.MAX_UTTER_MS) endUtterance();
    }
  } else if (LIVE.state === 'speaking') {
    // 끼어들기: 크게, 충분히 길게 말할 때만
    LIVE.bargeMs = band > startTh * VAD.BARGE_X && ratio > VAD.BAND_RATIO ? LIVE.bargeMs + dt : 0;
    if (LIVE.bargeMs >= VAD.BARGE_MS) interruptSpeech();
  }
  LIVE.raf = requestAnimationFrame(tick);
}

function endUtterance() {
  const voiced = LIVE.voicedMs;
  LIVE.speaking = false;
  const rec = LIVE.rec;
  if (voiced < VAD.MIN_VOICED_MS) { rec.onstop = null; rec.stop(); startSegment(); setLiveState('listening'); return; }
  LIVE.lastSpeechAt = performance.now();
  setLiveState('thinking');
  rec.onstop = () => sendUtterance(rec.mimeType || 'audio/webm', LIVE.chunks.slice());
  rec.stop();
}

async function sendUtterance(type, chunks) {
  if (!LIVE.on) return;
  const ext = type.includes('mp4') ? 'm4a' : type.includes('ogg') ? 'ogg' : 'webm';
  const fd = new FormData();
  fd.append('audio', new Blob(chunks, { type }), 'voice.' + ext);
  fd.append('session_id', S.chatSession);
  if (S.customer?.customer_session) fd.append('customer_session', S.customer.customer_session);
  let r;
  try {
    const res = await fetch(API + '/api/kiosk/ai/voice', { method: 'POST', headers: { 'X-Kiosk-Key': KIOSK_KEY }, body: fd });
    r = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : '음성 인식에 실패했어요');
  } catch (e) {
    if (!LIVE.on) return;
    flashLabel(e.message);
    return resumeListening();
  }
  if (!LIVE.on) return;
  if (r.ignored) { flashLabel('주변 소리는 넘길게요'); return resumeListening(); }
  addMsg('user', `<span class="heard">🎤</span>${esc(r.transcript)}`);
  renderReply(r);
  const checkout = runActions(r.actions || []);
  if (checkout) { speak(r.reply); liveStop(); return goCheckout(); }
  setLiveState('speaking');
  speak(r.reply, resumeListening);
}

function resumeListening() {
  if (!LIVE.on) return;
  startSegment();
  setLiveState('listening');
}

function interruptSpeech() {
  if (window.speechSynthesis) speechSynthesis.cancel();  // onend → resumeListening
  LIVE.bargeMs = 0;
  if (LIVE.state === 'speaking') resumeListening();
}

function setLiveState(st, talking) {
  LIVE.state = st;
  const pill = $('#voicePill');
  pill.dataset.state = st;
  $('#micBtn').dataset.state = LIVE.on ? st : 'idle';
  pill.classList.toggle('busy', st === 'thinking');
  $('#voiceLabel').textContent = {
    listening: talking ? '말씀 듣는 중…' : '듣고 있어요 · 편하게 말씀하세요',
    thinking: '생각 중…', speaking: '말하는 중 · 탭하면 끊고 말할 수 있어요', idle: '',
  }[st];
}
function flashLabel(text) {
  $('#voiceLabel').textContent = text;
  clearTimeout(flashLabel.t);
  flashLabel.t = setTimeout(() => LIVE.on && setLiveState(LIVE.state), 1500);
}

// ===== 보이스 필 파형 (React Bits Voice Pill 그리기 방식: 막대가 오른쪽에서 생겨 왼쪽으로 흐름) =====
const VP = { hist: [], tick: 0, acc: 0, env: 0, start: 0 };
const SYL = [[0.1, .16, .9], [0.3, .12, .7], [0.5, .2, 1], [0.95, .14, .8], [1.15, .1, .6], [1.3, .22, .95], [1.9, .16, .85], [2.12, .12, .7], [2.3, .18, .9], [3.05, .24, 1], [3.4, .12, .75], [3.6, .16, .9]];
function simLevel(t) {
  const u = t % 4.8; let a = 0.06;
  for (const [st, d, p] of SYL) { const x = (u - st) / d; if (x >= 0 && x <= 1) a = Math.max(a, p * 0.5 * (1 - Math.cos(2 * Math.PI * x))); }
  return a * (0.7 + 0.3 * Math.abs(Math.sin(2 * Math.PI * 7.1 * u)));
}
function drawVoiceWave(target, dtMs) {
  const tau = (target > VP.env ? 40 : 240) / 1000;
  VP.env += (target - VP.env) * (1 - Math.exp(-(dtMs / 1000) / tau));
  const cv = $('#vpWave'); if (!cv) return;
  const tEl = $('#vpTime'); const sec = Math.floor((performance.now() - VP.start) / 1000);
  const txt = `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, '0')}`; if (tEl.textContent !== txt) tEl.textContent = txt;
  const dpr = 2, W = 120 * dpr, H = 32 * dpr;
  if (cv.width !== W) { cv.width = W; cv.height = H; }
  const ctx = cv.getContext('2d');
  VP.acc = Math.max(VP.acc, VP.env); VP.tick = (VP.tick + 1) % 4;
  if (VP.tick === 0) { VP.hist.push(VP.acc); VP.acc = 0; if (VP.hist.length > 60) VP.hist.shift(); }
  const bw = 2 * dpr, step = 4 * dpr, shift = (VP.tick / 4) * step;
  ctx.clearRect(0, 0, W, H); ctx.fillStyle = '#fff';
  for (let i = 0; i < VP.hist.length; i++) {
    const v = VP.hist[VP.hist.length - 1 - i], x = W - (i + 1) * step - shift;
    if (x + bw < 0) break;
    const h = Math.max(bw, (0.12 + 0.88 * v) * H), t = Math.min(1, Math.max(0, (x + bw / 2) / (W * 0.55)));
    ctx.globalAlpha = (0.35 + 0.65 * v) * t * t * (3 - 2 * t);
    ctx.beginPath(); ctx.roundRect ? ctx.roundRect(x, (H - h) / 2, bw, h, bw / 2) : ctx.rect(x, (H - h) / 2, bw, h); ctx.fill();
  }
  ctx.globalAlpha = 1;
}

// AI가 돌려준 행동 실행: 장바구니 담기 / 결제
function runActions(actions) {
  let checkout = false;
  for (const a of actions) {
    if (a.type === 'add_to_cart') {
      const m = S.menus.find((x) => x.id === a.menu_item_id);
      if (m) for (let i = 0; i < (a.quantity || 1); i++) addToCart(m, []);
    }
    if (a.type === 'checkout') checkout = true;
  }
  return checkout;
}
function goCheckout() {
  $('#chatDrawer').classList.remove('open');
  if (S.cart.length) $('#btnOrder').click(); else toast('장바구니가 비어 있어요');
}

// 답을 소리로 (브라우저 기본 TTS)
function speak(text, onDone) {
  if (!window.speechSynthesis || !text || !PB.tts) { onDone && onDone(); return; }
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text.replace(/\([^)]*\)/g, ''));
  u.lang = 'ko-KR'; u.rate = 1.05;
  const ko = speechSynthesis.getVoices().find((v) => v.lang?.startsWith('ko'));
  if (ko) u.voice = ko;
  let done = false;
  const fin = () => { if (!done) { done = true; onDone && onDone(); } };
  u.onend = fin; u.onerror = fin;
  setTimeout(fin, 1500 + text.length * 180);  // TTS가 끝 신호를 안 줄 때 대비
  speechSynthesis.speak(u);
}

$('#chatLog').addEventListener('click', (e) => {
  const b = e.target.closest('[data-add]'); if (!b) return;
  const m = S.menus.find((x) => x.id === +b.dataset.add);
  if (m) openMenu(m);
});

// ===== 기기 설정 =====
$('#btnSettings').addEventListener('click', () => {
  showModal(`<h2>기기 설정</h2><p class="sub">사장님 화면 &gt; 가게 설정에서 키오스크를 등록하면 기기 키가 나와요.</p>
    <label class="field">기기 키 (X-Kiosk-Key)<input id="keyInput" value="${esc(KIOSK_KEY)}"></label>
    <div class="modal-actions"><button class="btn ghost" data-act="close">취소</button><button class="btn primary" data-act="save">저장</button></div>`);
  $('#modalBody').onclick = (e) => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (act === 'close') closeModal();
    if (act === 'save') { KIOSK_KEY = $('#keyInput').value.trim(); store_('kioskKey', KIOSK_KEY); location.reload(); }
  };
});

fitStage();
init();
