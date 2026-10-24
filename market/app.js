// ===== 공통 =====
const API = location.protocol === 'file:' ? 'http://localhost:8000' : '';
const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); if (v === null) localStorage.removeItem(k); else localStorage.setItem(k, v); } catch { return null; } };
const $ = (s) => document.querySelector(s);
const won = (n) => (n ?? 0).toLocaleString('ko-KR') + '원';
const short = (n) => n >= 10000 ? (n / 10000).toFixed(n % 10000 ? 1 : 0) + '만' : n.toLocaleString();
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ymd = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

let TOKEN = ls('ownerToken');
const S = { me: null, stores: [], storeId: null, view: 'dashboard', range: 7, payTypes: [], timer: null };

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
function toast(m) { const t = $('#toast'); t.textContent = m; t.classList.add('show'); clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('show'), 2400); }
function modal(html) { $('#modalBody').innerHTML = html; $('#modal').classList.remove('hidden'); }
function closeModal() { $('#modal').classList.add('hidden'); }
$('#modal').addEventListener('click', (e) => { if (e.target.id === 'modal' || e.target.closest('[data-close]')) closeModal(); });

// ===== 로그인 =====
$('#loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const r = await api('/api/auth/login', { method: 'POST', body: { email: $('#email').value, password: $('#pw').value } });
    if (r.user.role !== 'owner') return toast('사장님 계정으로 로그인해 주세요');
    TOKEN = r.access_token; ls('ownerToken', TOKEN); start();
  } catch (err) { toast(err.message); }
});
function logout() { TOKEN = null; ls('ownerToken', null); clearInterval(S.timer); $('#appView').classList.add('hidden'); $('#loginView').classList.remove('hidden'); }
$('#logout').addEventListener('click', logout);

async function start() {
  try {
    S.me = await api('/api/auth/me');
    S.payTypes = await api('/api/pay-types');
    S.stores = await api('/api/owner/stores');
  } catch { return logout(); }
  $('#loginView').classList.add('hidden'); $('#appView').classList.remove('hidden');
  $('#ownerName').textContent = S.me.name + ' 사장님';
  S.storeId = +(ls('ownerStore') || 0) || S.stores[0]?.id || null;
  if (!S.stores.find((s) => s.id === S.storeId)) S.storeId = S.stores[0]?.id || null;
  renderStoreSelect();
  go(S.storeId ? 'dashboard' : 'settings');
  clearInterval(S.timer);
  S.timer = setInterval(refreshPending, 5000); refreshPending();
}
function renderStoreSelect() {
  $('#storeSelect').innerHTML = S.stores.map((s) => `<option value="${s.id}" ${s.id === S.storeId ? 'selected' : ''}>${esc(s.name)}</option>`).join('') || '<option>가게 없음</option>';
}
$('#storeSelect').addEventListener('change', (e) => { S.storeId = +e.target.value; ls('ownerStore', S.storeId); go(S.view); refreshPending(); });

