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
    const statusLabels = { consumed: 'Consumed', consuming: 'Enjoying', want_to_consume: 'Want to try' };
    const statusColors = {
        consumed: 'bg-sage/10 text-sage',
        consuming: 'bg-coral/10 text-coral',
        want_to_consume: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
    };
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

    return `
        <div class="bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark p-4 flex items-center gap-4 transition-base hover:border-sage/30">
            <a href="/media/${entry.media_type}/${entry.external_id}?source=${entry.source}" class="flex-shrink-0">${image}</a>
            <div class="flex-1 min-w-0">
                <a href="/media/${entry.media_type}/${entry.external_id}?source=${entry.source}" class="text-sm font-medium hover:text-sage transition-base">${escapeHtml(entry.title)}</a>
                <div class="flex items-center gap-2 mt-1">
                    <span class="px-1.5 py-0.5 ${typeColors[entry.media_type] || ''} text-[10px] font-medium rounded capitalize">${entry.media_type}</span>
                    <span class="px-1.5 py-0.5 ${statusColors[entry.status] || ''} text-[10px] font-medium rounded">${statusLabels[entry.status] || entry.status}</span>
                    ${entry.year ? `<span class="text-xs text-txt-muted">${entry.year}</span>` : ''}
                </div>
                <div class="flex items-center gap-0.5 mt-2" id="rating-row-${entry.id}">
                    ${ratingDots}
                    ${entry.rating ? `<span class="text-xs font-semibold ml-1.5 ${entry.rating <= 3 ? 'text-coral' : entry.rating <= 5 ? 'text-amber-500' : entry.rating <= 7 ? 'text-yellow-600' : 'text-emerald-500'}">${entry.rating}/10</span>` : `<span class="text-[10px] text-txt-muted ml-1.5">rate</span>`}
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
}

async function deleteEntry(id) {
    if (!confirm('Remove this from your profile?')) return;
    await fetch(`/api/profile/${id}`, { method: 'DELETE' });
    loadProfile();
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Initial load
loadProfile();
