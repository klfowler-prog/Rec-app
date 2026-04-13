const detailLoading = document.getElementById('detail-loading');
const detailContent = document.getElementById('detail-content');
const addModal = document.getElementById('add-modal');
const addForm = document.getElementById('add-form');

let currentMedia = null;

async function loadDetail() {
    try {
        const resp = await fetch(`/api/media/${MEDIA_TYPE}/${EXTERNAL_ID}?source=${SOURCE}`);
        if (!resp.ok) throw new Error('Not found');
        currentMedia = await resp.json();

        // Fill in the details
        document.getElementById('detail-title').textContent = currentMedia.title;
        document.getElementById('detail-type-badge').textContent = currentMedia.media_type;
        document.getElementById('detail-year').textContent = currentMedia.year || '';
        document.getElementById('detail-creator').textContent = currentMedia.creator || '';
        document.getElementById('detail-description').textContent = currentMedia.description || 'No description available.';

        // Image
        const img = document.getElementById('detail-image');
        const placeholder = document.getElementById('detail-placeholder');
        if (currentMedia.image_url) {
            img.src = currentMedia.image_url;
            img.alt = currentMedia.title;
            img.classList.remove('hidden');
            placeholder.classList.add('hidden');
        } else {
            img.classList.add('hidden');
            placeholder.classList.remove('hidden');
            document.getElementById('detail-initial').textContent = currentMedia.title[0] || '?';
        }

        // Genres
        const genresEl = document.getElementById('detail-genres');
        if (currentMedia.genres && currentMedia.genres.length) {
            genresEl.innerHTML = currentMedia.genres.map(g =>
                `<span class="px-2 py-0.5 bg-sage/10 text-sage text-xs rounded-full">${escapeHtml(g)}</span>`
            ).join('');
        }

        // External link
        if (currentMedia.external_url) {
            const link = document.getElementById('detail-external-link');
            link.href = currentMedia.external_url;
            link.classList.remove('hidden');
        }

        // Watch providers
        if (currentMedia.watch_providers && currentMedia.watch_providers.length) {
            const section = document.getElementById('watch-providers-section');
            const container = document.getElementById('watch-providers');
            section.classList.remove('hidden');

            const typeLabels = { flatrate: 'Stream', rent: 'Rent', buy: 'Buy' };
            container.innerHTML = currentMedia.watch_providers.map(p => `
                <div class="flex items-center gap-2 px-3 py-2 bg-surface-light dark:bg-bg-dark border border-border-light dark:border-border-dark rounded-lg">
                    ${p.logo_url ? `<img src="${p.logo_url}" alt="${escapeHtml(p.name)}" class="provider-logo">` : ''}
                    <div>
                        <p class="text-xs font-medium">${escapeHtml(p.name)}</p>
                        <p class="text-[10px] text-txt-muted">${typeLabels[p.type] || p.type}</p>
                    </div>
                </div>
            `).join('');
        }

        // Check if already in profile. When it is, hide the "Add to
        // profile" button and mount a live status switcher so the
        // user can move the item between Later / Now / Done / Dropped
        // without navigating to /profile.
        const checkResp = await fetch(`/api/profile/check/${currentMedia.source}/${EXTERNAL_ID}`);
        const checkData = await checkResp.json();
        if (checkData.in_profile && checkData.entry) {
            document.getElementById('add-to-profile-btn').classList.add('hidden');
            mountStatusSwitcher(checkData.entry);
        }

        detailLoading.classList.add('hidden');
        detailContent.classList.remove('hidden');

        // Update page title
        document.title = `${currentMedia.title} — NextUp`;

        // Load cross-medium related items
        loadRelated();
    } catch (err) {
        detailLoading.innerHTML = `<p class="text-txt-muted">Could not load details for this item.</p>`;
    }
}

function mountStatusSwitcher(entry) {
    const block = document.getElementById('profile-status-block');
    const switcherMount = document.getElementById('status-switcher-mount');
    const ratingMount = document.getElementById('status-rating-mount');
    if (!block || !switcherMount || typeof buildStatusSwitcher !== 'function') return;

    switcherMount.innerHTML = buildStatusSwitcher(entry.id, entry.status, entry.media_type);

    // If already rated, show the rating. Otherwise, if status is
    // consumed, reveal rating dots so the user can rate in place.
    if (entry.rating) {
        const color = entry.rating <= 3 ? 'text-coral' : entry.rating <= 5 ? 'text-amber-500' : entry.rating <= 7 ? 'text-yellow-600' : 'text-emerald-500';
        ratingMount.innerHTML = `<span class="text-xs font-semibold ${color}">Rated ${entry.rating}/10</span>`;
    } else if (entry.status === 'consumed' && typeof showRatingDots === 'function') {
        showRatingDots(ratingMount, entry.id);
    } else {
        ratingMount.innerHTML = '';
    }
    block.classList.remove('hidden');
}

