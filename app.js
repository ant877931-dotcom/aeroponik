import { initializeApp } from "https://www.gstatic.com/firebasejs/12.16.0/firebase-app.js";
import { getDatabase, ref, onValue, set } from "https://www.gstatic.com/firebasejs/12.16.0/firebase-database.js";

// Firebase Configuration
const firebaseConfig = {
    apiKey: "AIzaSyBmBj2VzJzGYE9gobVU3-oRu6Y4ki_Amrw",
    authDomain: "aeroponic-2712d.firebaseapp.com",
    databaseURL: "https://aeroponic-2712d-default-rtdb.firebaseio.com",
    projectId: "aeroponic-2712d",
    storageBucket: "aeroponic-2712d.firebasestorage.app",
    messagingSenderId: "840434718049",
    appId: "1:840434718049:web:21d6a666e4f6d693e3e120"
};

// Initialize Firebase
const app = initializeApp(firebaseConfig);
const db = getDatabase(app);

// --- Chart.js Setup for Combined Chart ---
const maxDataPoints = 15;

const commonOptions = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: {
        mode: 'index',
        intersect: false,
    },
    plugins: {
        legend: { display: false },
        tooltip: {
            backgroundColor: 'rgba(255, 255, 255, 0.95)',
            titleColor: '#1f2937',
            bodyColor: '#4b5563',
            borderColor: '#e5e7eb',
            borderWidth: 1,
            padding: 12,
            boxPadding: 6,
            usePointStyle: true,
            titleFont: { family: 'Inter', weight: 'bold' },
            bodyFont: { family: 'Inter', weight: '500' }
        }
    },
    scales: {
        x: { display: true, grid: { display: false }, ticks: { font: { family: 'Inter' }, color: '#9ca3af', maxTicksLimit: 5 } },
        y: { type: 'linear', display: true, position: 'left', grid: { color: '#f3f4f6', drawBorder: false }, ticks: { font: { family: 'Inter', weight: '500' }, color: '#6b7280' } },
        y1: { type: 'linear', display: true, position: 'right', grid: { drawOnChartArea: false }, ticks: { font: { family: 'Inter', weight: '500' }, color: '#6b7280' } }
    }
};

const ctxMain = document.getElementById('mainChart').getContext('2d');
const mainChart = new Chart(ctxMain, {
    type: 'line',
    data: {
        labels: [],
        datasets: [
            { label: 'CO₂ / TDS (ppm)', data: [], borderColor: '#22c55e', backgroundColor: 'rgba(34, 197, 94, 0.1)', borderWidth: 2, tension: 0.4, pointRadius: 0, yAxisID: 'y1' },
            { label: 'pH', data: [], borderColor: '#c084fc', backgroundColor: 'rgba(192, 132, 252, 0.1)', borderWidth: 2, tension: 0.4, pointRadius: 0, yAxisID: 'y' }
        ]
    },
    options: commonOptions
});

// --- Date Picker Logic ---
const dateFilter = document.getElementById('chart-date-filter');
const noDataMessage = document.getElementById('no-data-message');
const chartCanvas = document.getElementById('mainChart');

if (dateFilter) {
    // Set today's date as default
    const today = new Date().toISOString().split('T')[0];
    dateFilter.value = today;

    dateFilter.addEventListener('change', (e) => {
        const selectedDate = e.target.value;
        if (selectedDate !== today) {
            // Show "no data" overlay if not today
            if (noDataMessage) noDataMessage.classList.remove('hidden');
            if (chartCanvas) chartCanvas.style.opacity = '0.1';
        } else {
            // Hide overlay if today
            if (noDataMessage) noDataMessage.classList.add('hidden');
            if (chartCanvas) chartCanvas.style.opacity = '1';
        }
    });
}

