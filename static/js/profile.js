const profileList = document.getElementById('profile-list');
const profileStats = document.getElementById('profile-stats');
const profileEmpty = document.getElementById('profile-empty');
const editModal = document.getElementById('edit-modal');
const editForm = document.getElementById('edit-form');
const statusFilter = document.getElementById('status-filter');
const sortBy = document.getElementById('sort-by');

let currentFilter = 'all';

// Filter buttons
document.querySelectorAll('.profile-filter').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.profile-filter').forEach(b => {
            b.classList.remove('bg-sage/10', 'text-sage-dark', 'dark:text-sage-light', 'font-medium');
            b.classList.add('text-txt-muted');
        });
        btn.classList.add('bg-sage/10', 'text-sage-dark', 'dark:text-sage-light', 'font-medium');
        btn.classList.remove('text-txt-muted');
        currentFilter = btn.dataset.filter;
        loadProfile();
    });
});

statusFilter.addEventListener('change', loadProfile);
sortBy.addEventListener('change', loadProfile);

async function loadProfile() {
    const params = new URLSearchParams();
    if (currentFilter !== 'all') params.set('media_type', currentFilter);
    if (statusFilter.value) params.set('status', statusFilter.value);
    params.set('sort', sortBy.value);

    try {
        const [entriesResp, statsResp] = await Promise.all([
            fetch(`/api/profile/?${params}`),
            fetch('/api/profile/stats'),
        ]);
        const entries = await entriesResp.json();
        const stats = await statsResp.json();

        renderStats(stats);

        if (entries.length === 0) {
            profileList.innerHTML = '';
            profileEmpty.classList.remove('hidden');
            return;
        }

        profileEmpty.classList.add('hidden');
        profileList.innerHTML = entries.map(entry => profileEntry(entry)).join('');
    } catch (err) {
        profileList.innerHTML = `<p class="text-center text-txt-muted py-8">Error loading profile.</p>`;
    }
}

function renderStats(stats) {
    const statItems = [
        { label: 'Total', value: stats.total_entries, color: 'text-sage' },
        { label: 'Avg Rating', value: stats.avg_rating ? `${stats.avg_rating}/10` : '—', color: 'text-coral' },
        { label: 'Top Genre', value: stats.top_genres[0] || '—', color: 'text-sage' },
        { label: 'Types', value: Object.keys(stats.by_type).length, color: 'text-coral' },
    ];
    profileStats.innerHTML = statItems.map(s => `
        <div class="bg-surface-light dark:bg-surface-dark rounded-lg p-4 border border-border-light dark:border-border-dark">
            <p class="text-2xl font-semibold ${s.color}">${s.value}</p>
            <p class="text-xs text-txt-muted mt-0.5">${s.label}</p>
        </div>
    `).join('');
}

