/* 손님 앱 인터랙션 — React Bits(MIT + Commons Clause, David Haz) 컴포넌트를 바닐라 JS로 옮겨 변형
   - pillNav     : Pill Nav (glide 프리셋, pill 인디케이터, bounce 0.42) → 하단 탭
   - depthCarousel: Depth Carousel → 결제 카드 고르기
   - bellToggle  : Bell Toggle → 가게 알림
   - swipeToast  : Swipe Toast → 알림 메시지 (아래로 밀면 닫힘, 남은 시간 심지) */
(function () {
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---------- Pill Nav (glide) ----------
  // 두 끝(x0, x1)이 각자 스프링으로 따라감. 가는 방향 앞쪽 끝이 더 빨라서 늘어났다가 줄어드는 젤리 느낌.
  function pillNav(nav, opts = {}) {
    const bounce = opts.bounce ?? 0.42, stretch = opts.stretch ?? 0.5;
    const items = [...nav.querySelectorAll('[data-view]')];
    nav.classList.add('pn');
    const track = document.createElement('div'); track.className = 'pn-track';
    items.forEach((b) => track.appendChild(b));
    const glide = document.createElement('span'); glide.className = 'pn-glide';
    const ink = document.createElement('div'); ink.className = 'pn-ink'; ink.setAttribute('aria-hidden', 'true');
    ink.innerHTML = items.map((b) => `<span class="pn-ink-item">${b.innerHTML}</span>`).join('');
    track.prepend(glide); track.appendChild(ink);
    nav.appendChild(track);
    const st = { x0: 0, x1: 0, v0: 0, v1: 0, alpha: 0, pop: 1, press: 1, pv: 0, pressing: false, active: -1 };
    let rects = [], raf = 0, last = 0, W = 0, H = 0;
    const measure = () => { W = track.offsetWidth; H = track.offsetHeight; rects = items.map((b) => ({ left: b.offsetLeft, width: b.offsetWidth })); };
    const render = () => {
      const width = Math.max(0, st.x1 - st.x0), target = rects[st.active];
      const squash = target ? 1 - clamp((width / Math.max(target.width, 1) - 1) * 0.3, 0, 0.14) : 1;
      const sc = st.press * st.pop;
      glide.style.width = width + 'px';
      glide.style.transform = `translate3d(${st.x0}px,0,0) scale(${sc},${sc * squash})`;
      glide.style.opacity = st.alpha;
      const half = (width * sc) / 2, center = (st.x0 + st.x1) / 2, inset = (H * (1 - sc * squash)) / 2;
      ink.style.clipPath = `inset(${inset}px ${W - center - half}px ${inset}px ${center - half}px round ${H / 2}px)`;
    };
    const tick = (now) => {
      raf = 0;
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 1 / 60; last = now;
      const t = rects[st.active]; let busy = false;
      if (t) {
        const t0 = t.left, t1 = t.left + t.width, zeta = 1 - 0.55 * bounce, base = 520;
        if (st.alpha < 0.02) { st.x0 = t0; st.x1 = t1; st.v0 = st.v1 = 0; st.pop = 0.9; }
        if (reduce) { st.x0 = t0; st.x1 = t1; } else {
          const dir = Math.sign((t0 + t1) / 2 - (st.x0 + st.x1) / 2);
          const lead = base * (1 + 0.9 * stretch), trail = base * (1 - 0.5 * stretch);
          const k0 = dir < 0 ? lead : dir > 0 ? trail : base, k1 = dir > 0 ? lead : dir < 0 ? trail : base;
          const steps = Math.ceil(dt * 240), h = dt / steps;
          for (let i = 0; i < steps; i++) {
            st.v0 += (-k0 * (st.x0 - t0) - 2 * zeta * Math.sqrt(k0) * st.v0) * h; st.x0 += st.v0 * h;
            st.v1 += (-k1 * (st.x1 - t1) - 2 * zeta * Math.sqrt(k1) * st.v1) * h; st.x1 += st.v1 * h;
          }
        }
        st.alpha += (1 - st.alpha) * (1 - Math.exp(-dt / 0.06));
        busy = Math.abs(st.x0 - t0) > 0.05 || Math.abs(st.x1 - t1) > 0.05 || Math.abs(st.v0) > 0.5 || Math.abs(st.v1) > 0.5 || st.alpha < 0.999;
      }
      st.pop += (1 - st.pop) * (1 - Math.exp(-dt / 0.09)); if (Math.abs(1 - st.pop) > 0.001) busy = true;
      const pt = st.pressing ? 0.95 : 1;
      st.pv += (-700 * (st.press - pt) - 30 * st.pv) * dt; st.press += st.pv * dt;
      if (Math.abs(st.press - pt) > 0.0005 || Math.abs(st.pv) > 0.01) busy = true;
      render();
      if (busy) raf = requestAnimationFrame(tick); else last = 0;
    };
    const wake = () => { if (!raf) raf = requestAnimationFrame(tick); };
    const set = (view) => {
      const i = items.findIndex((b) => b.dataset.view === view); if (i < 0) return;
      st.active = i; items.forEach((b, k) => b.classList.toggle('active', k === i));
      measure(); wake();
    };
    track.addEventListener('pointerdown', (e) => { if (e.target.closest('[data-view]')) { st.pressing = true; wake(); } });
    addEventListener('pointerup', () => { if (st.pressing) { st.pressing = false; wake(); } });
    new ResizeObserver(() => { measure(); render(); }).observe(track);
    return { set };
  }

  // ---------- Depth Carousel ----------
  // 카드가 3D 레일 위에서 뒤로 물러나며 쌓임. 드래그·키보드·탭으로 이동.
  function depthCarousel(root, cards, opts = {}) {
    const o = Object.assign({ cardWidth: 260, cardHeight: 164, depth: 150, spread: 58, tilt: 20, visibleCards: 3, falloff: 0.2, blur: 4, duration: 650, loop: false, start: 0 }, opts);
    const n = cards.length;
    root.classList.add('dc'); root.tabIndex = 0;
    root.style.setProperty('--dc-w', o.cardWidth + 'px'); root.style.setProperty('--dc-h', o.cardHeight + 'px');
    root.innerHTML = `<div class="dc-stage">${cards.map((html, i) => `<div class="dc-card" data-i="${i}">${html}<span class="dc-tint"></span></div>`).join('')}</div>
      <div class="dc-dots">${cards.map((_, i) => `<button class="dc-dot" data-dot="${i}" aria-label="${i + 1}번째"></button>`).join('')}</div>`;
    const els = [...root.querySelectorAll('.dc-card')], tints = els.map((e) => e.querySelector('.dc-tint')), dots = [...root.querySelectorAll('.dc-dot')];
    let pos = clamp(o.start, 0, n - 1), focus = Math.round(pos), anim = 0, drag = null, scale = 1;
    const layout = (p) => {
      for (let i = 0; i < n; i++) {
        let d = i - p;
        if (o.loop && n > 1) { d = ((d % n) + n) % n; if (d > n / 2) d -= n; }
        const back = Math.max(0, d), az = Math.abs(d), shown = az <= o.visibleCards + 0.5;
        const tz = -o.depth * d, tx = o.spread * d, ry = o.tilt * clamp(d, 0, 1);
        let op = d < 0 ? Math.max(0, 1 + d) : 1; if (!shown) op = 0;
        const bright = Math.max(0.15, 1 - back * o.falloff), bl = o.blur > 0 ? Math.min(o.blur, (back / Math.max(1, o.visibleCards)) * o.blur) : 0;
        const el = els[i];
        el.style.transform = `translate(-50%,-50%) scale(${scale}) translateX(${tx.toFixed(2)}px) translateZ(${tz.toFixed(2)}px) rotateY(${ry.toFixed(3)}deg)`;
        el.style.opacity = op.toFixed(3); el.style.filter = `brightness(${bright.toFixed(3)}) blur(${bl.toFixed(2)}px)`;
        el.style.zIndex = String(Math.round(2000 - d * 20)); el.style.pointerEvents = shown && op > 0.05 ? 'auto' : 'none';
        tints[i].style.opacity = clamp(back * o.falloff * 1.25, 0, 0.86).toFixed(3);
      }
    };
    const ease = (t) => 1 - Math.pow(1 - t, 3);  // power3.out
    const tweenTo = (target) => {
      cancelAnimationFrame(anim);
      const from = pos, t0 = performance.now(), dur = reduce ? 0 : o.duration;
      const step = (now) => {
        const k = dur ? Math.min(1, (now - t0) / dur) : 1;
        pos = from + (target - from) * ease(k); layout(pos);
        if (k < 1) anim = requestAnimationFrame(step); else { if (o.loop) pos = ((pos % n) + n) % n; layout(pos); }
      };
      anim = requestAnimationFrame(step);
    };
    const setFocus = (raw) => {
      const idx = o.loop ? ((raw % n) + n) % n : clamp(raw, 0, n - 1);
      let delta = idx - pos;
      if (o.loop && n > 1) { delta = ((delta % n) + n) % n; if (delta > n / 2) delta -= n; }
      tweenTo(pos + delta);
      dots.forEach((d, k) => d.classList.toggle('on', k === idx));
      if (idx !== focus) { focus = idx; o.onChange && o.onChange(idx); }
    };
    const stepPx = () => Math.max(o.cardWidth * 0.55 * scale, 40);
    root.addEventListener('pointerdown', (e) => {
      if (n < 2 || e.target.closest('.dc-dot')) return;
      cancelAnimationFrame(anim);
      drag = { x: e.clientX, start: pos, lastX: e.clientX, lastT: performance.now(), v: 0, moved: false, id: e.pointerId };
    });
    root.addEventListener('pointermove', (e) => {
      if (!drag) return;
      const dx = e.clientX - drag.x;
      if (!drag.moved && Math.abs(dx) > 4) { drag.moved = true; try { root.setPointerCapture(drag.id); } catch {} }
      if (!drag.moved) return;
      const now = performance.now(), dt = Math.max(now - drag.lastT, 1);
      drag.v = (e.clientX - drag.lastX) / dt; drag.lastX = e.clientX; drag.lastT = now;
      pos = drag.start - dx / stepPx();
      if (!o.loop) pos = clamp(pos, -0.4, n - 0.6);
      layout(pos);
    });
    const end = () => {
      if (!drag) return; const d = drag; drag = null;
      if (!d.moved) return;
      root.dataset.dragged = '1'; setTimeout(() => delete root.dataset.dragged, 50);
      setFocus(Math.round(pos - (d.v * 180) / stepPx()));
    };
    root.addEventListener('pointerup', end); root.addEventListener('pointercancel', end);
    root.addEventListener('click', (e) => {
      if (root.dataset.dragged) return;
      const dot = e.target.closest('[data-dot]'); if (dot) return setFocus(+dot.dataset.dot);
      const c = e.target.closest('.dc-card'); if (c) { const i = +c.dataset.i; if (i === focus) o.onPick && o.onPick(i); else setFocus(i); }
    });
    root.addEventListener('keydown', (e) => { if (e.key === 'ArrowLeft') setFocus(focus - 1); if (e.key === 'ArrowRight') setFocus(focus + 1); });
    new ResizeObserver(([en]) => { scale = clamp(en.contentRect.width / (o.cardWidth + Math.abs(o.spread) * 2 + 80), 0.5, 1); layout(pos); }).observe(root);
    layout(pos); dots.forEach((d, k) => d.classList.toggle('on', k === focus));
    return { go: setFocus, get index() { return focus; } };
  }

  // ---------- Bell Toggle ----------
  const BELL = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/></svg>`;
  const CLAP = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M10 20.5a2 2 0 0 0 4 0"/></svg>`;
  const WAVE = (side) => `<svg class="bt-wave bt-wave--${side}" viewBox="0 0 14 14"><path d="${side === 'left' ? 'M9 2.5C6 4 5 7 5.5 10' : 'M5 2.5C8 4 9 7 8.5 10'}"/></svg>`;
  const ringKeys = (amp, passes) => {
    const k = [{ transform: 'rotate(0deg)', offset: 0 }];
    for (let i = 1; i <= passes; i++) k.push({ transform: `rotate(${(i % 2 ? 1 : -1) * amp * Math.pow(1 - (i - 1) / passes, 1)}deg)`, offset: i / (passes + 1) });
    k.push({ transform: 'rotate(0deg)', offset: 1 }); return k;
  };
  function bellToggle(btn, opts = {}) {
    let on = !!opts.on;
    btn.classList.add('bt');
    btn.innerHTML = `<span class="bt-bell"><span class="bt-glyph">${BELL}</span><span class="bt-clapper">${CLAP}</span>${WAVE('left')}${WAVE('right')}</span>
      <span class="bt-label"><span class="bt-l bt-off">${opts.offLabel || '알림 받기'}</span><span class="bt-l bt-on">${opts.onLabel || '알림 켜짐'}</span></span>`;
    const paint = () => { btn.dataset.on = on; btn.setAttribute('aria-pressed', on); };
    const ring = () => {
      if (reduce) return;
      btn.querySelector('.bt-glyph').animate(ringKeys(17, 5), { duration: 820, easing: 'linear' });
      btn.querySelector('.bt-clapper').animate(ringKeys(27, 5), { duration: 820, easing: 'linear', delay: 30 });
      btn.querySelectorAll('.bt-wave').forEach((w, i) => w.animate([
        { opacity: 0, transform: 'scale(.6)' }, { opacity: 1, transform: 'scale(1)', offset: 0.3 }, { opacity: 0, transform: `scale(1.2) translateX(${i ? 3 : -3}px)` }],
      { duration: 700, easing: 'ease-out' }));
    };
    btn.addEventListener('pointerdown', () => btn.dataset.pressed = '1');
    addEventListener('pointerup', () => delete btn.dataset.pressed);
    btn.addEventListener('click', async () => {
      const next = !on; on = next; paint(); if (on) ring();
      try { if (opts.onChange) await opts.onChange(on); } catch (e) { on = !next; paint(); throw e; }
    });
    paint();
    return { set(v) { on = v; paint(); } };
  }

  // ---------- Swipe Toast ----------
  let current = null;
  function swipeToast(msg, opts = {}) {
    const dur = opts.duration ?? 2800;
    if (current) current.dismiss(true);
    const el = document.createElement('div');
    el.className = 'st' + (opts.type ? ' st-' + opts.type : '');
    el.innerHTML = `<span class="st-ic">${opts.icon || (opts.type === 'error' ? '!' : '✓')}</span><span class="st-msg"></span><span class="st-fuse"><i></i></span>`;
    el.querySelector('.st-msg').textContent = msg;
    (opts.host || document.body).appendChild(el);
    const fuse = el.querySelector('.st-fuse i');
    let left = dur, startT = performance.now(), timer = 0, dead = false, y0 = null, dy = 0;
    const burn = () => { fuse.style.transition = `transform ${left}ms linear`; fuse.style.transform = 'scaleX(0)'; startT = performance.now(); timer = setTimeout(() => api.dismiss(), left); };
    const hold = () => { clearTimeout(timer); left -= performance.now() - startT; const w = fuse.getBoundingClientRect().width / fuse.parentElement.getBoundingClientRect().width;
      fuse.style.transition = 'none'; fuse.style.transform = `scaleX(${w})`; };
    const api = {
      dismiss(fast) {
        if (dead) return; dead = true; clearTimeout(timer);
        el.style.transition = fast ? 'opacity .12s' : 'transform .32s cubic-bezier(.23,1,.32,1), opacity .25s';
        el.style.transform = `translate(-50%, ${Math.max(dy, 0) + 80}px)`; el.style.opacity = 0;
        setTimeout(() => el.remove(), 340); if (current === api) current = null;
      },
    };
    requestAnimationFrame(() => { el.classList.add('in'); requestAnimationFrame(burn); });
    el.addEventListener('pointerdown', (e) => { y0 = e.clientY; hold(); el.setPointerCapture(e.pointerId); el.style.transition = 'none'; });
    el.addEventListener('pointermove', (e) => { if (y0 == null) return; dy = e.clientY - y0; el.style.transform = `translate(-50%, ${dy > 0 ? dy : dy * 0.25}px)`; el.style.opacity = String(1 - clamp(dy / 120, 0, 0.8)); });
    const up = () => { if (y0 == null) return; y0 = null; if (dy > 40) return api.dismiss(); el.style.transition = 'transform .3s cubic-bezier(.34,1.56,.64,1), opacity .2s'; el.style.transform = 'translate(-50%,0)'; el.style.opacity = 1; dy = 0; burn(); };
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up);
    current = api; return api;
  }

  window.UFX = window.UFX || {};
  Object.assign(window.UFX, { pillNav, depthCarousel, bellToggle, swipeToast });
})();
