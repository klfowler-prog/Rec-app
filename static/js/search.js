const searchInput = document.getElementById('search-input');
const typeFilter = document.getElementById('type-filter');
const resultsGrid = document.getElementById('search-results');
const loadingEl = document.getElementById('search-loading');
const emptyEl = document.getElementById('search-empty');
const initialEl = document.getElementById('search-initial');

let debounceTimer = null;
let profileMap = {};  // key: title.toLowerCase() -> entry

// Preload profile for cross-referencing
async function loadProfileMap() {
    try {
        const resp = await fetch('/api/profile/');
        if (!resp.ok) return;
        const entries = await resp.json();
        if (!Array.isArray(entries)) return;
        profileMap = {};
        for (const e of entries) {
            if (e && e.title) {
                profileMap[e.title.toLowerCase()] = e;
            }
        }
    } catch {}
}

searchInput.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(doSearch, 400);
});

typeFilter.addEventListener('change', () => {
    if (searchInput.value.trim()) doSearch();
});

async function doSearch() {
    const query = searchInput.value.trim();
    if (!query) {
        resultsGrid.innerHTML = '';
        emptyEl.classList.add('hidden');
        initialEl.classList.remove('hidden');
        return;
    }

    initialEl.classList.add('hidden');
    emptyEl.classList.add('hidden');
    loadingEl.classList.remove('hidden');
    resultsGrid.innerHTML = '';

    const mediaType = typeFilter.value;
    const params = new URLSearchParams({ q: query });
    if (mediaType) params.set('media_type', mediaType);

    try {
        const resp = await fetch(`/api/media/search?${params}`);
        const results = await resp.json();

        loadingEl.classList.add('hidden');

        if (results.length === 0) {
            emptyEl.classList.remove('hidden');
            return;
        }

        resultsGrid.innerHTML = results.map(item => mediaCard(item)).join('');
    } catch (err) {
        loadingEl.classList.add('hidden');
        resultsGrid.innerHTML = `<p class="col-span-full text-center text-txt-muted py-8">Something went wrong. Please try again.</p>`;
    }
}

function mediaCard(item) {
    const typeColors = {
        movie: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
        tv: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
        book: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
        podcast: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400',
    };

    const fit = item.media_type === 'podcast' ? 'poster-contain' : 'poster-cover';
    const safeTitle = item.title || 'Untitled';
    const firstChar = safeTitle[0] || '?';
    const image = item.image_url
        ? `<div class="poster-frame"><img src="${item.image_url}" alt="${escapeHtml(safeTitle)}" class="${fit}" loading="lazy"></div>`
        : `<div class="poster-frame"><div class="poster-fallback bg-sage/10"><span class="text-sage text-3xl">${escapeHtml(firstChar)}</span></div></div>`;

    const year = item.year ? `<span class="text-xs text-txt-muted">${item.year}</span>` : '';
    const badgeClass = typeColors[item.media_type] || typeColors.movie;
    const detailLink = `/media/${item.media_type}/${item.external_id}?source=${item.source}`;

    // Check if already in profile
    const profileEntry = profileMap[safeTitle.toLowerCase()];
    let actionArea;
    let cardStyle = '';

    if (profileEntry) {
        if (profileEntry.rating) {
            const rc = ratingTextColor(profileEntry.rating);
            actionArea = `<span class="text-xs font-semibold ${rc}">${profileEntry.rating}/5 ✓</span>`;
        } else if (profileEntry.status === 'consumed') {
            actionArea = `<span class="text-xs text-txt-muted">✓ Done</span>`;
        } else if (profileEntry.status === 'consuming') {
            actionArea = `<span class="text-xs text-coral">● Now</span>`;
        } else if (profileEntry.status === 'want_to_consume') {
            actionArea = `<span class="text-xs text-sage">✓ Later</span>`;
        } else {
            actionArea = `<span class="text-xs text-txt-muted">✓ In profile</span>`;
        }
        cardStyle = 'opacity: 0.7;';
    } else {
        actionArea = buildActionBar(item, 'sm');
    }

    return `
        <div class="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden shadow-sm transition-base card-hover" data-rec-card style="${cardStyle}">
            <a href="${detailLink}" class="block">${image}</a>
            <div class="p-2">
                <a href="${detailLink}" class="block hover:text-sage transition-base">
                    <p class="text-[11px] font-semibold leading-tight line-clamp-2 mb-1">${escapeHtml(safeTitle)}</p>
                </a>
                <div class="flex items-center gap-1.5 mb-1">
                    <span class="px-1.5 py-0.5 ${badgeClass} text-[10px] font-medium rounded capitalize">${item.media_type}</span>
                    ${year}
                </div>
                ${item.creator ? `<p class="text-[10px] text-txt-muted mb-2 truncate">${escapeHtml(item.creator)}</p>` : '<div class="mb-1"></div>'}
                <div class="quick-add-area">${actionArea}</div>
            </div>
        </div>
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initial load
loadProfileMap();
