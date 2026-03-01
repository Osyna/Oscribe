const elements = {
    track: document.getElementById('carousel-track'),
    dot0: document.getElementById('dot-0'),
    dot1: document.getElementById('dot-1'),
    modelSelect: document.getElementById('model-select'),
    modelDesc: document.getElementById('model-desc'),
    toggleAutotype: document.getElementById('toggle-autotype'),
    toggleClipboard: document.getElementById('toggle-clipboard'),
    toggleLivetyping: document.getElementById('toggle-livetyping'),
    togglePunctuation: document.getElementById('toggle-punctuation'),
    timeoutDisplay: document.getElementById('timeout-display'),
    timeoutDecBtn: document.getElementById('timeout-dec-btn'),
    timeoutIncBtn: document.getElementById('timeout-inc-btn'),
    logoBtn: document.getElementById('logo-btn'),
    featuresNavBtn: document.getElementById('features-nav-btn')
};

function goToSlide(index) {
    if (!elements.track) return;
    elements.track.style.transform = `translateX(-${index * 100}%)`;
    if (index === 0) {
        if (elements.dot0) elements.dot0.className = "w-8 h-2 bg-brand-500 transition-all duration-300 outline-none";
        if (elements.dot1) elements.dot1.className = "w-2 h-2 bg-slate-300 hover:bg-slate-400 transition-all duration-300 outline-none";
    } else {
        if (elements.dot0) elements.dot0.className = "w-2 h-2 bg-slate-300 hover:bg-slate-400 transition-all duration-300 outline-none";
        if (elements.dot1) elements.dot1.className = "w-8 h-2 bg-brand-500 transition-all duration-300 outline-none";
    }
}

const modelDescriptions = {
    "tiny": "fastest",
    "base": "fast",
    "small": "balanced",
    "distil-small.en": "fast, English only",
    "medium": "accurate",
    "distil-medium.en": "balanced, English only",
    "large-v3": "most accurate",
    "distil-large-v2": "fast + accurate",
    "distil-large-v3": "fast + accurate",
    "large-v3-turbo": "fast + accurate"
};

function updateModelInfo() {
    if (!elements.modelSelect || !elements.modelDesc) return;
    elements.modelDesc.textContent = modelDescriptions[elements.modelSelect.value] || "";
}

function enableToggle(el) {
    if (!el) return;
    el.dataset.state = 'on';
    el.className = "w-8 h-4 sm:w-9 sm:h-5 bg-white flex items-center p-0.5 shadow-[inset_0_2px_4px_rgba(0,0,0,0.5)] cursor-pointer flex-shrink-0 transition-colors duration-200";
    if (el.firstElementChild) el.firstElementChild.className = "w-3 h-3 sm:w-4 sm:h-4 bg-gradient-to-b from-gray-100 to-gray-300 shadow-md transform translate-x-3.5 sm:translate-x-4 transition-transform duration-200";
}

function disableToggle(el) {
    if (!el) return;
    el.dataset.state = 'off';
    el.className = "w-8 h-4 sm:w-9 sm:h-5 bg-black/50 shadow-inner flex items-center p-0.5 border border-white/10 cursor-pointer flex-shrink-0 transition-colors duration-200";
    if (el.firstElementChild) el.firstElementChild.className = "w-3 h-3 sm:w-4 sm:h-4 bg-gradient-to-b from-slate-400 to-slate-500 shadow-sm transform translate-x-0 transition-transform duration-200";
}

function setToggle(type) {
    if (type === 'autotype') {
        enableToggle(elements.toggleAutotype);
        disableToggle(elements.toggleClipboard);
    } else if (type === 'clipboard') {
        enableToggle(elements.toggleClipboard);
        disableToggle(elements.toggleAutotype);
    }
}

function toggleStandalone(el) {
    if (!el) return;
    if (el.dataset.state === 'on') {
        disableToggle(el);
    } else {
        enableToggle(el);
    }
}

let currentTimeout = 3.0;
function updateTimeout(delta) {
    currentTimeout += delta;
    if (currentTimeout < 0.5) currentTimeout = 0.5;
    if (currentTimeout > 10.0) currentTimeout = 10.0;
    if (elements.timeoutDisplay) elements.timeoutDisplay.textContent = currentTimeout.toFixed(1) + 's';
}

if (elements.logoBtn) elements.logoBtn.addEventListener('click', () => goToSlide(0));
if (elements.featuresNavBtn) elements.featuresNavBtn.addEventListener('click', () => goToSlide(1));
if (elements.dot0) elements.dot0.addEventListener('click', () => goToSlide(0));
if (elements.dot1) elements.dot1.addEventListener('click', () => goToSlide(1));
if (elements.modelSelect) elements.modelSelect.addEventListener('change', updateModelInfo);
if (elements.toggleAutotype) elements.toggleAutotype.addEventListener('click', () => setToggle('autotype'));
if (elements.toggleClipboard) elements.toggleClipboard.addEventListener('click', () => setToggle('clipboard'));
if (elements.toggleLivetyping) elements.toggleLivetyping.addEventListener('click', () => toggleStandalone(elements.toggleLivetyping));
if (elements.togglePunctuation) elements.togglePunctuation.addEventListener('click', () => toggleStandalone(elements.togglePunctuation));
if (elements.timeoutDecBtn) elements.timeoutDecBtn.addEventListener('click', () => updateTimeout(-0.5));
if (elements.timeoutIncBtn) elements.timeoutIncBtn.addEventListener('click', () => updateTimeout(0.5));