// ===== 화면 전환 =====
const VIEWS = {
  dashboard: ['매출', renderDashboard], insights: ['AI 손님 의견', renderInsights], menus: ['메뉴 관리', renderMenus],
  orders: ['주문', renderOrders], settings: ['가게 설정', renderSettings],
};
$('#nav').addEventListener('click', (e) => { const b = e.target.closest('[data-view]'); if (b) go(b.dataset.view); });
function go(view) {
  S.view = view;
  document.querySelectorAll('#nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $('#viewTitle').textContent = VIEWS[view][0];
  $('#headActions').innerHTML = '';
  $('#screen').innerHTML = '<p class="muted">불러오는 중…</p>';
  $('#screen').onclick = null;
  if (!S.storeId && view !== 'settings') { $('#screen').innerHTML = '<p class="muted">가게 설정에서 가게를 먼저 만들어 주세요.</p>'; return; }
  VIEWS[view][1]().catch((e) => ($('#screen').innerHTML = `<p class="muted">${esc(e.message)}</p>`));
}

async function refreshPending() {
  if (!S.storeId || !TOKEN) return;
  try {
    const list = await api(`/api/owner/stores/${S.storeId}/orders?status=paid`);
    const el = $('#pendingCount');
    el.textContent = list.length; el.classList.toggle('hidden', !list.length);
    if (S.view === 'orders' && !document.querySelector('#modal:not(.hidden)')) renderOrders(true);
  } catch {}
}

// ===== 매출 =====
async function renderDashboard() {
  $('#headActions').innerHTML = `<div class="seg" id="range">${[[1, '오늘'], [7, '7일'], [30, '30일']].map(([d, l]) => `<button data-d="${d}" class="${S.range === d ? 'on' : ''}">${l}</button>`).join('')}</div>`;
  $('#range').onclick = (e) => { const b = e.target.closest('[data-d]'); if (b) { S.range = +b.dataset.d; renderDashboard(); } };
  const end = new Date(), start = new Date(Date.now() - (S.range - 1) * 864e5);
  const d = await api(`/api/owner/stores/${S.storeId}/sales?start=${ymd(start)}&end=${ymd(end)}`);

  // 빈 날짜도 0으로 채우기
  const days = [];
  for (let t = new Date(start); t <= end; t = new Date(t.getTime() + 864e5)) {
    const k = ymd(t); days.push({ date: k, revenue: d.daily.find((x) => x.date === k)?.revenue || 0 });
  }
  const maxDay = Math.max(1, ...days.map((x) => x.revenue));
  const maxMenu = Math.max(1, ...d.by_menu.map((x) => x.revenue));
  const maxPay = Math.max(1, ...d.by_payment_type.map((x) => x.amount));
  const hours = Array.from({ length: 15 }, (_, i) => i + 9).map((h) => ({ h, v: d.hourly.find((x) => x.hour === h)?.revenue || 0 }));
  const maxH = Math.max(1, ...hours.map((x) => x.v));

  $('#screen').innerHTML = `
    <div class="grid kpis">
      <div class="panel kpi"><div class="label">총 매출</div><div class="value">${won(d.total_revenue)}</div><div class="hint">${d.start} ~ ${d.end}</div></div>
      <div class="panel kpi"><div class="label">주문 수</div><div class="value">${d.order_count}건</div></div>
      <div class="panel kpi"><div class="label">평균 주문 금액</div><div class="value">${won(d.average_order_value)}</div></div>
      <div class="panel kpi"><div class="label">재방문 손님</div><div class="value">${d.returning_customers}명</div><div class="hint">앱 회원 ${d.member_customers}명 중</div></div>
    </div>
    <div class="grid two" style="margin-top:16px">
      <div class="panel"><h3>일별 매출 <small>막대에 마우스를 올려보세요</small></h3>
        <div class="vbars">${days.map((x) => `<div class="vbar"><i style="height:${(x.revenue / maxDay) * 100}%" data-v="${won(x.revenue)}"></i><span>${S.range > 14 ? x.date.slice(8) : x.date.slice(5).replace('-', '/')}</span></div>`).join('')}</div>
      </div>
      <div class="panel"><h3>메뉴별 매출</h3><div class="hbars">
        ${d.by_menu.slice(0, 8).map((m) => `<div class="hbar"><span class="name">${esc(m.name)}</span><div class="track"><i style="width:${(m.revenue / maxMenu) * 100}%"></i></div><b>${short(m.revenue)} · ${m.quantity}개</b></div>`).join('') || '<p class="muted">판매 기록이 없어요.</p>'}
      </div></div>
    </div>
    <div class="grid two" style="margin-top:16px">
      <div class="panel"><h3>시간대별 매출</h3>
        <div class="vbars" style="height:150px">${hours.map((x) => `<div class="vbar"><i style="height:${(x.v / maxH) * 100}%" data-v="${x.h}시 ${won(x.v)}"></i><span>${x.h}</span></div>`).join('')}</div>
      </div>
      <div class="panel"><h3>결제수단별</h3><div class="hbars">
        ${d.by_payment_type.map((p) => `<div class="hbar"><span class="name">${esc(p.label)}</span><div class="track"><i style="width:${(p.amount / maxPay) * 100}%"></i></div><b>${short(p.amount)}</b></div>`).join('') || '<p class="muted">결제 기록이 없어요.</p>'}
      </div></div>
    </div>`;
}

// ===== AI 손님 의견 =====
async function renderInsights() {
  $('#headActions').innerHTML = `<div class="seg" id="range">${[[7, '7일'], [30, '30일'], [90, '90일']].map(([d, l]) => `<button data-d="${d}" class="${(S.insRange || 30) === d ? 'on' : ''}">${l}</button>`).join('')}</div>`;
  $('#range').onclick = (e) => { const b = e.target.closest('[data-d]'); if (b) { S.insRange = +b.dataset.d; renderInsights(); } };
  const d = await api(`/api/owner/stores/${S.storeId}/insights?days=${S.insRange || 30}`);
  const topics = Object.entries(d.question_topics);
  const maxT = Math.max(1, ...topics.map(([, v]) => v));
  $('#screen').innerHTML = `
    <div class="panel ai-summary"><h3>✦ AI 요약 <small style="color:rgba(255,255,255,.7)">키오스크 질문 ${d.total_questions}건 분석</small></h3><p>${esc(d.summary)}</p></div>
    <div class="grid two" style="margin-top:16px">
      <div class="panel"><h3>손님이 찾았지만 없는 것 <small>옵션을 추가하면 바로 키오스크에 반영돼요</small></h3>
        ${d.unmet_requests.map((u) => `
          <div class="unmet"><div class="count">${u.count}<small>명</small></div>
            <div class="body"><b>${esc(u.request)}</b>${u.examples.map((x) => `<span class="quote">“${esc(x)}”</span>`).join('')}</div>
            <button class="btn primary small" data-addopt="${esc(u.request)}">옵션 추가</button></div>`).join('') || '<p class="muted">아직 없어요. 손님들이 원하는 건 다 있네요!</p>'}
      </div>
      <div>
        <div class="panel"><h3>AI 개선 제안</h3>
          ${d.suggestions.map((s) => `<div class="sugg"><b>${esc(s.title)}<span class="prio ${esc(s.priority)}">${{ high: '중요', medium: '보통', low: '참고' }[s.priority] || esc(s.priority)}</span></b><span class="muted">${esc(s.detail)}</span></div>`).join('') || '<p class="muted">제안이 없어요.</p>'}
        </div>
        <div class="panel" style="margin-top:16px"><h3>손님들이 많이 묻는 주제</h3><div class="hbars">
          ${topics.map(([k, v]) => `<div class="hbar ai"><span class="name">${esc(k)}</span><div class="track"><i style="width:${(v / maxT) * 100}%"></i></div><b>${v}건</b></div>`).join('') || '<p class="muted">질문 기록이 없어요.</p>'}
        </div></div>
      </div>
    </div>`;
  $('#screen').onclick = (e) => { const b = e.target.closest('[data-addopt]'); if (b) openAddOption(null, b.dataset.addopt); };
}

const OPTION_PRESETS = {
  '맵기 조절': ['맵기', ['덜 맵게', '보통', '더 맵게']],
  '단맛 조절': ['단맛', ['덜 달게']],
  '양 조절(곱빼기 등)': ['양', ['곱빼기']],
  '재료 빼기': ['재료', ['빼기 요청']],
  '포장': ['포장', ['포장']],
  '아이용 메뉴': ['맵기', ['아이용(안 맵게)']],
};

async function openAddOption(menuId, request) {
  const menus = await api(`/api/owner/stores/${S.storeId}/menus`);
  const [group, names] = OPTION_PRESETS[request] || ['', ['']];
  modal(`
    <h2>옵션 추가</h2><p class="muted">${request ? `‘${esc(request)}’ 요청을 반영해요. 여러 메뉴에 한 번에 추가할 수 있어요.` : '메뉴에 선택 옵션을 추가해요.'}</p>
    <form class="form" id="optForm" style="margin-top:14px">
      <label>적용할 메뉴<div class="checks">${menus.filter((m) => m.is_available).map((m) => `<label><input type="checkbox" name="menu" value="${m.id}" ${menuId === m.id ? 'checked' : ''}>${esc(m.name)}</label>`).join('')}</div></label>
      <div class="row"><label>옵션 그룹<input name="group" value="${esc(group)}" placeholder="예) 맵기" required></label>
      <label>추가 금액<input name="extra" type="number" value="0" min="0"></label></div>
      <label>옵션 이름 (쉼표로 여러 개)<input name="names" value="${esc(names.join(', '))}" placeholder="예) 덜 맵게, 더 맵게" required></label>
      <div class="actions"><button type="button" class="btn ghost" data-close>취소</button><button class="btn primary">추가</button></div>
    </form>`);
  $('#optForm').onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const ids = f.getAll('menu').map(Number);
    if (!ids.length) return toast('메뉴를 하나 이상 골라주세요');
    const optNames = f.get('names').split(',').map((x) => x.trim()).filter(Boolean);
    for (const id of ids) for (const name of optNames)
      await api(`/api/owner/menus/${id}/options`, { method: 'POST', body: { group: f.get('group'), name, extra_price: +f.get('extra') || 0 } });
    closeModal(); toast(`${ids.length}개 메뉴에 옵션을 추가했어요`); go(S.view);
  };
}

