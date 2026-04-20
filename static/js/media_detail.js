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
            img.className = currentMedia.media_type === 'podcast' ? 'poster-contain' : 'poster-cover';
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

        // Metadata row — runtime, audience score, status, seasons
        renderMetaRow(currentMedia);

        // Watch providers — scoped to user's services
        renderWatchProviders(currentMedia);

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

        // Load taste fit prediction (only if not already in profile with a rating)
        if (!checkData.in_profile || !checkData.entry?.rating) {
            loadTasteFit();
        }

        // Load cross-medium related items + partner fit
        loadRelated();
        loadPartnerFit();
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
        const color = ratingTextColor(entry.rating);
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
                <p class="text-xs text-txt-muted leading-snug line-clamp-4">${escapeHtml(item.description || '')}</p>
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


async function loadTasteFit() {
    const section = document.getElementById('taste-fit-section');
    const card = document.getElementById('taste-fit-card');
    if (!section || !card || !currentMedia) return;
    try {
        // If the card that linked here already had a predicted rating, use it
        // for consistency — don't generate a second, potentially different score.
        const urlPr = new URLSearchParams(window.location.search).get('pr');
        let data;
        if (urlPr && !isNaN(parseFloat(urlPr))) {
            data = { predicted_rating: parseFloat(urlPr), reason: null };
        } else {
            const params = new URLSearchParams({ title: currentMedia.title, source: currentMedia.source || SOURCE });
            if (currentMedia.description) params.set('description', currentMedia.description.slice(0, 500));
            if (currentMedia.creator) params.set('creator', currentMedia.creator);
            if (currentMedia.genres && currentMedia.genres.length) params.set('genres', currentMedia.genres.join(', '));
            const resp = await fetch(`/api/media/taste-fit/${MEDIA_TYPE}/${EXTERNAL_ID}?${params}`);
            if (!resp.ok) return;
            data = await resp.json();
        }
        if (!data.predicted_rating && !data.reason) return;

        const pr = data.predicted_rating;
        const color = ratingTextColor(pr);
        const fitLabel = pr >= 4 ? 'Strong fit' : pr >= 3 ? 'Decent fit' : pr >= 2 ? 'Might not be for you' : 'Probably not your thing';

        card.innerHTML = `
            <div>
                ${pr ? `<p class="text-xs font-semibold ${color} mb-1"><span class="uppercase tracking-wide">${fitLabel}</span> · ${pr}/5</p>` : ''}
                ${data.reason ? `<p class="text-sm leading-relaxed text-txt dark:text-txt-light/80">${escapeHtml(data.reason)}</p>` : ''}
            </div>
        `;
        section.classList.remove('hidden');
    } catch {}
}

// Metadata row — compact line of runtime, audience score, status, seasons
function renderMetaRow(media) {
    const row = document.getElementById('detail-meta-row');
    if (!row) return;
    const parts = [];
    if (media.runtime) {
        const h = Math.floor(media.runtime / 60);
        const m = media.runtime % 60;
        parts.push(h > 0 ? `${h}h ${m}m` : `${m}m`);
    }
    if (media.audience_score) {
        const pct = Math.round(media.audience_score * 10);
        const color = pct >= 70 ? 'text-sage' : pct >= 50 ? 'text-gold' : 'text-coral';
        const countStr = media.audience_count ? ` (${media.audience_count.toLocaleString()})` : '';
        parts.push(`<span class="${color} font-semibold">${pct}%</span> audience${countStr}`);
    }
    if (media.network) parts.push(escapeHtml(media.network));
    if (media.status && media.media_type === 'tv') {
        const statusLabel = media.status === 'Returning Series' ? 'Returning' : media.status;
        parts.push(statusLabel);
    }
    if (media.seasons && media.media_type === 'tv') {
        parts.push(`${media.seasons} season${media.seasons > 1 ? 's' : ''}`);
    }
    if (parts.length) {
        row.innerHTML = parts.join('<span class="text-border-light dark:text-border-dark">·</span>');
        row.classList.remove('hidden');
    }
}

