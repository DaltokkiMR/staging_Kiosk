/* Counter — React Bits Counter(MIT + Commons Clause, David Haz)를 참고한 바닐라 오도미터.
   숫자가 바뀌면 자리마다 0~9 띠가 굴러가며(살짝 튕기며) 새 값으로 바뀜.
   UFX.counter(el, { value, format }) → { set(v) }
   UFX.countdown(el, until, { onEnd }) → 'D-1 05:12:33' 형태로 매초 굴러가는 남은 시간 → { stop() } */
(function () {
  const css = `
  .ufx-counter { display: inline-flex; align-items: baseline; line-height: 1; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .ufx-digit { position: relative; display: inline-block; height: 1.15em; width: 0.62em; overflow: hidden; vertical-align: -0.15em;
    -webkit-mask-image: linear-gradient(to bottom, transparent 0, #000 22%, #000 78%, transparent 100%);
            mask-image: linear-gradient(to bottom, transparent 0, #000 22%, #000 78%, transparent 100%); }
  .ufx-strip { position: absolute; left: 0; right: 0; top: 0; transition: transform var(--ufx-dur, .7s) cubic-bezier(.34, 1.45, .64, 1); will-change: transform; }
  .ufx-strip i { display: flex; align-items: center; justify-content: center; height: 1.15em; font-style: normal; }
  .ufx-sym { display: inline-block; white-space: pre; }`;
  if (!document.getElementById('ufx-counter-css')) {
    const st = document.createElement('style'); st.id = 'ufx-counter-css'; st.textContent = css; document.head.appendChild(st);
  }
  const DIGITS = '0123456789';
  function counter(el, opts = {}) {
    const fmt = opts.format || ((v) => String(v));
    el.classList.add('ufx-counter');
    let slots = [];  // 오른쪽(1의 자리)부터 맞춰서 재사용
    function build(text) {
      const chars = [...text];
      // 자리 구조가 바뀌면 다시 만듦
      const sig = chars.map((c) => (DIGITS.includes(c) ? 'd' : c)).join('');
      if (sig !== el.dataset.sig) {
        el.dataset.sig = sig; el.innerHTML = ''; slots = [];
        chars.forEach((c) => {
          if (DIGITS.includes(c)) {
            const d = document.createElement('span'); d.className = 'ufx-digit';
            const strip = document.createElement('span'); strip.className = 'ufx-strip';
            strip.innerHTML = [...DIGITS].map((n) => `<i>${n}</i>`).join('');
            d.appendChild(strip); el.appendChild(d);
            // 처음엔 0에서 굴러 올라오게
            strip.style.transform = 'translateY(0)';
            slots.push({ strip, digit: true });
          } else {
            const s = document.createElement('span'); s.className = 'ufx-sym'; s.textContent = c; el.appendChild(s); slots.push({ digit: false });
          }
        });
        void el.offsetWidth;
      }
      let k = 0;
      chars.forEach((c, i) => {
        const sl = slots[i];
        if (!sl.digit) return;
        sl.strip.style.transitionDelay = `${(chars.length - i) * (opts.stagger ?? 0.03)}s`;
        sl.strip.style.transform = `translateY(${-DIGITS.indexOf(c) * 10}%)`;
        k++;
      });
    }
    const api = { set(v) { build(fmt(v)); return api; } };
    if (opts.value !== undefined) api.set(opts.value);
    return api;
  }
  const pad = (n) => String(n).padStart(2, '0');
  function countdown(el, until, opts = {}) {
    const end = typeof until === 'number' ? until : new Date(until).getTime();
    const c = counter(el, { stagger: 0 });
    let t = 0;
    const tick = () => {
      const left = Math.max(0, Math.floor((end - Date.now()) / 1000));
      const d = Math.floor(left / 86400), h = Math.floor((left % 86400) / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
      c.set(`${d > 0 ? 'D-' + d + ' ' : ''}${pad(h)}:${pad(m)}:${pad(s)}`);
      if (left <= 0) { clearInterval(t); opts.onEnd && opts.onEnd(); }
    };
    tick(); t = setInterval(tick, 1000);
    return { stop() { clearInterval(t); } };
  }
  window.UFX = window.UFX || {};
  window.UFX.counter = counter;
  window.UFX.countdown = countdown;
})();