async function loadRelated() {
    try {
        const resp = await fetch(`/api/media/related/${MEDIA_TYPE}/${EXTERNAL_ID}?source=${SOURCE}`);
        const data = await resp.json();

        // Adaptation card
        if (data.adaptation && data.adaptation.title) {
            renderAdaptation(data.adaptation);
        }

        // Related items grouped by type
        const related = data.related || {};
        const loading = document.getElementById('related-loading');
        const content = document.getElementById('related-content');

        if (Object.keys(related).length === 0) {
            loading.innerHTML = '<p class="text-sm text-txt-muted">No related items found right now.</p>';
            return;
        }

        const typeLabels = { movie: 'Movies', tv: 'TV Shows', book: 'Books', podcast: 'Podcasts' };
        const typeGradients = {
            movie: 'gradient-blue', tv: 'gradient-purple',
            book: 'gradient-amber', podcast: 'bg-green-500',
        };

        let html = '';
        for (const [type, items] of Object.entries(related)) {
            if (!items || items.length === 0) continue;
            const label = typeLabels[type] || type;
            const grad = typeGradients[type] || 'bg-gray-500';

            html += `
                <div class="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-5">
                    <h4 class="text-sm font-semibold uppercase tracking-wide mb-3 flex items-center gap-2">
                        <span class="w-5 h-5 rounded ${grad}"></span>
                        ${label}
                    </h4>
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                        ${items.map(item => relatedCard(item, type)).join('')}
                    </div>
                </div>
            `;
        }

        content.innerHTML = html;
        loading.classList.add('hidden');
        content.classList.remove('hidden');
    } catch (e) {
        document.getElementById('related-loading').innerHTML =
            '<p class="text-sm text-txt-muted">Couldn\'t load related items.</p>';
    }
}

function relatedCard(item, fallbackType) {
    const mt = item.media_type || fallbackType;
    const link = item.external_id ? `/media/${mt}/${item.external_id}?source=${item.source}` : '#';
    const safeTitle = item.title || 'Untitled';
    // Use the shared poster frame so podcast squares sit inside the same
    // 2:3 slot as movie/TV/book posters — keeps the row heights uniform.
    const fit = mt === 'podcast' ? 'poster-contain' : 'poster-cover';
    const image = item.image_url
        ? `<div class="poster-frame w-16 rounded flex-shrink-0"><img src="${item.image_url}" alt="" class="${fit}"></div>`
        : `<div class="poster-frame w-16 rounded flex-shrink-0"><div class="poster-fallback bg-sage/10"><span class="text-sage text-lg">${escapeHtml(safeTitle[0] || '?')}</span></div></div>`;

    return `
        <a href="${link}" class="flex gap-3 p-2 rounded-lg hover:bg-bg-light dark:hover:bg-bg-dark transition-base">
            ${image}
            <div class="flex-1 min-w-0">
                <p class="text-sm font-semibold truncate">${escapeHtml(safeTitle)}</p>
                ${item.year ? `<p class="text-[10px] text-txt-muted mb-1">${item.year}</p>` : ''}
                <p class="text-xs text-txt-muted leading-snug line-clamp-3">${escapeHtml(item.reason || '')}</p>
            </div>
        </a>
    `;
}

function renderAdaptation(adaptation) {
    const section = document.getElementById('adaptation-section');
    const content = document.getElementById('adaptation-content');
    const mt = adaptation.media_type || 'movie';
    const link = adaptation.external_id ? `/media/${mt}/${adaptation.external_id}?source=${adaptation.source}` : '#';
    const fit = mt === 'podcast' ? 'poster-contain' : 'poster-cover';
    const image = adaptation.image_url
        ? `<div class="poster-frame w-14 rounded flex-shrink-0"><img src="${adaptation.image_url}" alt="" class="${fit}"></div>`
        : '';

    content.innerHTML = `
        <a href="${link}" class="flex items-start gap-3 group">
            ${image}
            <div class="flex-1">
                <p class="text-base font-semibold group-hover:text-coral transition-base">${escapeHtml(adaptation.title)}</p>
                <p class="text-xs text-txt-muted capitalize mb-1">${mt}${adaptation.year ? ' · ' + adaptation.year : ''}</p>
                <p class="text-sm text-txt leading-relaxed">${escapeHtml(adaptation.note || '')}</p>
            </div>
        </a>
    `;
    section.classList.remove('hidden');
}

// Add to profile
document.getElementById('add-to-profile-btn').addEventListener('click', () => {
    addModal.classList.remove('hidden');
});

document.getElementById('add-cancel').addEventListener('click', () => addModal.classList.add('hidden'));
addModal.addEventListener('click', (e) => { if (e.target === addModal) addModal.classList.add('hidden'); });

addForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!currentMedia) return;

    const data = {
        external_id: currentMedia.external_id,
        source: currentMedia.source,
        title: currentMedia.title,
        media_type: currentMedia.media_type,
        image_url: currentMedia.image_url,
        year: currentMedia.year,
        creator: currentMedia.creator,
        genres: currentMedia.genres ? currentMedia.genres.join(', ') : null,
        description: currentMedia.description,
        status: document.getElementById('add-status').value,
        rating: document.getElementById('add-rating').value ? parseFloat(document.getElementById('add-rating').value) : null,
        notes: document.getElementById('add-notes').value || null,
    };

    try {
        const resp = await fetch('/api/profile/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        if (resp.ok || resp.status === 409) {
            addModal.classList.add('hidden');
            document.getElementById('add-to-profile-btn').classList.add('hidden');
            let entry = null;
            if (resp.ok) {
                entry = await resp.json();
            } else {
                // 409 = already exists, fetch the existing entry
                try {
                    const checkResp = await fetch(`/api/profile/check/${currentMedia.source}/${currentMedia.external_id}`);
                    const checkData = await checkResp.json();
                    entry = checkData.entry || null;
                } catch {}
            }
            if (entry) {
                // Patch in any fields mountStatusSwitcher needs that the API may not return
                entry.media_type = entry.media_type || currentMedia.media_type;
                mountStatusSwitcher(entry);
            }
        }
    } catch (err) {
        alert('Failed to add to profile. Please try again.');
    }
});

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

loadDetail();
