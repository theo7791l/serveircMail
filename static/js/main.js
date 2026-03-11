// ====== PARTICLES ======
function initParticles() {
    const container = document.getElementById('particles');
    if (!container) return;
    const count = 30;
    for (let i = 0; i < count; i++) {
        const p = document.createElement('div');
        const size = Math.random() * 3 + 1;
        const x = Math.random() * 100;
        const delay = Math.random() * 15;
        const duration = Math.random() * 15 + 10;
        const opacity = Math.random() * 0.4 + 0.1;
        p.style.cssText = `
            position: absolute;
            left: ${x}%;
            bottom: -10px;
            width: ${size}px;
            height: ${size}px;
            border-radius: 50%;
            background: ${Math.random() > 0.5 ? 'rgba(108,99,255,' : 'rgba(62,198,224,'}${opacity});
            animation: particleFloat ${duration}s ${delay}s linear infinite;
            pointer-events: none;
        `;
        container.appendChild(p);
    }
}

// ====== ANIMATE ON LOAD ======
function initAnimations() {
    const cards = document.querySelectorAll('.login-card, .compose-card, .read-card');
    cards.forEach(el => {
        requestAnimationFrame(() => {
            setTimeout(() => el.classList.add('in'), 50);
        });
    });
}

// ====== RIPPLE EFFECT ======
function initRipple() {
    document.querySelectorAll('.btn-login, .btn-compose, .btn-send').forEach(btn => {
        btn.addEventListener('click', function(e) {
            const ripple = document.createElement('span');
            const rect = this.getBoundingClientRect();
            ripple.style.cssText = `
                position: absolute;
                left: ${e.clientX - rect.left}px;
                top: ${e.clientY - rect.top}px;
                width: 10px;
                height: 10px;
                background: rgba(255,255,255,0.3);
                border-radius: 50%;
                transform: translate(-50%, -50%) scale(0);
                animation: ripple 0.6s ease-out forwards;
                pointer-events: none;
            `;
            this.style.position = 'relative';
            this.appendChild(ripple);
            setTimeout(() => ripple.remove(), 700);
        });
    });
}

// ====== SIDEBAR ACTIVE ======
function initSidebarActive() {
    const path = window.location.pathname;
    document.querySelectorAll('.nav-item').forEach(link => {
        if (link.getAttribute('href') && path.startsWith(link.getAttribute('href'))) {
            link.classList.add('active');
        }
    });
}

// ====== TOAST NOTIFICATIONS ======
window.showToast = function(msg, type = 'info') {
    const toast = document.createElement('div');
    const colors = { success: '#4ade80', error: '#FF6584', info: '#6C63FF', warn: '#fbbf24' };
    toast.style.cssText = `
        position: fixed;
        bottom: 24px;
        right: 24px;
        padding: 12px 20px;
        background: #0f1223;
        border: 1px solid ${colors[type] || colors.info};
        border-radius: 12px;
        color: ${colors[type] || colors.info};
        font-size: 13px;
        font-weight: 500;
        z-index: 9999;
        box-shadow: 0 8px 30px rgba(0,0,0,0.4);
        animation: fadeInUp 0.4s ease;
        display: flex;
        align-items: center;
        gap: 8px;
        max-width: 320px;
    `;
    toast.textContent = msg;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'fadeIn 0.3s ease reverse';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
};

// ====== KEYBOARD SHORTCUTS ======
document.addEventListener('keydown', (e) => {
    if (e.key === 'n' && !e.ctrlKey && !e.metaKey && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
        if (window.location.pathname !== '/compose') window.location = '/compose';
    }
    if (e.key === 'Escape') {
        if (window.location.pathname !== '/inbox') window.location = '/inbox';
    }
});

// ====== INIT ======
document.addEventListener('DOMContentLoaded', () => {
    initParticles();
    initAnimations();
    initRipple();
    initSidebarActive();
});
