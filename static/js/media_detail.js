const detailLoading = document.getElementById('detail-loading');
const detailContent = document.getElementById('detail-content');

let currentMedia = null;

// --- Description rendering --------------------------------------------
// Descriptions from TMDB / Open Library / Google Books / iTunes come in
// three wildly inconsistent shapes:
//   1. Plain text with \n\n paragraph breaks (Open Library, TMDB TV)
//   2. HTML with <p>, <br>, <i>, <b> tags (Google Books, some podcasts)
//   3. Plain text with no breaks at all (TMDB movies, some books)
// The old code set textContent on a single <p>, which collapsed all of
// these into one wall of text. This helper normalizes the input to a
// list of plain-text paragraphs, escapes them, and renders each as its
// own <p> with the prose container's vertical spacing.
function renderDescription(raw) {
    const container = document.getElementById('detail-description');
    const fadeEl = document.getElementById('detail-description-fade');
    const toggleBtn = document.getElementById('detail-description-toggle');
    if (!container) return;

    if (!raw || !raw.trim()) {
        container.innerHTML = '<p class="text-txt-muted italic">No description available.</p>';
        if (fadeEl) fadeEl.style.display = 'none';
        if (toggleBtn) toggleBtn.classList.add('hidden');
        container.style.maxHeight = 'none';
        return;
    }

    // Step 1: strip HTML tags via the browser's own parser so we decode
    // entities (&#39;, &amp;, &quot;) and don't leave <i>/<br> leaking
    // through. innerHTML on a detached element + textContent out gives
    // us the safest round-trip.
    const sandbox = document.createElement('div');
    sandbox.innerHTML = raw;
    // Replace <br> with newlines before extracting text so single-line
    // breaks aren't silently lost.
    sandbox.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
    // Turn block-level tags into paragraph markers.
    sandbox.querySelectorAll('p, div, li').forEach(el => {
        el.insertAdjacentText('afterend', '\n\n');
    });
    let text = sandbox.textContent || '';

    // Step 2: normalize line endings and split into paragraphs.
    text = text.replace(/\r\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
    const paragraphs = text
        .split(/\n\s*\n/)
        .map(p => p.replace(/\s+/g, ' ').trim())
        .filter(p => p.length > 0);

    if (paragraphs.length === 0) {
        container.innerHTML = '<p class="text-txt-muted italic">No description available.</p>';
        return;
    }

    // Step 3: render as escaped <p> elements. escapeHtml is defined in
    // card_actions.js (loaded before this script).
    container.innerHTML = paragraphs
        .map(p => `<p>${escapeHtml(p)}</p>`)
        .join('');

    // Step 4: if the rendered content overflows the clamped max-height,
    // reveal the Show more toggle and the fade overlay. Otherwise hide
    // both and let the content expand naturally.
    requestAnimationFrame(() => {
        const clampedHeight = 14 * 16; // 14rem in px, matches the template
        const actualHeight = container.scrollHeight;
        if (actualHeight > clampedHeight + 8) {
            if (toggleBtn) {
                toggleBtn.classList.remove('hidden');
                toggleBtn.textContent = 'Show more';
                toggleBtn.onclick = () => {
                    const expanded = container.style.maxHeight !== `${clampedHeight}px`;
                    if (expanded) {
                        container.style.maxHeight = `${clampedHeight}px`;
                        toggleBtn.textContent = 'Show more';
                        if (fadeEl) fadeEl.style.display = '';
                    } else {
                        container.style.maxHeight = `${container.scrollHeight}px`;
                        toggleBtn.textContent = 'Show less';
                        if (fadeEl) fadeEl.style.display = 'none';
                    }
                };
            }
        } else {
            // Content fits in the clamp — drop the clamp and hide the
            // fade/toggle so shorter descriptions don't have awkward
            // empty space below them.
            container.style.maxHeight = 'none';
            if (fadeEl) fadeEl.style.display = 'none';
            if (toggleBtn) toggleBtn.classList.add('hidden');
        }
    });
}

async function loadDetail() {
    try {
        const resp = await fetch(`/api/media/${MEDIA_TYPE}/${EXTERNAL_ID}?source=${SOURCE}`);
        if (!resp.ok) throw new Error('Not found');
        currentMedia = await resp.json();
        if (!currentMedia || !currentMedia.title) throw new Error('No data');

        // Fill in the details
        document.getElementById('detail-title').textContent = currentMedia.title;
        document.getElementById('detail-type-badge').textContent = currentMedia.media_type;
        document.getElementById('detail-year').textContent = currentMedia.year || '';
        document.getElementById('detail-creator').textContent = currentMedia.creator || '';
        renderDescription(currentMedia.description);

        // Show AI reason if passed from a recommendation card
        const reasonParam = new URLSearchParams(window.location.search).get('reason');
        if (reasonParam) {
            const banner = document.getElementById('rec-reason-banner');
            const text = document.getElementById('rec-reason-text');
            if (banner && text) {
                text.textContent = reasonParam;
                banner.classList.remove('hidden');
            }
        }

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

        // Inject the shared action bar (save / verb / dismiss)
        const actionBar = document.getElementById('detail-action-bar');
        if (actionBar && typeof buildActionBar === 'function') {
            actionBar.innerHTML = buildActionBar(currentMedia, 'md');
        }

        // Check if already in profile. When it is, hide the action bar
        // and mount a live status switcher (Later / Now / Done / Dropped).
        const checkResp = await fetch(`/api/profile/check/${currentMedia.source}/${EXTERNAL_ID}`);
        const checkData = await checkResp.json();
        if (checkData.in_profile && checkData.entry) {
            if (actionBar) actionBar.classList.add('hidden');
            mountStatusSwitcher(checkData.entry);
        }

        detailLoading.classList.add('hidden');
        detailContent.classList.remove('hidden');

        // Update page title
        document.title = `${currentMedia.title} — NextUp`;

        // Load cross-medium related items
        loadRelated();
    } catch (err) {
        detailLoading.innerHTML = `
            <div class="text-center space-y-3">
                <p class="text-txt-muted">Could not load details for this item.</p>
                <a href="/search" class="inline-block px-4 py-2 bg-sage text-white rounded-lg text-sm font-medium hover:bg-sage-dark transition-base">Search for it instead</a>
            </div>`;
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
        const color = entry.rating <= 1 ? 'text-coral' : entry.rating <= 2 ? 'text-amber-500' : entry.rating <= 3 ? 'text-yellow-600' : 'text-emerald-500';
        ratingMount.innerHTML = `<span class="text-xs font-semibold ${color} cursor-pointer hover:underline" onclick="toggleInlineRate(this, ${entry.id}, ${entry.rating})">Rated ${entry.rating}/5</span>`;
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


function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

loadDetail();