// ===== 메뉴 관리 =====
async function renderMenus() {
  $('#headActions').innerHTML = '<button class="btn primary" id="newMenu">+ 메뉴 추가</button>';
  $('#newMenu').onclick = () => openMenuForm();
  const menus = await api(`/api/owner/stores/${S.storeId}/menus`);
  $('#screen').innerHTML = `<div class="panel overflow"><table class="table">
    <thead><tr><th>메뉴</th><th>분류</th><th>가격</th><th>맵기</th><th>단맛</th><th>옵션</th><th>판매</th><th></th></tr></thead>
    <tbody>${menus.map((m) => `
      <tr class="${m.is_available ? '' : 'off'}">
        <td><b>${esc(m.name)}</b><br><span class="muted" style="font-size:12px">${esc(m.description)}</span></td>
        <td>${esc(m.category)}</td>
        <td><input class="price" data-price="${m.id}" type="number" value="${m.price}"></td>
        <td>${m.spicy_level}</td><td>${m.sweetness}</td>
        <td>${m.options.map((o) => `<span class="opt-chip">${esc(o.group)}: ${esc(o.name)}${o.extra_price ? ' +' + o.extra_price.toLocaleString() : ''}<button data-delopt="${o.id}" title="삭제">✕</button></span>`).join('')}
          <button class="btn ghost small" data-newopt="${m.id}">+ 옵션</button></td>
        <td><button class="switch ${m.is_available ? 'on' : ''}" data-toggle="${m.id}" data-on="${m.is_available}" title="판매/품절"></button></td>
        <td><button class="btn ghost small" data-edit="${m.id}">수정</button></td>
      </tr>`).join('')}</tbody></table>
    <p class="muted" style="margin-top:12px">가격은 칸을 고치고 Enter를 누르면 저장돼요. 스위치를 끄면 품절로 키오스크에서 숨겨져요.</p></div>`;
  const byId = Object.fromEntries(menus.map((m) => [m.id, m]));
  $('#screen').onclick = async (e) => {
    const t = e.target.closest('button'); if (!t) return;
    if (t.dataset.toggle) { await api('/api/owner/menus/' + t.dataset.toggle, { method: 'PATCH', body: { is_available: t.dataset.on !== 'true' } }); renderMenus(); }
    if (t.dataset.delopt) { await api('/api/owner/options/' + t.dataset.delopt, { method: 'DELETE' }); toast('옵션을 지웠어요'); renderMenus(); }
    if (t.dataset.newopt) openAddOption(+t.dataset.newopt);
    if (t.dataset.edit) openMenuForm(byId[t.dataset.edit]);
  };
  $('#screen').onkeydown = async (e) => {
    if (e.key === 'Enter' && e.target.dataset.price) {
      await api('/api/owner/menus/' + e.target.dataset.price, { method: 'PATCH', body: { price: +e.target.value } });
      toast('가격을 바꿨어요'); e.target.blur();
    }
  };
}