// Watch providers — scoped to user's services
function renderWatchProviders(media) {
    const section = document.getElementById('watch-providers-section');
    if (!section || !media.watch_providers || !media.watch_providers.length) {
        // No providers at all — check if we should prompt to set services
        if (section && typeof USER_SERVICES !== 'undefined' && USER_SERVICES.size === 0 && ['movie', 'tv'].includes(media.media_type)) {
            document.getElementById('watch-no-services').classList.remove('hidden');
            section.classList.remove('hidden');
        }
        return;
    }
    section.classList.remove('hidden');

    const hasUserServices = typeof USER_SERVICES !== 'undefined' && USER_SERVICES.size > 0;
    const mine = [];
    const other = [];

    for (const p of media.watch_providers) {
        if (hasUserServices && p.type === 'flatrate' && USER_SERVICES.has(p.provider_id)) {
            mine.push(p);
        } else {
            other.push(p);
        }
    }

    function renderProviderPill(p) {
        return p.logo_url
            ? `<div class="flex items-center gap-1.5 px-2 py-1 rounded-lg bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark">
                <img src="${p.logo_url}" alt="" class="w-5 h-5 rounded">
                <span class="text-xs font-medium">${escapeHtml(p.name)}</span>
               </div>`
            : `<span class="px-2 py-1 rounded-lg bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark text-xs">${escapeHtml(p.name)}</span>`;
    }

    if (mine.length) {
        const mineEl = document.getElementById('watch-on-mine');
        document.getElementById('watch-mine-providers').innerHTML = mine.map(renderProviderPill).join('');
        mineEl.classList.remove('hidden');
    }

    if (other.length) {
        const otherEl = document.getElementById('watch-on-other');
        const typeLabels = { flatrate: 'Stream', rent: 'Rent', buy: 'Buy' };
        // Group others by type
        const grouped = {};
        for (const p of other) {
            const label = typeLabels[p.type] || p.type;
            if (!grouped[label]) grouped[label] = [];
            grouped[label].push(p);
        }
        document.getElementById('watch-other-providers').innerHTML = Object.entries(grouped).map(([label, providers]) => `
            <div class="flex items-center gap-1.5">
                <span class="text-[10px] text-txt-muted">${label}:</span>
                ${providers.map(p => p.logo_url ? `<img src="${p.logo_url}" alt="${escapeHtml(p.name)}" title="${escapeHtml(p.name)}" class="w-5 h-5 rounded">` : `<span class="text-[10px]">${escapeHtml(p.name)}</span>`).join('')}
            </div>
        `).join('');
        otherEl.classList.remove('hidden');
    }

    if (!hasUserServices && ['movie', 'tv'].includes(media.media_type)) {
        document.getElementById('watch-no-services').classList.remove('hidden');
    }
}

// Partner fit — "Josh would enjoy this too"
async function loadPartnerFit() {
    const section = document.getElementById('partner-fit-section');
    const container = document.getElementById('partner-fit-cards');
    if (!section || !container || !currentMedia) return;
    try {
        const genres = currentMedia.genres ? currentMedia.genres.join(', ') : '';
        const params = new URLSearchParams({ title: currentMedia.title, genres });
        const resp = await fetch(`/api/relationships/partner-fit/${MEDIA_TYPE}/${EXTERNAL_ID}?${params}`);
        if (!resp.ok) return;
        const fits = await resp.json();
        if (!fits.length) return;

        container.innerHTML = fits.map(p => {
            const avatar = p.picture
                ? `<img src="${p.picture}" alt="" class="w-8 h-8 rounded-full">`
                : `<span class="w-8 h-8 rounded-full bg-sage/20 flex items-center justify-center text-xs font-bold text-sage">${(p.name||'?')[0]}</span>`;
            const pr = p.predicted_rating;
            const prColor = pr >= 4 ? 'text-sage' : pr >= 3 ? 'text-gold' : 'text-coral';
            const firstName = escapeHtml(p.name.split(' ')[0]);
            return `
                <div class="flex items-center gap-3 p-3 bg-surface-light dark:bg-surface-dark rounded-lg border border-border-light dark:border-border-dark">
                    ${avatar}
                    <div class="flex-1 min-w-0">
                        <p class="text-sm font-medium">${firstName} would enjoy this</p>
                        <p class="text-xs ${prColor}">${pr.toFixed(1)}/5 predicted</p>
                    </div>
                    <div class="flex gap-2">
                        <button onclick="watchTogether(${p.id}, '${firstName}')" class="px-3 py-1.5 bg-sage text-white text-xs font-medium rounded-lg hover:bg-sage-dark transition-base">Watch together</button>
                        <button onclick="recommendTo(${p.id}, '${firstName}')" class="px-3 py-1.5 border border-border-light dark:border-border-dark text-xs font-medium rounded-lg hover:border-sage hover:text-sage transition-base">Recommend</button>
                    </div>
                </div>`;
        }).join('');
        section.classList.remove('hidden');
    } catch {}
}

async function watchTogether(partnerId, partnerName) {
    if (!currentMedia) return;
    try {
        const resp = await fetch('/api/relationships/watch-together', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                partner_id: partnerId,
                title: currentMedia.title,
                media_type: currentMedia.media_type,
                external_id: currentMedia.external_id || EXTERNAL_ID,
                source: currentMedia.source || SOURCE,
                image_url: currentMedia.image_url || '',
            }),
        });
        if (resp.ok) {
            const btn = event.target;
            btn.innerHTML = `Added!`;
            btn.disabled = true;
            btn.classList.add('bg-sage/50');
            if (typeof trackEvent === 'function') trackEvent('watch_together', { partner: partnerName });
        }
    } catch {}
}

async function recommendTo(partnerId, partnerName) {
    if (!currentMedia) return;
    try {
        const resp = await fetch('/api/relationships/recommend', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                to_user_id: partnerId,
                title: currentMedia.title,
                media_type: currentMedia.media_type,
                external_id: currentMedia.external_id || EXTERNAL_ID,
                source: currentMedia.source || SOURCE,
                image_url: currentMedia.image_url || '',
            }),
        });
        if (resp.ok) {
            const btn = event.target;
            btn.innerHTML = `Sent!`;
            btn.disabled = true;
        }
    } catch {}
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

loadDetail();
