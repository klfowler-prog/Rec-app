const searchInput = document.getElementById('search-input');
const typeFilter = document.getElementById('type-filter');
const resultsGrid = document.getElementById('search-results');
const loadingEl = document.getElementById('search-loading');
const emptyEl = document.getElementById('search-empty');
const initialEl = document.getElementById('search-initial');

let debounceTimer = null;

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

    const cardAspect = item.media_type === 'podcast' ? 'aspect-square' : 'aspect-[2/3]';
    const safeTitle = item.title || 'Untitled';
    const firstChar = safeTitle[0] || '?';
    const image = item.image_url
        ? `<img src="${item.image_url}" alt="${escapeHtml(safeTitle)}" class="w-full ${cardAspect} object-cover" loading="lazy">`
        : `<div class="w-full ${cardAspect} bg-sage/10 flex items-center justify-center"><span class="text-sage text-3xl">${escapeHtml(firstChar)}</span></div>`;

    const year = item.year ? `<span class="text-xs text-txt-muted">${item.year}</span>` : '';
    const badgeClass = typeColors[item.media_type] || typeColors.movie;

    return `
        <a href="/media/${item.media_type}/${item.external_id}?source=${item.source}" class="group">
            <div class="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark overflow-hidden transition-base card-hover">
                ${image}
                <div class="p-3">
                    <p class="text-sm font-medium truncate mb-1">${escapeHtml(safeTitle)}</p>
                    <div class="flex items-center gap-1.5">
                        <span class="px-1.5 py-0.5 ${badgeClass} text-[10px] font-medium rounded capitalize">${item.media_type}</span>
                        ${year}
                    </div>
                    ${item.creator ? `<p class="text-xs text-txt-muted mt-1 truncate">${escapeHtml(item.creator)}</p>` : ''}
                </div>
            </div>
        </a>
    `;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
