/* ============================================================
   Презентация «Учёт трудозатрат» — движок слайдов
   Слайд 1280×720 масштабируется под окно, поэтому вёрстка
   выглядит одинаково на любом экране и корректно печатается.
   ============================================================ */
(function () {
  'use strict';

  var W = 1280, H = 720;
  var slides = [].slice.call(document.querySelectorAll('.slide'));
  var idx = 0;
  var hud, bar;

  function fit() {
    var k = Math.min(window.innerWidth / W, window.innerHeight / H);
    for (var i = 0; i < slides.length; i++) {
      slides[i].style.transform = 'scale(' + k + ')';
    }
  }

  function render() {
    for (var i = 0; i < slides.length; i++) {
      slides[i].classList.toggle('is-active', i === idx);
    }
    if (hud) hud.innerHTML = '<b>' + (idx + 1) + '</b> / ' + slides.length +
      '<span class="hud-hint">← → листать · P печать</span>';
    if (bar) bar.style.width = ((idx + 1) / slides.length * 100) + '%';
    if (history.replaceState) history.replaceState(null, '', '#' + (idx + 1));
  }

  function go(n) {
    var next = Math.max(0, Math.min(slides.length - 1, n));
    if (next === idx) return;
    idx = next;
    render();
  }

  document.addEventListener('keydown', function (e) {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    switch (e.key) {
      case 'ArrowRight': case 'ArrowDown': case ' ': case 'PageDown': case 'Enter':
        e.preventDefault(); go(idx + 1); break;
      case 'ArrowLeft': case 'ArrowUp': case 'PageUp': case 'Backspace':
        e.preventDefault(); go(idx - 1); break;
      case 'Home': e.preventDefault(); go(0); break;
      case 'End':  e.preventDefault(); go(slides.length - 1); break;
      case 'p': case 'P': case 'р': case 'Р':
        e.preventDefault(); window.print(); break;
    }
  });

  var wheelLock = 0;
  window.addEventListener('wheel', function (e) {
    var now = Date.now();
    if (now - wheelLock < 480) return;
    if (Math.abs(e.deltaY) < 12) return;
    wheelLock = now;
    go(idx + (e.deltaY > 0 ? 1 : -1));
  }, { passive: true });

  var touchY = null;
  window.addEventListener('touchstart', function (e) { touchY = e.touches[0].clientY; }, { passive: true });
  window.addEventListener('touchend', function (e) {
    if (touchY === null) return;
    var dy = touchY - e.changedTouches[0].clientY;
    if (Math.abs(dy) > 45) go(idx + (dy > 0 ? 1 : -1));
    touchY = null;
  }, { passive: true });

  window.addEventListener('resize', fit);

  document.addEventListener('DOMContentLoaded', function () {
    hud = document.getElementById('hud');
    bar = document.getElementById('progress');

    var prev = document.querySelector('.edge-nav.prev');
    var next = document.querySelector('.edge-nav.next');
    if (prev) prev.addEventListener('click', function () { go(idx - 1); });
    if (next) next.addEventListener('click', function () { go(idx + 1); });

    var start = parseInt((location.hash || '').replace('#', ''), 10);
    if (start > 0 && start <= slides.length) idx = start - 1;

    fit();
    render();
  });
})();