function profileEntry(entry) {
    const typeColors = {
        movie: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
        tv: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
        book: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
        podcast: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400',
    };

    const image = entry.image_url
        ? `<img src="${entry.image_url}" alt="" class="w-12 h-16 object-cover rounded">`
        : `<div class="w-12 h-16 bg-sage/10 rounded flex items-center justify-center"><span class="text-sage text-sm">${escapeHtml(entry.title[0])}</span></div>`;

    const ratingDots = [1,2,3,4,5,6,7,8,9,10].map(n => {
        const active = entry.rating && n <= entry.rating;
        const color = active ? ratingColor(n) : 'bg-border-light dark:bg-border-dark';
        return `<button onclick="inlineRate(${entry.id}, ${n}, this)" class="w-5 h-5 rounded-full ${color} hover:bg-sage transition-base text-[8px] font-bold ${active ? 'text-white' : 'text-transparent hover:text-white'}" title="${n}/10">${n}</button>`;
    }).join('');

    // Use shared status switcher from card_actions.js
    const statusSwitcher = typeof buildStatusSwitcher === 'function'
        ? buildStatusSwitcher(entry.id, entry.status, entry.media_type)
        : '';

    return `
        <div class="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark p-4 flex items-start gap-4 transition-base hover:border-sage/30">
            <input type="checkbox" class="entry-checkbox w-4 h-4 accent-coral rounded flex-shrink-0 mt-1" data-id="${entry.id}" onchange="updateBulkBar()">
            <a href="/media/${entry.media_type}/${entry.external_id}?source=${entry.source}" class="flex-shrink-0">${image}</a>
            <div class="flex-1 min-w-0 space-y-1.5">
                <div>
                    <a href="/media/${entry.media_type}/${entry.external_id}?source=${entry.source}" class="text-sm font-medium hover:text-sage transition-base">${escapeHtml(entry.title)}</a>
                    <div class="flex items-center gap-2 mt-0.5">
                        <span class="px-1.5 py-0.5 ${typeColors[entry.media_type] || ''} text-[10px] font-medium rounded capitalize">${entry.media_type}</span>
                        ${entry.year ? `<span class="text-xs text-txt-muted">${entry.year}</span>` : ''}
                    </div>
                </div>
                ${statusSwitcher}
                <div class="flex items-center gap-0.5" id="rating-row-${entry.id}">
                    ${ratingDots}
                    ${entry.rating ? `<span class="text-xs font-semibold ml-1.5 ${entry.rating <= 3 ? 'text-coral' : entry.rating <= 5 ? 'text-amber-500' : entry.rating <= 7 ? 'text-yellow-600' : 'text-emerald-500'}">${entry.rating}/10</span>` : `<span class="text-[10px] text-txt-muted ml-1.5">rate</span>`}
                    ${!entry.rating && entry.predicted_rating ? `<span class="text-[10px] ml-1.5 px-1.5 py-0.5 rounded-full ${entry.predicted_rating >= 8 ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-900/30 dark:text-emerald-400' : entry.predicted_rating >= 6 ? 'bg-yellow-50 text-yellow-600 dark:bg-yellow-900/30 dark:text-yellow-400' : entry.predicted_rating >= 4 ? 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400' : 'bg-red-50 text-red-500 dark:bg-red-900/30 dark:text-red-400'}" title="AI predicted rating">~${entry.predicted_rating}</span>` : ''}
                </div>
            </div>
            <div class="flex gap-1 flex-shrink-0">
                <button onclick="openEdit(${entry.id}, '${entry.status}', ${entry.rating || 'null'}, ${entry.notes ? "'" + escapeHtml(entry.notes).replace(/'/g, "\\'") + "'" : 'null'}, ${entry.tags ? "'" + escapeHtml(entry.tags).replace(/'/g, "\\'") + "'" : 'null'})" class="p-1.5 text-txt-muted hover:text-sage transition-base rounded hover:bg-sage/10" title="Edit details">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                </button>
                <button onclick="deleteEntry(${entry.id})" class="p-1.5 text-txt-muted hover:text-red-500 transition-base rounded hover:bg-red-50 dark:hover:bg-red-900/20" title="Remove">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
                </button>
            </div>
        </div>
    `;
}

function openEdit(id, status, rating, notes, tags) {
    document.getElementById('edit-id').value = id;
    document.getElementById('edit-status').value = status;
    document.getElementById('edit-rating').value = rating || '';
    document.getElementById('edit-notes').value = notes || '';
    document.getElementById('edit-tags').value = tags || '';
    editModal.classList.remove('hidden');
}

document.getElementById('edit-cancel').addEventListener('click', () => editModal.classList.add('hidden'));
editModal.addEventListener('click', (e) => { if (e.target === editModal) editModal.classList.add('hidden'); });

editForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const id = document.getElementById('edit-id').value;
    const data = {
        status: document.getElementById('edit-status').value,
        rating: document.getElementById('edit-rating').value ? parseFloat(document.getElementById('edit-rating').value) : null,
        notes: document.getElementById('edit-notes').value || null,
        tags: document.getElementById('edit-tags').value || null,
    };
    await fetch(`/api/profile/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
    editModal.classList.add('hidden');
    loadProfile();
});

function ratingColor(n) {
    // Coral (bad) -> Amber (mid) -> Green (good)
    if (n <= 3) return 'bg-coral';
    if (n <= 5) return 'bg-amber-400';
    if (n <= 7) return 'bg-yellow-500';
    if (n <= 9) return 'bg-emerald-400';
    return 'bg-emerald-500';
}

async function inlineRate(entryId, rating, btn) {
    // Optimistic UI update — recolor dots immediately
    const row = document.getElementById(`rating-row-${entryId}`);
    const dots = row.querySelectorAll('button');
    dots.forEach((dot, i) => {
        const n = i + 1;
        const active = n <= rating;
        dot.className = `w-5 h-5 rounded-full ${active ? ratingColor(n) : 'bg-border-light dark:bg-border-dark'} hover:bg-sage transition-base text-[8px] font-bold ${active ? 'text-white' : 'text-transparent hover:text-white'}`;
    });
    // Update label
    const label = row.querySelector('span:last-child');
    const labelColor = rating <= 3 ? 'text-coral' : rating <= 5 ? 'text-amber-500' : rating <= 7 ? 'text-yellow-600' : 'text-emerald-500';
    if (label) { label.className = `text-xs font-semibold ml-1.5 ${labelColor}`; label.textContent = `${rating}/10`; }

    await fetch(`/api/profile/${entryId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rating }),
    });

    // Trigger post-rating discovery panel
    if (typeof showPostRatingPanel === 'function') {
        showPostRatingPanel(entryId);
    }
}

async function deleteEntry(id) {
    if (!confirm('Remove this from your profile?')) return;
    await fetch(`/api/profile/${id}`, { method: 'DELETE' });
    loadProfile();
}

function updateBulkBar() {
    const checked = document.querySelectorAll('.entry-checkbox:checked');
    const bar = document.getElementById('bulk-bar');
    const count = document.getElementById('selected-count');
    if (checked.length > 0) {
        bar.classList.remove('hidden');
        count.textContent = checked.length;
    } else {
        bar.classList.add('hidden');
    }
}

function toggleSelectAll(checked) {
    document.querySelectorAll('.entry-checkbox').forEach(cb => cb.checked = checked);
    updateBulkBar();
}

