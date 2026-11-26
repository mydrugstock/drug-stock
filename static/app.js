/* Drug Stock — Ember Light effects */
(function () {
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };

  // 1) หัวข้อเลื่อนขึ้นทีละบรรทัด (mask reveal)
  $$('.hero h1').forEach(function (h) {
    h.innerHTML = '<span class="mask"><span>' + h.innerHTML + '</span></span>';
  });

  // 2) ลำดับการปรากฏของส่วนต่าง ๆ
  $$('.wrap > *, .menu > *').forEach(function (el, i) { el.style.setProperty('--i', i); });

  // 3) Hero window: ขยายเต็มตอนเลื่อน + ภูเขาเคลื่อนตามเมาส์
  var hero = document.querySelector('.hero');
  if (hero && !reduce) {
    var ticking = false;
    function onScroll() {
      var p = Math.min(1, Math.max(0, window.scrollY / 260));
      hero.style.setProperty('--p', p.toFixed(3));
      ticking = false;
    }
    window.addEventListener('scroll', function () {
      if (!ticking) { ticking = true; requestAnimationFrame(onScroll); }
    }, { passive: true });
    onScroll();
    hero.addEventListener('pointermove', function (e) {
      var r = hero.getBoundingClientRect();
      hero.style.setProperty('--mx', ((e.clientX - r.left) / r.width - .5).toFixed(3));
    });
    hero.addEventListener('pointerleave', function () { hero.style.setProperty('--mx', 0); });
  }

  // 4) แสงตามเมาส์บนการ์ด
  document.addEventListener('pointermove', function (e) {
    var c = e.target.closest && e.target.closest('.card');
    if (!c) return;
    var r = c.getBoundingClientRect();
    c.style.setProperty('--mx', (e.clientX - r.left) + 'px');
    c.style.setProperty('--my', (e.clientY - r.top) + 'px');
  });

  // 5) การ์ดเมนูเอียงแบบ 3D
  if (!reduce && matchMedia('(hover: hover)').matches) {
    $$('.menu .card').forEach(function (c) {
      c.addEventListener('pointermove', function (e) {
        var r = c.getBoundingClientRect();
        var x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
        c.style.transform = 'perspective(800px) rotateX(' + (-y * 6) + 'deg) rotateY(' + (x * 8) + 'deg) translateY(-4px)';
      });
      c.addEventListener('pointerleave', function () { c.style.transform = ''; });
    });
  }

  // 6) ตัวเลขนับขึ้นเมื่อเลื่อนมาถึง
  var counters = $$('[data-count]');
  function runCount(el) {
    var end = parseFloat(el.getAttribute('data-count')) || 0, t0 = null, dur = 1100;
    if (reduce || end === 0) { el.textContent = end.toLocaleString('th-TH'); return; }
    function step(t) {
      if (!t0) t0 = t;
      var k = Math.min(1, (t - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      el.textContent = Math.round(end * e).toLocaleString('th-TH');
      if (k < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function (list) {
      list.forEach(function (en) { if (en.isIntersecting) { runCount(en.target); io.unobserve(en.target); } });
    }, { threshold: .4 });
    counters.forEach(function (c) { io.observe(c); });
  } else { counters.forEach(runCount); }

  // 7) ขั้นตอนบนแถบดำ: แถบเวลาเดิน จบแล้วขึ้นขั้นถัดไป คลิกเพื่อข้าม
  var band = document.querySelector('.band');
  if (band) {
    var steps = $$('.step', band), cur = 0;
    function go(n) {
      cur = (n + steps.length) % steps.length;
      steps.forEach(function (s) { s.classList.remove('on'); });
      void band.offsetWidth;
      steps[cur].classList.add('on');
    }
    go(0);
    if (!reduce) {
      band.addEventListener('animationend', function (e) {
        if (e.animationName === 'fill') go(cur + 1);
      });
      band.addEventListener('pointerenter', function () { band.classList.add('paused'); });
      band.addEventListener('pointerleave', function () { band.classList.remove('paused'); });
    }
    steps.forEach(function (s, k) {
      s.addEventListener('click', function () { go(k); });
      s.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(k); } });
    });
  }

  // 8) คลื่นกระเพื่อมบนปุ่ม
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('.btn, button');
    if (!b) return;
    var r = b.getBoundingClientRect(), d = Math.max(r.width, r.height);
    var s = document.createElement('span');
    s.className = 'ripple';
    s.style.width = s.style.height = d + 'px';
    s.style.left = (e.clientX - r.left - d / 2) + 'px';
    s.style.top = (e.clientY - r.top - d / 2) + 'px';
    b.appendChild(s);
    setTimeout(function () { s.remove(); }, 600);
  });

  // 9) Toast ปิดเอง
  function closeToast(t) { t.classList.add('out'); setTimeout(function () { t.remove(); }, 400); }
  $$('.toast').forEach(function (t) {
    setTimeout(function () { closeToast(t); }, 7000);
    var x = t.querySelector('.x');
    if (x) x.addEventListener('click', function () { closeToast(t); });
  });

  // 10) กันกดส่งซ้ำ
  $$('form').forEach(function (f) {
    f.addEventListener('submit', function (e) {
      if (e.defaultPrevented) return;
      var s = f.querySelector('button[type=submit]');
      if (s) setTimeout(function () { s.disabled = true; s.style.opacity = .6; }, 0);
    });
  });
  window.addEventListener('pageshow', function (e) {
    if (e.persisted) $$('button[type=submit]').forEach(function (b) { b.disabled = false; b.style.opacity = ''; });
  });
})();
