const bulkInput = document.getElementById('bulk-input');
const bulkStatus = document.getElementById('bulk-status');
const searchBtn = document.getElementById('bulk-search-btn');
const stepInput = document.getElementById('step-input');
const stepLoading = document.getElementById('step-loading');
const stepReview = document.getElementById('step-review');
const stepDone = document.getElementById('step-done');
const matchList = document.getElementById('match-list');
const matchCount = document.getElementById('match-count');
const addAllBtn = document.getElementById('add-all-btn');
const backBtn = document.getElementById('back-btn');
const addMoreBtn = document.getElementById('add-more-btn');
const loadingProgress = document.getElementById('loading-progress');

let matchData = {};

searchBtn.addEventListener('click', doBulkSearch);

async function doBulkSearch() {
    const text = bulkInput.value.trim();
    if (!text) return;

    const titles = text.split('\n').map(t => t.trim()).filter(t => t.length > 0);
    if (titles.length === 0) return;

    stepInput.classList.add('hidden');
    stepLoading.classList.remove('hidden');
    loadingProgress.textContent = `Searching for ${titles.length} titles...`;

    try {
        const resp = await fetch('/api/media/bulk-search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ titles }),
        });
        matchData = await resp.json();

        stepLoading.classList.add('hidden');
        renderMatches(titles);
        stepReview.classList.remove('hidden');
    } catch (err) {
        stepLoading.classList.add('hidden');
        stepInput.classList.remove('hidden');
        alert('Search failed. Please try again.');
    }
}

function renderMatches(titles) {
    let matched = 0;
    const typeColors = {
        movie: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
        tv: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
        book: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
        podcast: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400',
    };

    matchList.innerHTML = titles.map(title => {
        const results = matchData[title] || [];
        if (results.length === 0) {
            return `
                <div class="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark p-4">
                    <div class="flex items-center gap-3">
                        <svg class="w-5 h-5 text-red-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M6 18L18 6M6 6l12 12"/></svg>
                        <span class="text-sm font-medium">${escapeHtml(title)}</span>
                        <span class="text-xs text-txt-muted">— no match found</span>
                    </div>
                </div>
            `;
        }

        matched++;
        const best = results[0];
        const alternatives = results.slice(1);
        const badgeClass = typeColors[best.media_type] || typeColors.movie;
        const itemId = `match-${encodeId(title)}`;

        return `
            <div class="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark p-4" id="${itemId}">
                <div class="flex items-start gap-4">
                    <input type="checkbox" checked class="match-checkbox mt-1 w-4 h-4 accent-sage-dark" data-title="${escapeAttr(title)}">
                    <div class="flex gap-3 flex-1 min-w-0">
                        ${best.image_url
                            ? `<img src="${best.image_url}" alt="" class="w-10 h-14 object-cover rounded flex-shrink-0">`
                            : `<div class="w-10 h-14 bg-sage/10 rounded flex items-center justify-center flex-shrink-0"><span class="text-sage text-xs">${escapeHtml(best.title[0])}</span></div>`
                        }
                        <div class="flex-1 min-w-0">
                            <div class="flex items-center gap-2 mb-0.5">
                                <span class="text-sm font-medium truncate">${escapeHtml(best.title)}</span>
                                <span class="px-1.5 py-0.5 ${badgeClass} text-[10px] font-medium rounded capitalize flex-shrink-0">${best.media_type}</span>
                                ${best.year ? `<span class="text-xs text-txt-muted flex-shrink-0">${best.year}</span>` : ''}
                            </div>
                            <p class="text-xs text-txt-muted">Searched: "${escapeHtml(title)}"${best.creator ? ` · ${escapeHtml(best.creator)}` : ''}</p>
                            ${alternatives.length > 0 ? `
                                <details class="mt-1">
                                    <summary class="text-xs text-sage cursor-pointer hover:underline">Other matches</summary>
                                    <div class="mt-1 space-y-1">
                                        ${alternatives.map((alt, i) => `
                                            <label class="flex items-center gap-2 text-xs text-txt-muted cursor-pointer hover:text-txt">
                                                <input type="radio" name="pick-${encodeId(title)}" value="${i + 1}" class="alt-pick accent-sage-dark" data-title="${escapeAttr(title)}">
                                                ${escapeHtml(alt.title)} (${alt.media_type}, ${alt.year || '?'})${alt.creator ? ` — ${escapeHtml(alt.creator)}` : ''}
                                            </label>
                                        `).join('')}
                                        <label class="flex items-center gap-2 text-xs text-txt-muted cursor-pointer hover:text-txt">
                                            <input type="radio" name="pick-${encodeId(title)}" value="0" checked class="alt-pick accent-sage-dark" data-title="${escapeAttr(title)}">
                                            ${escapeHtml(best.title)} (original match)
                                        </label>
                                    </div>
                                </details>
                            ` : ''}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    matchCount.textContent = `${matched} of ${titles.length}`;
}

addAllBtn.addEventListener('click', async () => {
    addAllBtn.disabled = true;
    addAllBtn.textContent = 'Adding...';

    const status = bulkStatus.value;
    let addedCount = 0;

    const checkboxes = document.querySelectorAll('.match-checkbox:checked');
    for (const cb of checkboxes) {
        const title = cb.dataset.title;
        const results = matchData[title] || [];
        if (results.length === 0) continue;

        // Check if an alternative was picked
        let pickIndex = 0;
        const altPick = document.querySelector(`input.alt-pick[data-title="${CSS.escape(title)}"]:checked`);
        if (altPick) pickIndex = parseInt(altPick.value);

        const item = results[pickIndex] || results[0];

        try {
            const resp = await fetch('/api/profile/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    external_id: item.external_id,
                    source: item.source,
                    title: item.title,
                    media_type: item.media_type,
                    image_url: item.image_url,
                    year: item.year,
                    creator: item.creator,
                    genres: item.genres ? item.genres.join(', ') : null,
                    description: item.description,
                    status: status,
                }),
            });
            if (resp.ok || resp.status === 409) addedCount++;
        } catch {}
    }

    stepReview.classList.add('hidden');
    document.getElementById('added-count').textContent = addedCount;
    stepDone.classList.remove('hidden');
});

backBtn.addEventListener('click', () => {
    stepReview.classList.add('hidden');
    stepInput.classList.remove('hidden');
});

addMoreBtn.addEventListener('click', () => {
    stepDone.classList.add('hidden');
    bulkInput.value = '';
    matchData = {};
    addAllBtn.disabled = false;
    addAllBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v6m0 0v6m0-6h6m-6 0H6"/></svg> Add selected to profile';
    stepInput.classList.remove('hidden');
});

function encodeId(str) {
    return btoa(encodeURIComponent(str)).replace(/[=+/]/g, '_');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function escapeAttr(text) {
    return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