// Function to update the combined Chart dynamically
function updateCharts(tds, ph) {
    if (tds === null && ph === null) return;
    
    const now = new Date();
    const timeLabel = `${now.getHours()}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;
    
    if (mainChart) {
        mainChart.data.labels.push(timeLabel);
        mainChart.data.datasets[0].data.push(tds !== null ? tds : null);
        mainChart.data.datasets[1].data.push(ph !== null ? ph : null);
        
        if (mainChart.data.labels.length > maxDataPoints) {
            mainChart.data.labels.shift();
            mainChart.data.datasets.forEach(dataset => dataset.data.shift());
        }
        mainChart.update();
    }
    
    updateTable(timeLabel, ph, tds);
}

// Function to update Laporan Table with real data
let lastTableUpdateTime = 0;
function updateTable(timeStr, ph, tds) {
    const tbody = document.getElementById('table-body');
    if (!tbody) return; // Only run if on laporan.html
    
    // Throttle table updates to once every 5 seconds to avoid spamming the UI
    const now = Date.now();
    if (now - lastTableUpdateTime < 5000) return;
    lastTableUpdateTime = now;

    // Get current AI Status
    const healthEl = document.getElementById('plant-health');
    let kondisi = "Belum ada deteksi";
    if (healthEl && healthEl.innerText !== "Belum ada deteksi dari AI") {
        kondisi = healthEl.innerText;
    }

    const tr = document.createElement('tr');
    tr.className = "hover:bg-blue-50/30 transition-colors";
    
    const statusLower = kondisi.toLowerCase();
    let statusClass = "bg-gray-50 text-gray-600 border border-gray-200";
    if(statusLower.includes('sehat') || statusLower.includes('normal')) {
        statusClass = 'bg-secondary-50 text-secondary-600 border border-secondary-100';
    } else if(statusLower.includes('defisiensi') || statusLower.includes('sakit') || statusLower.includes('bahaya')) {
        statusClass = 'bg-red-50 text-red-600 border border-red-100';
    } else if(statusLower !== "belum ada deteksi") {
        statusClass = 'bg-yellow-50 text-yellow-600 border border-yellow-100';
    }

    tr.innerHTML = `
        <td class="py-4 px-5 font-bold text-gray-800">${timeStr}</td>
        <td class="py-4 px-5 text-purple-500 font-semibold">${ph !== null ? ph : '-'}</td>
        <td class="py-4 px-5 text-secondary-600 font-semibold">${tds !== null ? tds : '-'}</td>
        <td class="py-4 px-5">
            <span class="px-2 py-1 rounded text-xs font-bold ${statusClass}">
                ${kondisi}
            </span>
        </td>
    `;
    
    // Prepend so newest is at the top
    tbody.prepend(tr);
    
    // Keep max 100 rows in the DOM so it doesn't crash the browser
    if (tbody.children.length > 100) {
        tbody.removeChild(tbody.lastChild);
    }
}

// Function to add Notification dynamically
function addNotification(title, message, type) {
    const container = document.getElementById('notifikasi-container');
    if (!container) return; // Only if on notifikasi.html

    const emptyMsg = container.querySelector('.italic');
    if (emptyMsg) emptyMsg.remove();

    const now = new Date();
    const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`;
    
    let icon = "fa-bell";
    let colorClass = "bg-gray-100 text-gray-500";
    let bgHover = "hover:bg-gray-50";

    if (type === 'critical') {
        icon = "fa-temperature-arrow-up";
        colorClass = "bg-red-100 text-red-500";
        bgHover = "bg-red-50/30 hover:bg-red-50";
    } else if (type === 'info') {
        icon = "fa-water";
        colorClass = "bg-blue-100 text-blue-500";
    } else if (type === 'ai') {
        icon = "fa-seedling";
        colorClass = "bg-yellow-100 text-yellow-600";
    } else if (type === 'success') {
        icon = "fa-flask";
        colorClass = "bg-secondary-100 text-secondary-500";
    }

    const div = document.createElement('div');
    div.className = `p-5 flex gap-4 items-start transition-colors cursor-pointer ${bgHover}`;
    div.innerHTML = `
        <div class="w-10 h-10 rounded-full ${colorClass} flex items-center justify-center shrink-0 mt-0.5">
            <i class="fa-solid ${icon} text-lg"></i>
        </div>
        <div class="flex-1">
            <div class="flex justify-between items-start mb-1">
                <h3 class="font-bold text-gray-800">${title}</h3>
                <span class="text-xs font-bold ${type === 'critical' ? 'text-red-500' : 'text-gray-400'}">${timeStr}</span>
            </div>
            <p class="text-sm text-gray-600 leading-relaxed">${message}</p>
        </div>
        ${type === 'critical' ? '<div class="w-2 h-2 rounded-full bg-red-500 mt-2"></div>' : ''}
    `;

    container.prepend(div);
    
    // Keep max 20 notifications
    if (container.children.length > 20) {
        container.removeChild(container.lastChild);
    }
}

// --- Empty State & Data Logic ---
let currentTds = null;
let currentPh = null;

