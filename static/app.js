/* Drug Stock — shared effects */
(function(){
  var reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Floating pills in background
  var bg = document.querySelector('.bg');
  if (bg && !reduce) {
    var icons = ['💊','⚕️','🧪','💉'];
    for (var i = 0; i < 12; i++) {
      var p = document.createElement('span');
      p.className = 'pill';
      p.textContent = icons[i % icons.length];
      p.style.left = (Math.random() * 100) + '%';
      p.style.fontSize = (14 + Math.random() * 22) + 'px';
      p.style.animationDuration = (18 + Math.random() * 22) + 's';
      p.style.animationDelay = (-Math.random() * 30) + 's';
      bg.appendChild(p);
    }
  }

  // Stagger index for entrance animation
  document.querySelectorAll('.wrap > *, .menu > *').forEach(function(el, i){ el.style.setProperty('--i', i); });

  // Spotlight follow mouse on cards
  document.addEventListener('pointermove', function(e){
    var c = e.target.closest && e.target.closest('.card');
    if (!c) return;
    var r = c.getBoundingClientRect();
    c.style.setProperty('--mx', (e.clientX - r.left) + 'px');
    c.style.setProperty('--my', (e.clientY - r.top) + 'px');
  });

  // 3D tilt on home menu cards
  if (!reduce && matchMedia('(hover: hover)').matches) {
    document.querySelectorAll('.menu .card').forEach(function(c){
      c.addEventListener('pointermove', function(e){
        var r = c.getBoundingClientRect();
        var x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
        c.style.transform = 'perspective(800px) rotateX(' + (-y * 7) + 'deg) rotateY(' + (x * 9) + 'deg) translateY(-4px)';
      });
      c.addEventListener('pointerleave', function(){ c.style.transform = ''; });
    });
  }

  // Ripple on buttons
  document.addEventListener('click', function(e){
    var b = e.target.closest && e.target.closest('.btn, button');
    if (!b) return;
    var r = b.getBoundingClientRect(), d = Math.max(r.width, r.height);
    var s = document.createElement('span');
    s.className = 'ripple';
    s.style.width = s.style.height = d + 'px';
    s.style.left = (e.clientX - r.left - d / 2) + 'px';
    s.style.top = (e.clientY - r.top - d / 2) + 'px';
    b.appendChild(s);
    setTimeout(function(){ s.remove(); }, 600);
  });

  // Toasts auto-dismiss
  function closeToast(t){ t.classList.add('out'); setTimeout(function(){ t.remove(); }, 400); }
  document.querySelectorAll('.toast').forEach(function(t){
    setTimeout(function(){ closeToast(t); }, 7000);
    var x = t.querySelector('.x');
    if (x) x.addEventListener('click', function(){ closeToast(t); });
  });

  // Prevent double submit
  document.querySelectorAll('form').forEach(function(f){
    f.addEventListener('submit', function(e){
      if (e.defaultPrevented) return;
      var s = f.querySelector('button[type=submit]');
      if (s) setTimeout(function(){ s.disabled = true; s.style.opacity = .6; }, 0);
    });
  });
})();
