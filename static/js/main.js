// serveircMail — Main JavaScript

// ========== PARTICLES ==========
function initParticles() {
  const container = document.getElementById('particles-bg');
  if (!container) return;
  const colors = ['#6C63FF','#3EC6E0','#FF6584','#4ade80','#fbbf24'];
  const count = window.innerWidth < 768 ? 15 : 30;
  for (let i = 0; i < count; i++) {
    const p = document.createElement('div');
    p.className = 'particle';
    const size = Math.random() * 4 + 1;
    const color = colors[Math.floor(Math.random() * colors.length)];
    const dur = Math.random() * 15 + 8;
    const delay = Math.random() * 10;
    const drift = (Math.random() - 0.5) * 200;
    const maxOp = Math.random() * 0.4 + 0.1;
    p.style.cssText = `
      width:${size}px; height:${size}px;
      background:${color}; left:${Math.random()*100}%;
      --dur:${dur}s; --delay:${delay}s;
      --drift:${drift}px; --max-op:${maxOp};
      box-shadow: 0 0 ${size*3}px ${color};
    `;
    container.appendChild(p);
  }
}

// ========== RIPPLE ==========
function addRipple(e) {
  const btn = e.currentTarget;
  const rect = btn.getBoundingClientRect();
  const ripple = document.createElement('div');
  const size = Math.max(rect.width, rect.height);
  ripple.className = 'ripple';
  ripple.style.cssText = `
    width:${size}px; height:${size}px;
    left:${e.clientX-rect.left-size/2}px;
    top:${e.clientY-rect.top-size/2}px;
  `;
  btn.appendChild(ripple);
  setTimeout(() => ripple.remove(), 700);
}
document.querySelectorAll('.btn').forEach(btn => {
  btn.classList.add('ripple-container');
  btn.addEventListener('click', addRipple);
});

// ========== TOAST ==========
function toast(msg, type='info', duration=3500) {
  const icons = { success:'fa-check-circle', error:'fa-circle-xmark', info:'fa-circle-info', warning:'fa-triangle-exclamation' };
  const container = document.getElementById('toast-container');
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `<i class="fa ${icons[type]||icons.info}"></i><span>${msg}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = 'toastOut 0.3s ease forwards';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ========== SIDEBAR TOGGLE ==========
function toggleSidebar() {
  document.getElementById('sidebar')?.classList.toggle('open');
}

// ========== SIDEBAR CLOSE ON OUTSIDE CLICK ==========
document.addEventListener('click', e => {
  const sidebar = document.getElementById('sidebar');
  if (sidebar?.classList.contains('open') && !sidebar.contains(e.target) && !e.target.closest('.sidebar-toggle')) {
    sidebar.classList.remove('open');
  }
});

// ========== KEYBOARD SHORTCUTS ==========
document.addEventListener('keydown', e => {
  const tag = e.target.tagName;
  const isEditable = e.target.isContentEditable;
  const onCompose = window.location.pathname.startsWith('/compose');
  // Ne pas déclencher les raccourcis dans les champs de saisie ou sur /compose
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || isEditable || onCompose) return;
  if (e.key === 'n' || e.key === 'N') window.location.href = '/compose';
  if (e.key === 'Escape') {
    const path = window.location.pathname;
    if (path !== '/inbox') window.location.href = '/inbox';
  }
});

// ========== UNREAD BADGE ==========
async function loadUnreadBadge() {
  try {
    const res = await fetch('/api/stats');
    if (!res.ok) return;
    const data = await res.json();
    const badge = document.getElementById('unread-badge');
    if (badge && data.unseen > 0) {
      badge.textContent = data.unseen > 99 ? '99+' : data.unseen;
      badge.style.display = 'inline-flex';
    }
  } catch {}
}

// ========== FOLDERS SIDEBAR ==========
async function loadFolders() {
  try {
    const res = await fetch('/api/folders');
    if (!res.ok) return;
    const data = await res.json();
    const container = document.getElementById('folders-list');
    if (!container) return;
    const current = new URLSearchParams(window.location.search).get('folder') || 'INBOX';
    const skip = ['INBOX'];
    const extras = (data.folders || []).filter(f => !skip.includes(f.toUpperCase()));
    if (!extras.length) return;
    container.innerHTML = extras.map(f =>
      `<a href="/inbox?folder=${encodeURIComponent(f)}" class="nav-item ${f===current?'active':""}">
        <i class="fa fa-folder"></i><span>${f}</span>
      </a>`
    ).join('');
  } catch {}
}

// ========== COUNT UP ANIMATION ==========
function animateCountUp(el) {
  const target = parseInt(el.textContent) || 0;
  const duration = 1000;
  const start = performance.now();
  el.textContent = '0';
  function update(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.floor(eased * target);
    if (progress < 1) requestAnimationFrame(update);
    else el.textContent = target;
  }
  requestAnimationFrame(update);
}
document.querySelectorAll('.stat-value').forEach(el => {
  const observer = new IntersectionObserver(entries => {
    entries.forEach(e => { if (e.isIntersecting) { animateCountUp(el); observer.disconnect(); } });
  });
  observer.observe(el);
});

// ========== INIT ==========
document.addEventListener('DOMContentLoaded', () => {
  initParticles();
  loadUnreadBadge();
  loadFolders();
  document.querySelectorAll('.btn').forEach(btn => {
    btn.classList.add('ripple-container');
    btn.addEventListener('click', addRipple);
  });
});