function handleSensorUI(val, prefix) {
    const dataEl = document.getElementById(`sensor-${prefix}-data`);
    const emptyEl = document.getElementById(`sensor-${prefix}-empty`);
    const valEl = document.getElementById(`sensor-${prefix}`);

    if (val === null || val === undefined) {
        if(dataEl) dataEl.classList.add('hidden');
        if(emptyEl) emptyEl.classList.remove('hidden');
    } else {
        if(dataEl) dataEl.classList.remove('hidden');
        if(emptyEl) emptyEl.classList.add('hidden');
        if (valEl) valEl.innerText = val;
    }
}

// --- Firebase Listeners: Sensor Metrics ---

onValue(ref(db, 'sensor/ph'), (snapshot) => {
    const val = snapshot.val();
    handleSensorUI(val, 'ph');
    currentPh = val;
    updateCharts(currentTds, currentPh);
});

onValue(ref(db, 'sensor/tds'), (snapshot) => {
    const val = snapshot.val();
    handleSensorUI(val, 'tds');
    handleSensorUI(val, 'co2'); // CO2 mapped to TDS
    currentTds = val;
    updateCharts(currentTds, currentPh);
});

onValue(ref(db, 'sensor/volume'), (snapshot) => {
    const val = snapshot.val();
    handleSensorUI(val, 'vol');
    if (val !== null && val !== undefined) {
        const percentage = Math.min(Math.max(val, 0), 100);
        const volBar = document.getElementById('vol-bar');
        if (volBar) volBar.style.width = `${percentage}%`;
    }
});


// --- Firebase Listeners: AI Camera ---

onValue(ref(db, 'kamera/url'), (snapshot) => {
    const val = snapshot.val();
    const feedImg = document.getElementById('camera-feed');
    const emptyText = document.getElementById('camera-feed-empty');
    if (!feedImg || !emptyText) return;
    
    if (val) {
        feedImg.src = val;
        feedImg.classList.remove('hidden');
        emptyText.classList.add('hidden');
    } else {
        feedImg.classList.add('hidden');
        emptyText.classList.remove('hidden');
    }
});

let lastHealth = null;
onValue(ref(db, 'kamera/status'), (snapshot) => {
    const val = snapshot.val();
    const healthEl = document.getElementById('plant-health');
    if (healthEl) {
        if (!val) {
            healthEl.innerText = "Belum ada deteksi dari AI";
            healthEl.className = 'bg-red-50 text-red-600 px-3 py-1 rounded-md text-[11px] font-bold border border-red-100 inline-block leading-tight';
        } else {
            healthEl.innerText = val;
            const statusLower = val.toLowerCase();
            if(statusLower.includes('sehat') || statusLower.includes('normal')) {
                healthEl.className = 'bg-secondary-50 text-secondary-600 px-3 py-1 rounded-md text-[11px] font-bold border border-secondary-100 inline-block leading-tight';
            } else if(statusLower.includes('defisiensi') || statusLower.includes('sakit') || statusLower.includes('bahaya')) {
                healthEl.className = 'bg-red-50 text-red-600 px-3 py-1 rounded-md text-[11px] font-bold border border-red-100 inline-block leading-tight';
            } else {
                healthEl.className = 'bg-yellow-50 text-yellow-600 px-3 py-1 rounded-md text-[11px] font-bold border border-yellow-100 inline-block leading-tight';
            }
        }
    }
    
    if (val && lastHealth !== val) {
        const statusLower = val.toLowerCase();
        if (statusLower.includes('defisiensi') || statusLower.includes('sakit') || statusLower.includes('bahaya')) {
            addNotification("Indikasi Masalah Kesehatan", `Kamera AI mendeteksi status: ${val}. Silakan periksa tanaman.`, "ai");
        } else if ((statusLower.includes('sehat') || statusLower.includes('normal')) && lastHealth) {
            addNotification("Kondisi Tanaman Membaik", `Status AI terbaru: ${val}.`, "success");
        }
    }
    lastHealth = val;
});

onValue(ref(db, 'kamera/akurasi'), (snapshot) => {
    const val = snapshot.val();
    const accEl = document.getElementById('model-accuracy');
    if (accEl) {
        if (val !== null && val !== undefined) {
            accEl.innerText = `${val}%`;
        } else {
            accEl.innerText = "-";
        }
    }
});


// --- Firebase Listeners & Controls: Actuators ---

