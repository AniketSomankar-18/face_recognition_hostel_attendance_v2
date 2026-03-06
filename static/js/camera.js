/**
 * Camera and Face Recognition Utilities
 * Hostel Attendance System
 */

// ─── Camera Utilities ─────────────────────────────────────────────────────────

const CameraUtils = {
    stream: null,

    async start(videoElement, constraints = {}) {
        const defaultConstraints = {
            video: {
                width: { ideal: 640 },
                height: { ideal: 480 },
                facingMode: 'user'
            }
        };
        try {
            this.stream = await navigator.mediaDevices.getUserMedia(
                Object.assign(defaultConstraints, constraints)
            );
            if (videoElement) {
                videoElement.srcObject = this.stream;
            }
            return { success: true, stream: this.stream };
        } catch (err) {
            console.error('Camera error:', err);
            return { success: false, error: err.message };
        }
    },

    stop() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
        }
    },

    captureFrame(videoElement, quality = 0.9) {
        const canvas = document.createElement('canvas');
        canvas.width = videoElement.videoWidth || 640;
        canvas.height = videoElement.videoHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(videoElement, 0, 0);
        return canvas.toDataURL('image/jpeg', quality);
    },

    isAvailable() {
        return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
    }
};


// ─── API Calls ────────────────────────────────────────────────────────────────

const API = {
    async post(url, data) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return response.json();
    },

    async get(url) {
        const response = await fetch(url);
        return response.json();
    },

    async trainModel() {
        return this.post('/api/train', {});
    },

    async getSummary() {
        return this.get('/api/summary');
    },

    async markAbsentAll() {
        return this.post('/api/mark_absent_all', {});
    }
};


// ─── Notification Helper ──────────────────────────────────────────────────────

const Notify = {
    show(message, type = 'info', duration = 4000) {
        const container = document.querySelector('.flash-container') ||
            (() => {
                const el = document.createElement('div');
                el.className = 'flash-container';
                document.querySelector('.page-content')?.prepend(el);
                return el;
            })();

        const icons = {
            success: 'fa-check-circle',
            danger: 'fa-exclamation-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
        };

        const alert = document.createElement('div');
        alert.className = `alert alert-${type}`;
        alert.innerHTML = `
            <i class="fas ${icons[type] || icons.info}"></i>
            ${message}
            <button class="alert-close" onclick="this.parentElement.remove()">×</button>
        `;
        container.appendChild(alert);

        if (duration > 0) {
            setTimeout(() => {
                alert.style.transition = 'opacity 0.5s';
                alert.style.opacity = '0';
                setTimeout(() => alert.remove(), 500);
            }, duration);
        }
    },

    success(msg) { this.show(msg, 'success'); },
    error(msg) { this.show(msg, 'danger'); },
    warning(msg) { this.show(msg, 'warning'); },
    info(msg) { this.show(msg, 'info'); }
};


// ─── Loading Indicator ────────────────────────────────────────────────────────

const Loading = {
    show(buttonEl, text = 'Processing...') {
        if (buttonEl) {
            buttonEl._originalContent = buttonEl.innerHTML;
            buttonEl.disabled = true;
            buttonEl.innerHTML = `<i class="fas fa-circle-notch fa-spin"></i> ${text}`;
        }
    },
    hide(buttonEl) {
        if (buttonEl && buttonEl._originalContent) {
            buttonEl.disabled = false;
            buttonEl.innerHTML = buttonEl._originalContent;
        }
    }
};


// ─── Train Model Button ───────────────────────────────────────────────────────

async function trainModelAjax(buttonEl) {
    if (!confirm('Train face recognition model? This may take a few minutes.')) return;
    Loading.show(buttonEl, 'Training...');
    try {
        const data = await API.trainModel();
        if (data.success) {
            Notify.success(`✓ ${data.message}`);
        } else {
            Notify.error(`✗ ${data.message}`);
        }
    } catch (err) {
        Notify.error('Training failed: ' + err.message);
    }
    Loading.hide(buttonEl);
}


// ─── Dashboard Auto Refresh ───────────────────────────────────────────────────

function initDashboardRefresh() {
    const summaryCards = document.querySelectorAll('.stat-value');
    if (!summaryCards.length) return;

    setInterval(async () => {
        try {
            const data = await API.getSummary();
            // You can update stat cards here if needed
        } catch (e) {
            // Silently fail
        }
    }, 60000);
}


// ─── Confirm Delete ───────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Add confirmation to all danger forms
    document.querySelectorAll('form[data-confirm]').forEach(form => {
        form.addEventListener('submit', e => {
            if (!confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });

    initDashboardRefresh();
});


// ─── Keyboard Shortcuts ───────────────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
    // Alt + A => Attendance
    if (e.altKey && e.key === 'a') {
        window.location.href = '/attendance';
    }
    // Alt + S => Students
    if (e.altKey && e.key === 's') {
        window.location.href = '/students';
    }
    // Alt + D => Dashboard
    if (e.altKey && e.key === 'd') {
        window.location.href = '/dashboard';
    }
});