function openMenuForm(m) {
  const v = m || { name: '', description: '', category: '', price: '', spicy_level: 0, sweetness: 0, tags: [], allergens: [], image_url: '' };
  modal(`
    <h2>${m ? '메뉴 수정' : '메뉴 추가'}</h2>
    <form class="form" id="menuForm" style="margin-top:14px">
      <div class="row"><label>이름<input name="name" value="${esc(v.name)}" required></label><label>분류<input name="category" value="${esc(v.category)}" placeholder="예) 찌개"></label></div>
      <label>설명<input name="description" value="${esc(v.description)}"></label>
      <div class="row"><label>가격<input name="price" type="number" min="0" value="${v.price}" required></label><label>이미지 주소 (선택)<input name="image_url" value="${esc(v.image_url)}"></label></div>
      <div class="row"><label>맵기 (0~5)<input name="spicy_level" type="number" min="0" max="5" value="${v.spicy_level}"></label><label>단맛 (0~5)<input name="sweetness" type="number" min="0" max="5" value="${v.sweetness}"></label></div>
      <div class="row"><label>태그 (쉼표)<input name="tags" value="${esc(v.tags.join(', '))}" placeholder="예) 인기, 채식"></label><label>알레르기 성분 (쉼표)<input name="allergens" value="${esc(v.allergens.join(', '))}" placeholder="예) 대두, 밀"></label></div>
      <p class="muted" style="margin:0">맵기·단맛·알레르기 정보는 AI 직원이 손님 질문에 답할 때 사용해요.</p>
      <div class="actions"><button type="button" class="btn ghost" data-close>취소</button><button class="btn primary">저장</button></div>
    </form>`);
  $('#menuForm').onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    const list = (s) => s.split(',').map((x) => x.trim()).filter(Boolean);
    const body = { ...f, price: +f.price, spicy_level: +f.spicy_level, sweetness: +f.sweetness, tags: list(f.tags), allergens: list(f.allergens) };
    try {
      if (m) await api('/api/owner/menus/' + m.id, { method: 'PATCH', body });
      else await api(`/api/owner/stores/${S.storeId}/menus`, { method: 'POST', body });
      closeModal(); toast('저장했어요'); renderMenus();
    } catch (err) { toast(err.message); }
  };
}

