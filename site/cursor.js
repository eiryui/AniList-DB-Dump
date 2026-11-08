/* Custom cursor (dot + trailing ring), themed to AniList-DB-Dump.
   Only active for mouse/trackpad users who haven't asked for reduced motion. */
(function () {
  if (!window.matchMedia('(hover:hover) and (pointer:fine)').matches) return;
  if (window.matchMedia('(prefers-reduced-motion:reduce)').matches) return;

  var css = [
    'html.has-cursor,html.has-cursor *{cursor:none!important}',
    'html.has-cursor input,html.has-cursor textarea,html.has-cursor select{cursor:text!important}',
    '.cursor-dot,.cursor-ring{position:fixed;top:0;left:0;pointer-events:none;z-index:99999;border-radius:50%;will-change:transform}',
    '.cursor-dot{width:6px;height:6px;margin:-3px 0 0 -3px;background:#3db4f2;box-shadow:0 0 10px rgba(61,180,242,.85);transition:opacity .2s}',
    '.cursor-ring{width:36px;height:36px;margin:-18px 0 0 -18px;border:1.5px solid rgba(139,109,255,.5);',
    'transition:width .25s cubic-bezier(.22,1,.36,1),height .25s cubic-bezier(.22,1,.36,1),margin .25s cubic-bezier(.22,1,.36,1),border-color .25s,background .25s,opacity .2s}',
    '.cursor-ring.is-hovering{width:52px;height:52px;margin:-26px 0 0 -26px;border-color:rgba(61,180,242,.8);background:rgba(61,180,242,.08)}',
    '.cursor-ring.is-clicking{width:28px;height:28px;margin:-14px 0 0 -14px;border-color:rgba(139,109,255,.95);background:rgba(139,109,255,.14)}',
    '.cursor-dot.is-hovering{opacity:0}',
    '.cursor-dot.is-hidden,.cursor-ring.is-hidden{opacity:0}'
  ].join('');
  var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

  var dot = document.createElement('div'), ring = document.createElement('div');
  dot.className = 'cursor-dot is-hidden'; ring.className = 'cursor-ring is-hidden';
  dot.setAttribute('aria-hidden', 'true'); ring.setAttribute('aria-hidden', 'true');
  document.body.append(dot, ring);
  document.documentElement.classList.add('has-cursor');

  var mx = -200, my = -200, rx = -200, ry = -200, visible = false, LERP = 0.22;
  var INTERACTIVE = 'a,button,[role="button"],summary,label';

  (function tick() {
    rx += (mx - rx) * LERP; ry += (my - ry) * LERP;
    dot.style.transform = 'translate(' + mx + 'px,' + my + 'px)';
    ring.style.transform = 'translate(' + Math.round(rx * 10) / 10 + 'px,' + Math.round(ry * 10) / 10 + 'px)';
    requestAnimationFrame(tick);
  })();

  function show(v) {
    visible = v;
    dot.classList.toggle('is-hidden', !v); ring.classList.toggle('is-hidden', !v);
  }
  var P = { passive: true };
  document.addEventListener('mousemove', function (e) {
    mx = e.clientX; my = e.clientY;
    if (!visible) { rx = mx; ry = my; show(true); }
  }, P);
  document.documentElement.addEventListener('mouseleave', function () { show(false); }, P);
  document.documentElement.addEventListener('mouseenter', function () { show(true); }, P);
  document.addEventListener('mousedown', function () { ring.classList.add('is-clicking'); ring.classList.remove('is-hovering'); }, P);
  document.addEventListener('mouseup', function () { ring.classList.remove('is-clicking'); }, P);
  document.addEventListener('mouseover', function (e) {
    if (e.target.closest && e.target.closest(INTERACTIVE)) { dot.classList.add('is-hovering'); ring.classList.add('is-hovering'); }
  }, P);
  document.addEventListener('mouseout', function (e) {
    if (e.target.closest && e.target.closest(INTERACTIVE)) { dot.classList.remove('is-hovering'); ring.classList.remove('is-hovering'); }
  }, P);
  window.addEventListener('touchstart', function () {
    dot.remove(); ring.remove(); document.documentElement.classList.remove('has-cursor');
  }, { once: true, passive: true });
})();
