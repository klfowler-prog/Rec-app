// Shared widgets used by Home (Phase B1) and the new Discover page.
// Exposes loadBestBets() and loadThemes() which both call into
// /api/media/home-bundle and /api/media/best-bet/<type>. The helpers
// look for fixed element IDs in the host page:
//   #best-bets       — grid container for Your Best Bets
//   #themes-wrap     — vertical stack container for For Your Day themes
// Pages that don't render one of those sections simply don't call the
// loader and the helper short-circuits.

(function () {
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = (text == null ? '' : text);
        return div.innerHTML;
    }

    function logImpressions(surface, items) {
        const cleaned = items.filter(i => i && i.title).map(i => ({
            title: i.title, media_type: i.media_type || '', predicted_rating: i.predicted_rating || null,
        }));
        if (!cleaned.length) return;
        fetch('/api/profile/rec-events/impression', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ surface, items: cleaned }),
        }).catch(() => {});
    }

    const TYPE_BADGE = {
        movie: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
        tv: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
        book: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
        podcast: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400',
    };
    const TYPE_ACCENT = {
        movie: 'gradient-blue',
        tv: 'gradient-purple',
        book: 'gradient-amber',
        podcast: 'bg-green-500',
    };
    const TYPE_LABEL = {
        movie: 'Movies',
        tv: 'TV Shows',
        book: 'Books',
        podcast: 'Podcasts',
    };

    function prBadge(pr) {
        if (pr == null || typeof pr !== 'number' || pr < 3) return '';
        const color = pr >= 4.5 ? 'bg-sage'
                   : pr >= 4   ? 'bg-sage-light'
                   : pr >= 3.5 ? 'bg-gold'
                   : 'bg-gold';
        return `<div class="absolute top-2 right-2 px-2 py-0.5 ${color} rounded-full shadow"><span class="text-[10px] font-bold text-white">${pr.toFixed(1)}</span></div>`;
    }

    // Shared bundle promise so a host page that calls both loadBestBets()
    // and loadThemes() only hits the API once.
    let _homeBundle = null;
    let _homeBundlePromise = null;
    async function ensureHomeBundle() {
        if (_homeBundle !== null) return _homeBundle;
        if (_homeBundlePromise) return _homeBundlePromise;
        _homeBundlePromise = (async () => {
            try {
                const resp = await fetch('/api/media/home-bundle');
                _homeBundle = resp.ok ? await resp.json() : { top_picks: [], suggestions: {}, themes: {}, insights: [] };
            } catch {
                _homeBundle = { top_picks: [], suggestions: {}, themes: {}, insights: [] };
            }
            return _homeBundle;
        })();
        return _homeBundlePromise;
    }

    // ---- Best Bets ---------------------------------------------------
    const MEDIA_TYPES = ['movie', 'tv', 'book', 'podcast'];

    async function loadBestBets() {
        const container = document.getElementById('best-bets');
        if (!container) return;
        try {
            const [results, bundle] = await Promise.all([
                Promise.all(
                    MEDIA_TYPES.map(mt => fetch(`/api/media/best-bet/${mt}`).then(r => r.ok ? r.json() : null).catch(() => null))
                ),
                ensureHomeBundle(),
            ]);

            const fallbackByType = {};
            for (const p of (bundle.top_picks || [])) {
                const mt = p.media_type;
                if (mt && !fallbackByType[mt]) fallbackByType[mt] = p;
            }

            const cards = [];
            for (let i = 0; i < MEDIA_TYPES.length; i++) {
                const mt = MEDIA_TYPES[i];
                const data = results[i];
                if (data && data.pick) {
                    cards.push(renderBestBetCard(mt, data.pick, data.cited || (data.anchor ? [data.anchor.title] : [])));
                } else if (fallbackByType[mt]) {
                    cards.push(renderBestBetCard(mt, fallbackByType[mt], []));
                }
            }
            if (cards.length === 0) {
                container.innerHTML = `
                    <div class="col-span-full bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark p-6 text-center">
                        <p class="text-sm text-txt-muted">Rate a few items to start getting personalised picks.</p>
                    </div>`;
                return;
            }
            container.innerHTML = cards.join('');
            const shownPicks = results.filter(d => d && d.pick).map(d => d.pick);
            if (shownPicks.length) logImpressions('best_bet', shownPicks);
        } catch {
            container.innerHTML = `<p class="col-span-full text-center text-sm text-txt-muted py-6">Couldn't load best bets right now.</p>`;
        }
    }

    function renderBestBetCard(mediaType, pick, cited) {
        const badge = TYPE_BADGE[mediaType] || TYPE_BADGE.movie;
        const accent = TYPE_ACCENT[mediaType] || TYPE_ACCENT.movie;
        const label = TYPE_LABEL[mediaType] || mediaType;
        const fit = mediaType === 'podcast' ? 'poster-contain' : 'poster-cover';
        const pr = typeof pick.predicted_rating === 'number' ? prBadge(pick.predicted_rating) : '';
        const imageInner = pick.image_url
            ? `<img src="${pick.image_url}" alt="" class="${fit}">`
            : `<div class="poster-fallback ${accent}"><span class="text-white text-3xl font-bold">${escapeHtml((pick.title || '?')[0])}</span></div>`;
        const image = `<div class="poster-frame relative">${imageInner}${pr}</div>`;
        const bbReasonParam = '';
        const bbPrParam = typeof pick.predicted_rating === 'number' ? `&pr=${pick.predicted_rating}` : '';
        const link = pick.external_id ? `/media/${pick.media_type || mediaType}/${pick.external_id}?source=${pick.source}${bbReasonParam}${bbPrParam}` : '#';
        const itemForCard = {
            external_id: pick.external_id || '',
            source: pick.source || '',
            title: pick.title,
            media_type: pick.media_type || mediaType,
            image_url: pick.image_url || null,
            year: pick.year || null,
            creator: pick.creator || null,
            genres: Array.isArray(pick.genres) ? pick.genres.join(', ') : (pick.genres || null),
            description: pick.description || null,
        };
        const posterAction = typeof buildPosterAction === 'function' ? buildPosterAction(itemForCard) : '';
        const citedNames = Array.isArray(cited) && cited.length > 0
            ? cited.map(t => escapeHtml(t)).join(' & ')
            : null;
        const anchorLine = citedNames
            ? `<p class="text-[11px] text-txt-muted uppercase tracking-wide mt-2">${label} · because you loved ${citedNames}</p>`
            : `<p class="text-[11px] text-txt-muted uppercase tracking-wide mt-2">${label}</p>`;
        const providerIds = (pick.watch_providers || []).map(p => p.provider_id).filter(Boolean).join(',');
        return `
            <div class="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden shadow-sm" data-rec-card data-provider-ids="${providerIds}">
                <div class="poster-frame relative">
                    <a href="${link}" class="block">${imageInner}</a>
                    ${pr}
                </div>
                <div class="p-2.5">
                    <div class="flex items-center gap-1.5 mb-1">
                        <span class="px-1.5 py-0.5 ${badge} text-[10px] font-semibold rounded-full capitalize">${pick.media_type || mediaType}</span>
                        ${pick.year ? `<span class="text-[10px] text-txt-muted">${pick.year}</span>` : ''}
                    </div>
                    <a href="${link}" class="text-[11px] font-semibold leading-tight hover:text-sage transition-base block line-clamp-2">${escapeHtml(pick.title)}</a>
                    ${typeof renderProviderBadges === 'function' && pick.watch_providers ? renderProviderBadges(pick.watch_providers) : ''}
                    ${pick.description ? `<p class="text-xs text-txt-muted leading-relaxed mt-1 line-clamp-4">${escapeHtml(pick.description)}</p>` : ''}
                    ${anchorLine}
                </div>
                ${posterAction}
            </div>`;
    }

    // ---- Vibe-based swim lanes ----------------------------------------
    const THEME_META = {
        tonight_binge:    { label: "Can't-stop-watching",        blurb: "Shows that earn the next episode.",                    accent: 'text-purple-500' },
        wind_down:        { label: "Comfort zone",               blurb: "Cozy, low-stakes, feels like a warm blanket.",        accent: 'text-gold' },
        quick_escape:     { label: "Quick escape",               blurb: "Under 90 minutes. Get out of your own head.",         accent: 'text-rose-500' },
        walking_the_dog:  { label: "Good for a walk",            blurb: "Podcasts you can drop in and out of.",                accent: 'text-green-500' },
    };
    const THEME_ORDER = ['tonight_binge', 'wind_down', 'quick_escape', 'walking_the_dog'];

    async function loadThemes(retried) {
        const wrap = document.getElementById('themes-wrap');
        if (!wrap) return;
        try {
            const bundle = await ensureHomeBundle();
            const themes = bundle.themes || {};
            const rendered = [];
            for (const slug of THEME_ORDER) {
                const items = themes[slug];
                if (!Array.isArray(items) || items.length < 2) continue;
                rendered.push(renderThemeRow(slug, items));
            }
            if (rendered.length === 0) {
                if (!retried || retried < 3) {
                    // Bundle may still be generating — bust the cached promise and retry
                    _homeBundle = null;
                    _homeBundlePromise = null;
                    wrap.innerHTML = `<div class="text-center py-10 bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark rounded-2xl"><div class="inline-block w-6 h-6 border-2 border-sage/30 border-t-sage rounded-full animate-spin"></div><p class="text-xs text-txt-muted mt-3">Building your picks&hellip; this can take a moment.</p></div>`;
                    const attempt = (retried || 0) + 1;
                    setTimeout(() => loadThemes(attempt), 15000);
                    return;
                }
                wrap.innerHTML = `<p class="text-sm text-txt-muted py-6 text-center">We'll build these out once you've rated a few items.</p>`;
                return;
            }
            wrap.innerHTML = rendered.join('');
            for (const slug of THEME_ORDER) {
                const items = themes[slug];
                if (Array.isArray(items) && items.length >= 2) {
                    logImpressions(`theme_${slug}`, items);
                }
            }
            if (typeof overlayQueueBadges === 'function') overlayQueueBadges(wrap);
        } catch {
            wrap.innerHTML = `<p class="text-sm text-txt-muted py-6 text-center">Couldn't load themed picks right now.</p>`;
        }
    }

    function renderThemeRow(slug, items) {
        const meta = THEME_META[slug] || { label: slug, blurb: '', accent: 'text-sage' };
        const cards = items.map(renderThemeCard).join('');
        const containerId = `theme-row-${slug}`;
        return `
            <div>
                <div class="flex items-center justify-between mb-2">
                    <div>
                        <h3 class="text-base font-semibold ${meta.accent}">${escapeHtml(meta.label)}</h3>
                        <p class="text-xs text-txt-muted">${escapeHtml(meta.blurb)}</p>
                    </div>
                </div>
                <div id="${containerId}" class="swim-lane flex gap-3 overflow-x-auto pb-2" style="scroll-snap-type: x mandatory;">
                    ${cards}
                </div>
            </div>`;
    }

    function renderThemeCard(item) {
        const mt = item.media_type || 'movie';
        const badge = TYPE_BADGE[mt] || TYPE_BADGE.movie;
        const accent = TYPE_ACCENT[mt] || TYPE_ACCENT.movie;
        const fit = mt === 'podcast' ? 'poster-contain' : 'poster-cover';
        const pr = typeof item.predicted_rating === 'number' ? prBadge(item.predicted_rating) : '';
        const imageInner = item.image_url
            ? `<img src="${item.image_url}" alt="" class="${fit}">`
            : `<div class="poster-fallback ${accent}"><span class="text-white text-3xl font-bold">${escapeHtml((item.title || '?')[0])}</span></div>`;
        const image = `<div class="poster-frame relative">${imageInner}${pr}</div>`;
        const reasonParam = '';
        const prParam = typeof item.predicted_rating === 'number' ? `&pr=${item.predicted_rating}` : '';
        const link = item.external_id ? `/media/${mt}/${item.external_id}?source=${item.source}${reasonParam}${prParam}` : '#';
        const themeProviderIds = (item.watch_providers || []).map(p => p.provider_id).filter(Boolean).join(',');
        const posterAction = typeof buildPosterAction === 'function' ? buildPosterAction(item) : '';
        return `
            <div class="flex-shrink-0 bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden shadow-sm card-hover transition-base" style="width: 130px; scroll-snap-align: start;" data-rec-card data-provider-ids="${themeProviderIds}">
                <div class="poster-frame relative">
                    <a href="${link}" class="block">${imageInner}</a>
                    ${pr}
                </div>
                <div class="p-2">
                    <div class="flex items-center gap-1 mb-0.5">
                        <span class="px-1.5 py-0.5 ${badge} text-[9px] font-semibold rounded-full capitalize">${mt}</span>
                    </div>
                    <a href="${link}" class="text-[11px] font-semibold leading-tight line-clamp-2 hover:text-sage transition-base block">${escapeHtml(item.title)}</a>
                </div>
                ${posterAction}
            </div>`;
    }

    function applyCollapsible(container, visibleCount) {
        const count = container.children.length;
        const row = container.closest('div');
        const toggleBtn = row ? row.querySelector('[data-role="theme-toggle"]') : null;
        if (count <= visibleCount) {
            container.classList.remove('collapsed');
            container.classList.add('expanded');
            if (toggleBtn) toggleBtn.classList.add('hidden');
            return;
        }
        container.classList.add('collapsed');
        if (toggleBtn) {
            toggleBtn.textContent = `Show all ${count}`;
            toggleBtn.classList.remove('hidden');
        }
    }

    function toggleCollapsible(containerId, btn) {
        const el = document.getElementById(containerId);
        if (!el) return;
        if (el.classList.contains('collapsed')) {
            el.classList.remove('collapsed');
            el.classList.add('expanded');
            btn.textContent = 'Show less';
        } else {
            el.classList.remove('expanded');
            el.classList.add('collapsed');
            btn.textContent = `Show all ${el.children.length}`;
        }
    }

    // Expose globals for inline page scripts.
    function scrollToTheme(slug) {
        const el = document.getElementById(`theme-row-${slug}`);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    window.escapeHtml = escapeHtml;
    window.prBadge = prBadge;
    window.TYPE_BADGE = TYPE_BADGE;
    window.TYPE_ACCENT = TYPE_ACCENT;
    window.TYPE_LABEL = TYPE_LABEL;
    window.ensureHomeBundle = ensureHomeBundle;
    window.loadBestBets = loadBestBets;
    window.loadThemes = loadThemes;
    window.scrollToTheme = scrollToTheme;
    window.toggleCollapsible = toggleCollapsible;
})();