// ===== 주문 =====
const STATUS = { pending: '결제 대기', paid: '조리 대기', served: '서빙 완료', cancelled: '취소' };
async function renderOrders(silent) {
  const orders = await api(`/api/owner/stores/${S.storeId}/orders`);
  if (S.view !== 'orders') return;
  if (!silent) $('#headActions').innerHTML = '<span class="muted">5초마다 자동 새로고침</span>';
  $('#screen').innerHTML = `<div class="panel overflow"><table class="table">
    <thead><tr><th>번호</th><th>시간</th><th>테이블</th><th>메뉴</th><th>금액</th><th>상태</th><th></th></tr></thead>
    <tbody>${orders.map((o) => `<tr>
      <td>#${o.id}</td><td>${new Date(o.created_at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td>
      <td>${esc(o.table_no || '-')}</td>
      <td>${o.items.map((i) => `${esc(i.name)}${i.quantity > 1 ? ' ×' + i.quantity : ''}${i.options.length ? ` <span class="muted">(${i.options.map((x) => esc(x.name)).join(', ')})</span>` : ''}`).join('<br>')}</td>
      <td>${won(o.total_amount)}</td><td><span class="status ${o.status}">${STATUS[o.status] || o.status}</span></td>
      <td>${o.status === 'paid' ? `<button class="btn primary small" data-st="served" data-o="${o.id}">서빙 완료</button>` : ''}
          ${o.status === 'pending' ? `<button class="btn ghost small" data-st="cancelled" data-o="${o.id}">취소</button>` : ''}</td>
    </tr>`).join('') || '<tr><td colspan="7" class="muted">주문이 없어요.</td></tr>'}</tbody></table></div>`;
  $('#screen').onclick = async (e) => {
    const b = e.target.closest('[data-st]'); if (!b) return;
    await api(`/api/owner/orders/${b.dataset.o}/status`, { method: 'PATCH', body: { status: b.dataset.st } });
    refreshPending(); renderOrders(true);
  };
}

