/* serveircMail - Main JS */

// ============================================================
// PARTICLES
// ============================================================
(function initParticles() {
  const canvas = document.createElement('canvas');
  canvas.id = 'particles-canvas';
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  let W, H, particles = [];

  function resize() {
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }
  resize();
  window.addEventListener('resize', resize);

  const COLORS = ['rgba(108,99,255,', 'rgba(62,198,224,', 'rgba(255,101,132,', 'rgba(74,222,128,'];

  class Particle {
    constructor() { this.reset(); }
    reset() {
      this.x = Math.random() * W;
      this.y = Math.random() * H;
      this.size = Math.random() * 2 + 0.5;
      this.speedX = (Math.random() - 0.5) * 0.4;
      this.speedY = (Math.random() - 0.5) * 0.4;
      this.color = COLORS[Math.floor(Math.random() * COLORS.length)];
      this.alpha = Math.random() * 0.5 + 0.1;
      this.targetAlpha = this.alpha;
      this.life = 0;
      this.maxLife = 200 + Math.random() * 400;
    }
    update() {
      this.x += this.speedX;
      this.y += this.speedY;
      this.life++;
      if (this.life > this.maxLife || this.x < 0 || this.x > W || this.y < 0 || this.y > H) this.reset();
    }
    draw() {
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.size, 0, Math.PI * 2);
      ctx.fillStyle = this.color + this.alpha + ')';
      ctx.fill();
    }
  }

  for (let i = 0; i < 80; i++) particles.push(new Particle());

  function drawConnections() {
    for (let i = 0; i < particles.length; i++) {
      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < 100) {
          ctx.beginPath();
          ctx.strokeStyle = 'rgba(108,99,255,' + (0.08 * (1 - dist / 100)) + ')';
          ctx.lineWidth = 0.5;
          ctx.moveTo(particles[i].x, particles[i].y);
          ctx.lineTo(particles[j].x, particles[j].y);
          ctx.stroke();
        }
      }
    }
  }

  function animate() {
    ctx.clearRect(0, 0, W, H);
    particles.forEach(p => { p.update(); p.draw(); });
    drawConnections();
    requestAnimationFrame(animate);
  }
  animate();
})();

// ============================================================
// ORBS
// ============================================================
['orb-1','orb-2','orb-3'].forEach(cls => {
  const el = document.createElement('div');
  el.className = `orb ${cls}`;
  document.body.prepend(el);
});

// ============================================================
// RIPPLE EFFECT
// ============================================================
document.addEventListener('click', function(e) {
  const btn = e.target.closest('.btn, .nav-item');
  if (!btn) return;
  const ripple = document.createElement('span');
  ripple.className = 'ripple';
  const rect = btn.getBoundingClientRect();
  const size = Math.max(rect.width, rect.height);
  ripple.style.width = ripple.style.height = size + 'px';
  ripple.style.left = (e.clientX - rect.left - size/2) + 'px';
  ripple.style.top = (e.clientY - rect.top - size/2) + 'px';
  btn.classList.add('ripple-container');
  btn.appendChild(ripple);
  setTimeout(() => ripple.remove(), 600);
});

// ============================================================
// TOAST
// ============================================================
window.toast = function(msg, type='info', duration=3500) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }
  const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icons[type]||'ℹ️'}</span><span>${msg}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    setTimeout(() => el.remove(), 300);
  }, duration);
  return el;
};

// ============================================================
// COUNT-UP ANIMATION
// ============================================================
function animateCountUp(el) {
  const target = parseInt(el.textContent.replace(/[^0-9]/g,''), 10);
  if (isNaN(target)) return;
  let current = 0;
  const duration = 1000;
  const step = target / (duration / 16);
  const timer = setInterval(() => {
    current = Math.min(current + step, target);
    el.textContent = Math.floor(current);
    if (current >= target) { el.textContent = target; clearInterval(timer); }
  }, 16);
}

