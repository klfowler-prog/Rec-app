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
        const color = pr >= 4.5 ? 'bg-emerald-500'
                   : pr >= 4   ? 'bg-emerald-400'
                   : pr >= 3.5 ? 'bg-yellow-500'
                   : 'bg-amber-400';
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
        const bbReasonParam = pick.reason ? `&reason=${encodeURIComponent(pick.reason)}` : '';
        const link = pick.external_id ? `/media/${pick.media_type || mediaType}/${pick.external_id}?source=${pick.source}${bbReasonParam}` : '#';
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
        const actions = typeof buildActionBar === 'function' ? buildActionBar(itemForCard, 'sm') : '';
        const citedNames = Array.isArray(cited) && cited.length > 0
            ? cited.map(t => escapeHtml(t)).join(' & ')
            : null;
        const anchorLine = citedNames
            ? `<p class="text-[11px] text-txt-muted uppercase tracking-wide mt-2">${label} · because you loved ${citedNames}</p>`
            : `<p class="text-[11px] text-txt-muted uppercase tracking-wide mt-2">${label}</p>`;
        const providerIds = (pick.watch_providers || []).map(p => p.provider_id).filter(Boolean).join(',');
        return `
            <div class="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden shadow-sm" data-rec-card data-provider-ids="${providerIds}">
                <a href="${link}">${image}</a>
                <div class="p-4">
                    <div class="flex items-center gap-2 mb-1.5">
                        <span class="px-2 py-0.5 ${badge} text-[10px] font-semibold rounded-full capitalize">${pick.media_type || mediaType}</span>
                        ${pick.year ? `<span class="text-xs text-txt-muted">${pick.year}</span>` : ''}
                    </div>
                    <a href="${link}" class="text-sm font-semibold hover:text-sage transition-base block">${escapeHtml(pick.title)}</a>
                    ${typeof renderProviderBadges === 'function' && pick.watch_providers ? renderProviderBadges(pick.watch_providers) : ''}
                    ${pick.reason ? `<p class="text-xs text-txt-muted leading-relaxed mt-1">${escapeHtml(pick.reason)}</p>` : ''}
                    ${anchorLine}
                    <div class="mt-3 quick-add-area">${actions}</div>
                </div>
            </div>`;
    }

    // ---- For Your Day themes ----------------------------------------
    const THEME_META = {
        walking_the_dog:  { label: "While walking the dog",     blurb: "Podcasts you can drop in and out of.",                accent: 'text-green-500' },
        tonight_binge:    { label: "Tonight's binge",           blurb: "TV that actually earns the next episode.",            accent: 'text-purple-500' },
        wind_down:        { label: "Wind down before bed",      blurb: "Low-stakes, slow your pulse.",                        accent: 'text-amber-500' },
        background_work:  { label: "Background while you work", blurb: "Familiar and conversational, half-attention-safe.",   accent: 'text-sky-500' },
        weekend_binge:    { label: "Lose the weekend",          blurb: "Binge it. Fall in. Look up and it's dark outside.",   accent: 'text-coral' },
        quick_escape:     { label: "Quick escape",              blurb: "15-90 minutes, out of your own head.",                accent: 'text-rose-500' },
    };
    // Morning → daytime → evening → weekend
    const THEME_ORDER = ['walking_the_dog', 'background_work', 'quick_escape', 'tonight_binge', 'wind_down', 'weekend_binge'];

    async function loadThemes() {
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
                wrap.innerHTML = `<p class="text-sm text-txt-muted py-6 text-center">We'll build these out once you've rated a few items.</p>`;
                return;
            }
            wrap.innerHTML = rendered.join('');
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
                <div id="${containerId}" class="grid grid-cols-2 md:grid-cols-4 gap-4">
                    ${cards}
                </div>
            </div>`;
    }

    function renderThemeCard(item) {
        const mt = item.media_type || 'movie';
        const accent = TYPE_ACCENT[mt] || TYPE_ACCENT.movie;
        const badge = TYPE_BADGE[mt] || TYPE_BADGE.movie;
        const fit = mt === 'podcast' ? 'poster-contain' : 'poster-cover';
        const pr = typeof item.predicted_rating === 'number' ? prBadge(item.predicted_rating) : '';
        const imageInner = item.image_url
            ? `<img src="${item.image_url}" alt="" class="${fit}">`
            : `<div class="poster-fallback ${accent}"><span class="text-white text-3xl font-bold">${escapeHtml((item.title || '?')[0])}</span></div>`;
        const image = `<div class="poster-frame relative">${imageInner}${pr}</div>`;
        const reasonParam = item.reason ? `&reason=${encodeURIComponent(item.reason)}` : '';
        const link = item.external_id ? `/media/${mt}/${item.external_id}?source=${item.source}${reasonParam}` : '#';
        const itemForCard = {
            external_id: item.external_id || '',
            source: item.source || '',
            title: item.title,
            media_type: mt,
            image_url: item.image_url || null,
            year: item.year || null,
            creator: item.creator || null,
            genres: Array.isArray(item.genres) ? item.genres.join(', ') : (item.genres || null),
            description: item.description || null,
        };
        const actions = typeof buildActionBar === 'function' ? buildActionBar(itemForCard, 'sm') : '';
        const themeProviderIds = (item.watch_providers || []).map(p => p.provider_id).filter(Boolean).join(',');
        return `
            <div class="bg-surface-light dark:bg-surface-dark rounded-xl border border-border-light dark:border-border-dark overflow-hidden shadow-sm" data-rec-card data-provider-ids="${themeProviderIds}">
                <a href="${link}">${image}</a>
                <div class="p-3">
                    <div class="flex items-center gap-2 mb-1">
                        <span class="px-2 py-0.5 ${badge} text-[10px] font-semibold rounded-full capitalize">${mt}</span>
                        ${item.year ? `<span class="text-[11px] text-txt-muted">${item.year}</span>` : ''}
                    </div>
                    <a href="${link}" class="text-xs font-semibold hover:text-sage transition-base block truncate">${escapeHtml(item.title)}</a>
                    ${typeof renderProviderBadges === 'function' && item.watch_providers ? renderProviderBadges(item.watch_providers) : ''}
                    ${item.reason ? `<p class="text-[11px] text-txt-muted leading-snug mt-1">${escapeHtml(item.reason)}</p>` : ''}
                    <div class="mt-2 quick-add-area">${actions}</div>
                </div>
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
    window.escapeHtml = escapeHtml;
    window.prBadge = prBadge;
    window.TYPE_BADGE = TYPE_BADGE;
    window.TYPE_ACCENT = TYPE_ACCENT;
    window.TYPE_LABEL = TYPE_LABEL;
    window.ensureHomeBundle = ensureHomeBundle;
    window.loadBestBets = loadBestBets;
    window.loadThemes = loadThemes;
    window.toggleCollapsible = toggleCollapsible;
})();