// ===== 가게 설정 =====
async function renderSettings() {
  $('#headActions').innerHTML = '<button class="btn ghost" id="newStore">+ 새 가게</button>';
  $('#newStore').onclick = openNewStore;
  if (!S.storeId) { $('#screen').innerHTML = '<p class="muted">아직 가게가 없어요. 오른쪽 위에서 새 가게를 만들어 주세요.</p>'; return; }
  const [store, kiosks] = await Promise.all([api('/api/stores/' + S.storeId), api(`/api/owner/stores/${S.storeId}/kiosks`)]);
  $('#screen').innerHTML = `
    <div class="grid two">
      <div class="panel"><h3>가게 정보</h3>
        <form class="form" id="storeForm">
          <div class="row"><label>가게 이름<input name="name" value="${esc(store.name)}"></label><label>분류<input name="category" value="${esc(store.category)}"></label></div>
          <label>소개 (AI 직원이 참고해요)<textarea name="description" rows="2">${esc(store.description)}</textarea></label>
          <div class="row"><label>주소<input name="address" value="${esc(store.address)}"></label><label>지역 (지역화폐 판단용)<input name="region" value="${esc(store.region)}" placeholder="예) 서울 마포구"></label></div>
          <label>유니 포인트 적립률 (%)<input name="point_rate" type="number" step="0.5" min="0" max="50" value="${(store.point_rate * 100).toFixed(1)}"></label>
          <fieldset class="disc-set"><legend>할인 행사 <small class="muted">${store.discount ? `진행 중 · ${store.discount.rate}%` : '없음'}</small></legend>
            <div class="row"><label>할인율 (%)<input name="discount_rate" type="number" min="0" max="90" value="${store.discount ? store.discount_rate : 0}"></label>
            <label>끝나는 시각<input name="discount_until" type="datetime-local" value="${store.discount_until ? store.discount_until.slice(0, 16) : ''}"></label></div>
            <label>행사 이름 (손님 앱·키오스크 광고에 보여요)<input name="discount_title" value="${esc(store.discount_title || '')}" placeholder="예) 점심 특가 10%"></label>
            <p class="muted" style="margin:0">할인율을 0으로 저장하면 행사가 끝나요. 주문 금액에서 자동으로 빠져요.</p>
          </fieldset>
          <label>받는 결제수단<div class="checks">${S.payTypes.map((p) => `<label><input type="checkbox" name="pay" value="${p.value}" ${store.supported_pay_types.includes(p.value) ? 'checked' : ''}>${esc(p.label)}</label>`).join('')}</div></label>
          <div><button class="btn primary">저장</button></div>
        </form>
      </div>
      <div class="panel"><h3>키오스크 / 테이블 기기</h3>
        <table class="table"><thead><tr><th>이름</th><th>테이블</th><th>기기 키</th></tr></thead>
        <tbody>${kiosks.map((k) => `<tr><td>${esc(k.name)}</td><td>${esc(k.table_no || '-')}</td><td><span class="key">${esc(k.api_key)}</span></td></tr>`).join('') || '<tr><td colspan="3" class="muted">등록된 기기가 없어요.</td></tr>'}</tbody></table>
        <form class="form" id="kioskForm" style="margin-top:14px"><div class="row"><label>기기 이름<input name="name" placeholder="예) 3번 테이블" required></label><label>테이블 번호<input name="table_no" placeholder="3"></label></div>
          <div><button class="btn primary">기기 등록</button></div></form>
        <p class="muted">키오스크 화면 오른쪽 위 ⚙에 기기 키를 넣으면 이 가게로 연결돼요.</p>
      </div>
    </div>`;
  $('#storeForm').onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target), f = Object.fromEntries(fd);
    await api('/api/owner/stores/' + S.storeId, { method: 'PATCH', body: {
      name: f.name, category: f.category, description: f.description, address: f.address, region: f.region,
      point_rate: (+f.point_rate || 0) / 100, supported_pay_types: fd.getAll('pay'),
      discount_rate: +f.discount_rate || 0, discount_title: f.discount_title || '', ...(f.discount_until ? { discount_until: f.discount_until } : {}) } });
    S.stores = await api('/api/owner/stores'); renderStoreSelect(); toast('저장했어요');
  };
  $('#kioskForm').onsubmit = async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    await api(`/api/owner/stores/${S.storeId}/kiosks`, { method: 'POST', body: { name: f.name, table_no: f.table_no || null } });
    toast('기기를 등록했어요'); renderSettings();
  };
}

function openNewStore() {
  modal(`<h2>새 가게</h2><form class="form" id="nsForm" style="margin-top:14px">
    <label>가게 이름<input name="name" required></label><div class="row"><label>분류<input name="category" placeholder="예) 한식"></label><label>지역<input name="region" placeholder="예) 서울 마포구"></label></div>
    <label>소개<input name="description"></label>
    <div class="actions"><button type="button" class="btn ghost" data-close>취소</button><button class="btn primary">만들기</button></div></form>`);
  $('#nsForm').onsubmit = async (e) => {
    e.preventDefault();
    const s = await api('/api/owner/stores', { method: 'POST', body: Object.fromEntries(new FormData(e.target)) });
    S.stores = await api('/api/owner/stores'); S.storeId = s.id; ls('ownerStore', s.id);
    renderStoreSelect(); closeModal(); toast('가게를 만들었어요'); go('menus');
  };
}

// ===== 시작 =====
if (TOKEN) start(); else $('#loginView').classList.remove('hidden');