const toggles = [
    { id: 'toggle-air', path: 'kontrol/pompaAir', name: 'Pompa Air' },
    { id: 'toggle-nutrisi', path: 'kontrol/pompaNutrisiA', name: 'Pompa Nutrisi A' },
    { id: 'toggle-misting', path: 'kontrol/pompaMisting', name: 'Pompa Misting' },
    { id: 'toggle-utama', path: 'kontrol/pompaUtama', name: 'Pompa Utama' }
];

let lastActuatorState = {};

toggles.forEach(t => {
    const el = document.getElementById(t.id);
    
    onValue(ref(db, t.path), (snapshot) => {
        const val = snapshot.val();
        if(val !== null && val !== undefined) {
            if (el) el.checked = Boolean(val);
            
            const isNowOn = Boolean(val);
            const wasOn = lastActuatorState[t.path];
            
            if (isNowOn && wasOn === false) {
                addNotification(`${t.name} Diaktifkan`, `${t.name} telah diaktifkan secara otomatis atau manual.`, "info");
            } else if (!isNowOn && wasOn === true) {
                addNotification(`${t.name} Dimatikan`, `${t.name} telah dimatikan.`, "info");
            }
            
            lastActuatorState[t.path] = isNowOn;
        }
    });

    el.addEventListener('change', (e) => {
        set(ref(db, t.path), e.target.checked)
            .catch((error) => console.error(`Error updating ${t.path}:`, error));
    });
});


// --- Connection Status Indicator ---
const connectedRef = ref(db, ".info/connected");
onValue(connectedRef, (snap) => {
    const indicator = document.getElementById('conn-indicator');
    const text = document.getElementById('conn-text');
    if (snap.val() === true) {
        indicator.innerHTML = `
          <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-secondary-400 opacity-75"></span>
          <span class="relative inline-flex rounded-full h-2 w-2 bg-secondary-500"></span>`;
        text.innerText = "Online";
        text.className = "text-[13px] font-bold text-secondary-600";
    } else {
        indicator.innerHTML = `<span class="relative inline-flex rounded-full h-2 w-2 bg-red-500"></span>`;
        text.innerText = "Menunggu Koneksi IoT...";
        text.className = "text-[13px] font-bold text-red-600";
    }
});


// --- Sidebar Active State Logic ---
const sidebarNav = document.getElementById('sidebar-nav');
if (sidebarNav) {
    const navItems = sidebarNav.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            const href = item.getAttribute('href');
            if (href && href.startsWith('#')) {
                e.preventDefault();
                if (href === '#') {
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                } else {
                    const target = document.querySelector(href);
                    if (target) {
                        target.scrollIntoView({ behavior: 'smooth' });
                    }
                }
            }
            
            navItems.forEach(nav => {
                nav.classList.remove('active', 'bg-secondary-50', 'text-secondary-600', 'font-bold');
                nav.classList.add('text-gray-500', 'hover:bg-gray-50', 'hover:text-gray-800', 'font-medium');
                const indicator = nav.querySelector('.absolute');
                if (indicator) indicator.remove();
            });

            item.classList.add('active', 'bg-secondary-50', 'text-secondary-600', 'font-bold');
            item.classList.remove('text-gray-500', 'hover:bg-gray-50', 'hover:text-gray-800', 'font-medium');
            
            if (!item.querySelector('.absolute')) {
                const indicator = document.createElement('div');
                indicator.className = 'absolute left-0 top-0 bottom-0 w-1 bg-secondary-500 rounded-r-md';
                item.prepend(indicator);
            }
        });
    });
}

// --- Sidebar Interaction Logic (Mobile) ---
const sidebar = document.getElementById('sidebar');
const sidebarOverlay = document.getElementById('sidebar-overlay');
const btnOpenSidebar = document.getElementById('btn-open-sidebar');
const btnCloseSidebar = document.getElementById('btn-close-sidebar');

function openSidebar() {
    sidebar.classList.remove('-translate-x-full');
    sidebarOverlay.classList.remove('hidden');
    setTimeout(() => {
        sidebarOverlay.classList.remove('opacity-0', 'pointer-events-none');
    }, 10);
}

function closeSidebar() {
    sidebar.classList.add('-translate-x-full');
    sidebarOverlay.classList.add('opacity-0', 'pointer-events-none');
    setTimeout(() => {
        sidebarOverlay.classList.add('hidden');
    }, 300);
}

if (btnOpenSidebar) btnOpenSidebar.addEventListener('click', openSidebar);
if (btnCloseSidebar) btnCloseSidebar.addEventListener('click', closeSidebar);
if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);
