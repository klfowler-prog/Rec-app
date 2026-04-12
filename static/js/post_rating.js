// Post-rating discovery panel — shows cross-medium next-steps after rating an item
// Called from card_actions.js rateItem() and profile.js inlineRate()

// Ensure escapeHtml is available (define early in case other scripts haven't loaded)
if (typeof escapeHtml === 'undefined') {
    window.escapeHtml = function (text) {
        const div = document.createElement('div');
        div.textContent = (text === null || text === undefined) ? '' : String(text);
        return div.innerHTML;
    };
}

let postRatingTimeout = null;

async function showPostRatingPanel(entryId) {
    if (!entryId) return;

    try {
        const resp = await fetch('/api/profile/');
        if (!resp.ok) return;
        const entries = await resp.json();
        if (!Array.isArray(entries)) return;
        const entry = entries.find(e => e.id === entryId);
        if (!entry) return;

        // Can't fetch related items without an external_id
        if (!entry.external_id || !entry.source) return;

        // Fetch related items
        const relResp = await fetch(`/api/media/related/${entry.media_type}/${encodeURIComponent(entry.external_id)}?source=${encodeURIComponent(entry.source)}`);
        if (!relResp.ok) return;
        const relData = await relResp.json();
        const related = relData.related || {};

        // Flatten into a single array (one per media type)
        const items = [];
        for (const [type, list] of Object.entries(related)) {
            for (const item of (list || []).slice(0, 1)) {
                items.push({ ...item, media_type: item.media_type || type });
            }
        }

        if (items.length === 0) return;

        // Render the panel
        const panel = document.getElementById('post-rating-panel');
        const content = document.getElementById('post-rating-content');
        if (!panel || !content) return;

        content.innerHTML = `
            <p class="text-xs text-txt-muted mb-2">Because you just rated <strong class="text-txt dark:text-txt-light">${escapeHtml(entry.title)}</strong>:</p>
            ${items.slice(0, 3).map(item => postRatingCard(item)).join('')}
        `;

        panel.classList.remove('hidden');
        // Slide up animation
        requestAnimationFrame(() => {
            panel.style.transform = 'translateY(0)';
        });

        // Auto-hide after 15 seconds
        clearTimeout(postRatingTimeout);
        postRatingTimeout = setTimeout(closePostRatingPanel, 15000);
    } catch {}
}

function postRatingCard(item) {
    const typeBadgeColors = {
        movie: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
        tv: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
        book: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
        podcast: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400',
    };
    const badgeClass = typeBadgeColors[item.media_type] || typeBadgeColors.movie;
    const safeTitle = item.title || 'Untitled';
    const link = item.external_id ? `/media/${item.media_type}/${encodeURIComponent(item.external_id)}?source=${encodeURIComponent(item.source || '')}` : '#';
    const image = item.image_url
        ? `<img src="${item.image_url}" alt="" class="w-12 h-16 object-cover rounded flex-shrink-0">`
        : `<div class="w-12 h-16 bg-sage/10 rounded flex-shrink-0 flex items-center justify-center"><span class="text-sage text-sm">${escapeHtml(safeTitle[0] || '?')}</span></div>`;

    const escapeAttrFn = typeof escapeAttr === 'function' ? escapeAttr : (s => s.replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'));
    const saveData = escapeAttrFn(JSON.stringify({
        external_id: item.external_id || '', source: item.source || '', title: item.title,
        media_type: item.media_type, image_url: item.image_url || null, year: item.year || null,
        creator: item.creator || null, genres: null, description: null, status: 'want_to_consume',
    }));

    return `
        <div class="flex gap-3 p-2 rounded-lg hover:bg-bg-light dark:hover:bg-bg-dark transition-base">
            <a href="${link}" class="flex-shrink-0">${image}</a>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5 mb-0.5">
                    <span class="px-1.5 py-0.5 ${badgeClass} text-[9px] font-semibold rounded capitalize">${item.media_type}</span>
                    ${item.year ? `<span class="text-[10px] text-txt-muted">${item.year}</span>` : ''}
                </div>
                <a href="${link}" class="text-xs font-semibold block truncate hover:text-sage transition-base">${escapeHtml(safeTitle)}</a>
                <p class="text-[10px] text-txt-muted line-clamp-2 leading-tight mt-0.5">${escapeHtml(item.reason || '')}</p>
                <div class="mt-1.5 quick-add-area">
                    <button onclick="saveForLater(this, ${saveData})" class="px-2 py-1 bg-sage/10 hover:bg-sage hover:text-white text-sage text-[10px] font-medium rounded transition-base flex items-center gap-1">
                        <svg class="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>
                        Save
                    </button>
                </div>
            </div>
        </div>
    `;
}

function closePostRatingPanel() {
    const panel = document.getElementById('post-rating-panel');
    if (!panel) return;
    panel.style.transform = 'translateY(120%)';
    setTimeout(() => panel.classList.add('hidden'), 350);
    clearTimeout(postRatingTimeout);
}