document.querySelectorAll('.stat-value').forEach(el => {
  const observer = new IntersectionObserver(entries => {
    if (entries[0].isIntersecting) { animateCountUp(el); observer.disconnect(); }
  });
  observer.observe(el);
});

// ============================================================
// MODAL
// ============================================================
window.openModal = function(id) {
  const m = document.getElementById(id);
  if (m) { m.style.display = 'flex'; document.body.style.overflow = 'hidden'; }
};
window.closeModal = function(id) {
  const m = document.getElementById(id);
  if (m) { m.style.display = 'none'; document.body.style.overflow = ''; }
};
document.addEventListener('click', e => {
  if (e.target.classList.contains('modal-overlay')) {
    e.target.style.display = 'none';
    document.body.style.overflow = '';
  }
});

// ============================================================
// KEYBOARD SHORTCUTS
// ============================================================
document.addEventListener('keydown', e => {
  if (e.target.matches('input, textarea, select')) return;
  if (e.key === 'n' || e.key === 'N') {
    const composeLink = document.querySelector('a[href="/compose"]');
    if (composeLink) composeLink.click();
  }
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay').forEach(m => { m.style.display = 'none'; });
    document.body.style.overflow = '';
  }
  if (e.key === 'g' && e.shiftKey) {
    window.location.href = '/inbox';
  }
});

// ============================================================
// PAGE TRANSITIONS
// ============================================================
document.querySelectorAll('a:not([target="_blank"]):not([href^="#"]):not([href^="javascript"])').forEach(a => {
  a.addEventListener('click', e => {
    if (e.ctrlKey || e.metaKey || e.shiftKey) return;
    const main = document.querySelector('.page-content, .auth-page');
    if (main) {
      main.style.opacity = '0';
      main.style.transform = 'translateY(8px)';
      main.style.transition = 'all 0.2s ease';
    }
  });
});

const mainEl = document.querySelector('.page-content');
if (mainEl) mainEl.classList.add('page-enter');

// ============================================================
// SIDEBAR TOGGLE (MOBILE)
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
  const toggleBtn = document.getElementById('sidebar-toggle');
  const sidebar = document.querySelector('.sidebar');
  if (toggleBtn && sidebar) {
    toggleBtn.addEventListener('click', () => sidebar.classList.toggle('open'));
  }

  // Active nav item
  document.querySelectorAll('.nav-item').forEach(item => {
    if (item.href && window.location.pathname.startsWith(new URL(item.href, location.origin).pathname) && item.href !== '/') {
      item.classList.add('active');
    }
  });

  // Auto-dismiss flash messages
  document.querySelectorAll('.auth-error, .auth-success').forEach(el => {
    setTimeout(() => { el.style.opacity = '0'; el.style.transition = 'opacity 0.5s'; setTimeout(() => el.remove(), 500); }, 5000);
  });

  // Table search
  const searchInput = document.getElementById('table-search');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      const q = searchInput.value.toLowerCase();
      document.querySelectorAll('tbody tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  }
});

// ============================================================
// MAIL API HELPERS
// ============================================================
window.mailApi = {
  async getFolders() {
    const r = await fetch('/api/folders'); return r.json();
  },
  async getMails(folder='INBOX', page=1) {
    const r = await fetch(`/api/mails?folder=${encodeURIComponent(folder)}&page=${page}`); return r.json();
  },
  async getMail(uid, folder='INBOX') {
    const r = await fetch(`/api/mail/${uid}?folder=${encodeURIComponent(folder)}`); return r.json();
  },
  async sendMail(to, subject, body, html=false) {
    const r = await fetch('/api/send', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({to,subject,body,html}) });
    return r.json();
  },
  async deleteMail(uid, folder='INBOX') {
    const r = await fetch(`/api/mail/${uid}/delete?folder=${encodeURIComponent(folder)}`, {method:'POST'});
    return r.json();
  },
  async markRead(uid, folder='INBOX') {
    const r = await fetch(`/api/mail/${uid}/read?folder=${encodeURIComponent(folder)}`, {method:'POST'});
    return r.json();
  }
};