async function bulkDelete() {
    const checked = document.querySelectorAll('.entry-checkbox:checked');
    if (checked.length === 0) return;
    if (!confirm(`Delete ${checked.length} items from your profile?`)) return;

    for (const cb of checked) {
        await fetch(`/api/profile/${cb.dataset.id}`, { method: 'DELETE' });
    }
    document.getElementById('select-all').checked = false;
    updateBulkBar();
    loadProfile();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function backfillPosters(btn) {
    const original = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<svg class="w-3.5 h-3.5 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" stroke-width="3" stroke-dasharray="60" stroke-dashoffset="20"/></svg> Searching...';
    try {
        const resp = await fetch('/api/profile/backfill-posters', { method: 'POST' });
        if (!resp.ok) {
            btn.innerHTML = original;
            btn.disabled = false;
            return;
        }
        const data = await resp.json();
        if (data.checked === 0) {
            btn.innerHTML = '✓ No missing posters';
        } else {
            btn.innerHTML = `✓ Found ${data.updated}/${data.checked}`;
        }
        setTimeout(() => loadProfile(), 600);
    } catch {
        btn.innerHTML = original;
        btn.disabled = false;
    }
}

async function loadTopTen() {
    try {
        const resp = await fetch('/api/profile/top?limit=10');
        const items = await resp.json();
        if (!items || items.length === 0) return;

        const typeColors = {
            movie: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
            tv: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
            book: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
            podcast: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400',
        };

        const grid = document.getElementById('top-ten-grid');
        grid.innerHTML = items.map((item, i) => {
            const fit = item.media_type === 'podcast' ? 'poster-contain' : 'poster-cover';
            const image = item.image_url
                ? `<div class="poster-frame"><img src="${item.image_url}" alt="" class="${fit}"></div>`
                : `<div class="poster-frame"><div class="poster-fallback bg-sage/10"><span class="text-sage text-2xl">${escapeHtml(item.title[0] || '?')}</span></div></div>`;
            const badge = typeColors[item.media_type] || typeColors.movie;
            const rc = item.rating <= 3 ? 'text-coral' : item.rating <= 5 ? 'text-amber-500' : item.rating <= 7 ? 'text-yellow-600' : 'text-emerald-500';
            return `
                <a href="/media/${item.media_type}/${item.external_id}?source=${item.source}" class="group">
                    <div class="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark overflow-hidden transition-base card-hover relative">
                        <div class="absolute top-2 left-2 w-6 h-6 bg-coral rounded-full flex items-center justify-center text-white text-[10px] font-bold shadow-md">${i + 1}</div>
                        ${image}
                        <div class="p-2.5">
                            <p class="text-xs font-medium truncate">${escapeHtml(item.title)}</p>
                            <div class="flex items-center justify-between mt-1">
                                <span class="px-1.5 py-0.5 ${badge} text-[10px] font-medium rounded capitalize">${item.media_type}</span>
                                <span class="text-xs font-semibold ${rc}">${item.rating}/10</span>
                            </div>
                        </div>
                    </div>
                </a>
            `;
        }).join('');
        document.getElementById('top-ten-section').classList.remove('hidden');
    } catch {}
}

async function loadTasteShape() {
    try {
        const resp = await fetch('/api/profile/shape');
        const data = await resp.json();
        if (!data.total) return;

        // Rating histogram
        const hist = data.rating_histogram || {};
        const maxCount = Math.max(1, ...Object.values(hist));
        const histEl = document.getElementById('rating-histogram');
        histEl.innerHTML = '';
        for (let i = 1; i <= 10; i++) {
            const count = hist[i] || 0;
            const height = (count / maxCount) * 100;
            const color = i <= 3 ? 'bg-coral' : i <= 5 ? 'bg-amber-400' : i <= 7 ? 'bg-yellow-500' : 'bg-emerald-500';
            histEl.innerHTML += `
                <div class="flex-1 ${color} rounded-t opacity-80" style="height: ${Math.max(height, 3)}%" title="${i}/10: ${count} item${count === 1 ? '' : 's'}"></div>
            `;
        }

        // Type distribution
        const dist = data.type_distribution || {};
        const typeEmoji = { movie: '🎬', tv: '📺', book: '📖', podcast: '🎧' };
        const typeLabel = { movie: 'Movies', tv: 'TV', book: 'Books', podcast: 'Podcasts' };
        const totalItems = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
        const distEl = document.getElementById('type-distribution');
        distEl.innerHTML = Object.entries(dist).map(([type, count]) => {
            const pct = Math.round((count / totalItems) * 100);
            return `
                <div>
                    <div class="flex items-center justify-between text-xs mb-0.5">
                        <span>${typeEmoji[type] || ''} ${typeLabel[type] || type}</span>
                        <span class="text-txt-muted">${count} · ${pct}%</span>
                    </div>
                    <div class="h-1.5 bg-border-light dark:bg-border-dark rounded-full overflow-hidden">
                        <div class="h-full bg-sage rounded-full" style="width: ${pct}%"></div>
                    </div>
                </div>
            `;
        }).join('');

        // Top genres with avg rating
        const genres = data.top_genres || [];
        const genreEl = document.getElementById('top-genres-avg');
        genreEl.innerHTML = genres.slice(0, 6).map(g => {
            const avgRating = g.avg_rating;
            const rc = !avgRating ? 'text-txt-muted' : avgRating <= 3 ? 'text-coral' : avgRating <= 5 ? 'text-amber-500' : avgRating <= 7 ? 'text-yellow-600' : 'text-emerald-500';
            return `
                <div class="flex items-center justify-between text-xs">
                    <span class="truncate">${escapeHtml(g.genre)}</span>
                    <span class="text-txt-muted ml-2 flex-shrink-0">${g.count} · <span class="font-semibold ${rc}">${avgRating || '—'}</span></span>
                </div>
            `;
        }).join('');

        document.getElementById('shape-section').classList.remove('hidden');
    } catch {}
}

// Backfill predicted ratings for queue items missing them
async function backfillPredictions() {
    try {
        await fetch('/api/profile/predict-ratings', { method: 'POST' });
    } catch {}
}

// Initial load
loadProfile();
loadTopTen();
loadTasteShape();
backfillPredictions();
