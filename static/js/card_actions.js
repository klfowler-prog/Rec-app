// Shared card actions: quick-add (consumed + rate), save-for-later, dismiss, inline rating dots.
// Used by search results and home page recommendation cards.

// Unified rating color scale — sage (5) → gold (3) → coral (1)
function ratingTextColor(r) {
    if (r >= 5) return 'text-sage';
    if (r >= 4) return 'text-sage-light';
    if (r >= 3) return 'text-gold';
    if (r >= 2) return 'text-coral-light';
    return 'text-coral';
}
function ratingBgColor(r) {
    if (r >= 4.5) return 'bg-sage';
    if (r >= 4) return 'bg-sage-light';
    if (r >= 3.5) return 'bg-gold';
    if (r >= 3) return 'bg-gold';
    return 'bg-coral-light';
}

function logRecOutcome(title, outcome, userRating) {
    fetch('/api/profile/rec-events/outcome', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ title, outcome, user_rating: userRating || null }),
    }).catch(() => {});
}

async function quickAdd(btn, data) {
    btn.disabled = true;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '...';
    try {
        const resp = await fetch('/api/profile/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        let entryId = null;
        if (resp.ok) {
            const created = await resp.json();
            entryId = created.id;
        } else if (resp.status === 409) {
            try {
                const checkResp = await fetch(`/api/profile/check/${encodeURIComponent(data.source || '_')}/${encodeURIComponent(data.external_id || '_')}`);
                const checkData = await checkResp.json();
                entryId = checkData.entry ? checkData.entry.id : null;
            } catch {}
        }

        logRecOutcome(data.title, 'consumed');
        const container = btn.parentElement;
        if (entryId) {
            showRatingDots(container, entryId);
        } else {
            container.innerHTML = '<span class="text-xs font-medium text-sage">✓ Added — rate from profile</span>';
        }
    } catch {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
}

// startConsuming — create the entry with status='consuming' so the user
// can flag something they're in the middle of without having to click
// "Save for later" first and then dig through the profile page to flip
// the status. Mirrors quickAdd's POST flow but skips the rating-dots
// swap since the user hasn't finished yet. On success the action bar
// collapses to a "Started ✓" chip and the full page (if any) should
// ideally re-check the entry state, but the chip alone is enough to
// confirm the action worked.
async function startConsuming(btn, data) {
    btn.disabled = true;
    const originalHTML = btn.innerHTML;
    btn.innerHTML = '...';
    // Force the payload status even if the caller forgot to flip it.
    const payload = { ...data, status: 'consuming' };
    try {
        const resp = await fetch('/api/profile/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        // 409 = already in profile. Flip that existing entry's status
        // to 'consuming' so "Start" still works when the user had
        // previously saved it for later.
        if (resp.status === 409) {
            try {
                const checkResp = await fetch(`/api/profile/check/${encodeURIComponent(data.source || '_')}/${encodeURIComponent(data.external_id || '_')}`);
                const checkData = await checkResp.json();
                if (checkData.entry) {
                    await fetch(`/api/profile/${checkData.entry.id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ status: 'consuming' }),
                    });
                }
            } catch {}
        } else if (!resp.ok) {
            btn.innerHTML = originalHTML;
            btn.disabled = false;
            return;
        }

        logRecOutcome(data.title, 'started');
        const container = btn.parentElement;
        const verb = { movie: "watching", tv: "watching", book: "reading", podcast: "listening" }[data.media_type] || "it";
        container.innerHTML = `<span class="text-xs font-medium text-coral">✓ Started ${verb}</span>`;
    } catch {
        btn.innerHTML = originalHTML;
        btn.disabled = false;
    }
}

function showRatingDots(container, entryId) {
    container.innerHTML = `
        <div class="flex items-center gap-1 flex-wrap">
            <button onclick="rateItem(this,${entryId},1)" class="w-7 h-7 rounded-full bg-border-light dark:bg-border-dark hover:bg-coral transition-base text-xs font-bold text-transparent hover:text-white" title="1/5">1</button>
            <button onclick="rateItem(this,${entryId},2)" class="w-7 h-7 rounded-full bg-border-light dark:bg-border-dark hover:bg-coral-light transition-base text-xs font-bold text-transparent hover:text-white" title="2/5">2</button>
            <button onclick="rateItem(this,${entryId},3)" class="w-7 h-7 rounded-full bg-border-light dark:bg-border-dark hover:bg-gold transition-base text-xs font-bold text-transparent hover:text-white" title="3/5">3</button>
            <button onclick="rateItem(this,${entryId},4)" class="w-7 h-7 rounded-full bg-border-light dark:bg-border-dark hover:bg-sage-light transition-base text-xs font-bold text-transparent hover:text-white" title="4/5">4</button>
            <button onclick="rateItem(this,${entryId},5)" class="w-7 h-7 rounded-full bg-border-light dark:bg-border-dark hover:bg-sage transition-base text-xs font-bold text-transparent hover:text-white" title="5/5">5</button>
        </div>
    `;
}

async function rateItem(btn, entryId, rating) {
    if (!entryId) return;
    try {
        const resp = await fetch(`/api/profile/${entryId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ rating }),
        });
        if (!resp.ok) {
            btn.disabled = false;
            return;
        }
    } catch {
        btn.disabled = false;
        return;
    }
    const container = btn.parentElement;
    const ratingColor = ratingTextColor(rating);
    container.innerHTML = `<span class="text-xs font-semibold ${ratingColor}">${rating}/5 ✓</span>`;
    const card = btn.closest('[data-rec-card]') || btn.closest('.swim-lane-item') || btn.closest('.rounded-lg');
    if (card) {
        card.style.transition = 'opacity 0.5s, filter 0.5s';
        card.style.opacity = '0.4';
        card.style.filter = 'grayscale(50%)';
    }
    // Trigger post-rating discovery if available
    if (typeof showPostRatingPanel === 'function') {
        showPostRatingPanel(entryId);
    }
}

// Toggle inline rating — tap a displayed "4/5" to expand editable dots
function toggleInlineRate(el, entryId, currentRating) {
    const parent = el.parentElement;
    // If dots already shown, collapse
    if (parent.querySelector('.inline-edit-dots')) {
        parent.querySelector('.inline-edit-dots').remove();
        return;
    }
    const wrap = document.createElement('div');
    wrap.className = 'inline-edit-dots flex items-center gap-1 mt-1 flex-wrap';
    for (let n = 1; n <= 5; n++) {
        const active = n <= currentRating;
        const color = n <= 1 ? (active ? 'bg-coral' : 'bg-border-light dark:bg-border-dark')
                    : n <= 2 ? (active ? 'bg-coral-light' : 'bg-border-light dark:bg-border-dark')
                    : n <= 3 ? (active ? 'bg-gold' : 'bg-border-light dark:bg-border-dark')
                    : (active ? 'bg-sage' : 'bg-border-light dark:bg-border-dark');
        const dot = document.createElement('button');
        dot.className = `w-7 h-7 rounded-full ${color} hover:bg-sage transition-base text-xs font-bold ${active ? 'text-white' : 'text-transparent hover:text-white'}`;
        dot.textContent = n;
        dot.title = `${n}/5`;
        dot.onclick = async (e) => {
            e.preventDefault();
            e.stopPropagation();
            try {
                await fetch(`/api/profile/${entryId}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ rating: n }),
                });
                el.textContent = `${n}/5`;
                wrap.remove();
            } catch {}
        };
        wrap.appendChild(dot);
    }
    parent.appendChild(wrap);
}

async function saveForLater(btn, data) {
    btn.disabled = true;
    try {
        const resp = await fetch('/api/profile/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (resp.ok) {
            logRecOutcome(data.title, 'saved');
            const container = btn.closest('.quick-add-area');
            if (container) container.innerHTML = '<span class="text-xs font-medium text-sage">✓ Saved to queue</span>';
        } else if (resp.status === 409) {
            const container = btn.closest('.quick-add-area');
            if (container) container.innerHTML = '<span class="text-xs font-medium text-sage">✓ In profile</span>';
        } else {
            btn.disabled = false;
        }
    } catch {
        btn.disabled = false;
    }
}

async function dismissItem(btn, data) {
    btn.disabled = true;
    try {
        const resp = await fetch('/api/profile/dismiss', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (!resp.ok) {
            btn.disabled = false;
            return;
        }
        logRecOutcome(data.title, 'dismissed');
        const card = btn.closest('[data-rec-card]') || btn.closest('.swim-lane-item') || btn.closest('.rounded-lg');
        if (card) {
            card.style.transition = 'opacity 0.4s, transform 0.4s';
            card.style.opacity = '0';
            card.style.transform = 'scale(0.95)';
            setTimeout(() => card.remove(), 400);
        }
    } catch {
        btn.disabled = false;
    }
}

function escapeAttr(str) {
    return str.replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Shared status labels — used across the app
const STATUS_LABELS = {
    want_to_consume: 'Later',
    consuming: 'Now',
    consumed: 'Done',
    abandoned: 'Dropped',
};

const STATUS_COLORS = {
    want_to_consume: 'bg-sage/15 text-sage-dark dark:text-sage-light',
    consuming: 'bg-coral/15 text-coral',
    consumed: 'bg-sage/15 text-sage-dark dark:text-sage-light',
    abandoned: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
};

// Build an inline status switcher — 4 pill buttons for each state
// Current state is highlighted, tapping another transitions immediately
function buildStatusSwitcher(entryId, currentStatus, mediaType = null) {
    const verb = { movie: 'Watched', tv: 'Watched', book: 'Read', podcast: 'Listened' }[mediaType] || 'Done';
    // Use "Done" but on the consumed button, use contextual verb
    const labels = {
        want_to_consume: 'Later',
        consuming: 'Now',
        consumed: verb,
        abandoned: 'Dropped',
    };

    const states = ['want_to_consume', 'consuming', 'consumed', 'abandoned'];
    return `
        <div class="inline-flex rounded-lg bg-bg-light dark:bg-bg-dark border border-border-light dark:border-border-dark p-0.5 gap-0.5 text-[10px] font-medium" data-status-switcher="${entryId}">
            ${states.map(s => {
                const active = s === currentStatus;
                const base = 'px-2 py-1 rounded transition-base';
                const activeClass = active ? STATUS_COLORS[s] : 'text-txt-muted hover:text-txt';
                return `<button onclick="changeStatus(${entryId}, '${s}', this)" class="${base} ${activeClass}" title="${STATUS_LABELS[s]}">${labels[s]}</button>`;
            }).join('')}
        </div>
    `;
}

// Streaming provider badge — renders small service icons on cards
function renderProviderBadges(providers) {
    if (!providers || !providers.length) return '';
    const major = providers.filter(p => p.tier === 'major').slice(0, 3);
    const other = providers.filter(p => p.tier === 'other').length;
    const rental = providers.filter(p => p.tier === 'rental').length;

    let html = major.map(p =>
        p.logo_url
            ? `<img src="${p.logo_url}" alt="${p.name}" title="${p.name}" class="w-5 h-5 rounded" loading="lazy">`
            : `<span class="text-[8px] bg-gray-100 dark:bg-gray-800 px-1 rounded" title="${p.name}">${p.name.slice(0, 3)}</span>`
    ).join('');
    if (other > 0) html += `<span class="text-[8px] text-txt-muted bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded" title="Available on other streaming services">+${other} more</span>`;
    if (rental > 0 && major.length === 0 && other === 0) html += `<span class="text-[8px] text-txt-muted bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">Rent/Buy</span>`;

    return html ? `<div class="flex items-center gap-1 mt-1">${html}</div>` : '';
}

// Change an item's status via PUT /api/profile/{id}
async function changeStatus(entryId, newStatus, btn) {
    if (!entryId) return;
    try {
        const resp = await fetch(`/api/profile/${entryId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus }),
        });
        if (!resp.ok) return;

        // Update the switcher UI inline
        const switcher = btn.closest('[data-status-switcher]');
        if (switcher) {
            const buttons = switcher.querySelectorAll('button');
            buttons.forEach(b => {
                // Reset all to muted
                b.className = b.className.replace(/bg-sage\/15 text-sage-dark dark:text-sage-light|bg-coral\/15 text-coral|bg-sage\/15 text-sage-dark dark:text-sage-light|bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400/g, '').trim();
                if (!b.className.includes('text-txt-muted')) {
                    b.className += ' text-txt-muted hover:text-txt';
                }
            });
            // Highlight the new active
            btn.className = btn.className.replace('text-txt-muted hover:text-txt', '').trim() + ' ' + STATUS_COLORS[newStatus];
        }

        // If moved to "consumed", show rating dots so the user can rate inline
        if (newStatus === 'consumed') {
            // Find a place to show rating dots near the switcher
            const parent = switcher ? switcher.parentElement : btn.parentElement;
            if (parent) {
                // Check if rating dots already exist
                let ratingWrap = parent.querySelector('.inline-rating-dots');
                if (!ratingWrap) {
                    ratingWrap = document.createElement('div');
                    ratingWrap.className = 'inline-rating-dots mt-1';
                    parent.appendChild(ratingWrap);
                }
                showRatingDots(ratingWrap, entryId);
            }
        }
    } catch {}
}

// Helper to build the three-button action bar HTML used in cards
function buildActionBar(item, size = 'md') {
    const baseData = {
        external_id: item.external_id || '', source: item.source || '', title: item.title,
        media_type: item.media_type, image_url: item.image_url || null, year: item.year || null,
        creator: item.creator || null,
        genres: (item.genres && Array.isArray(item.genres)) ? item.genres.join(', ') : (item.genres || null),
        description: item.description || null,
    };
    const consumeData = escapeAttr(JSON.stringify({ ...baseData, status: 'consumed' }));
    const consumingData = escapeAttr(JSON.stringify({ ...baseData, status: 'consuming' }));
    const saveData = escapeAttr(JSON.stringify({ ...baseData, status: 'want_to_consume' }));
    const dismissData = escapeAttr(JSON.stringify({
        external_id: item.external_id || '', source: item.source || '',
        title: item.title, media_type: item.media_type,
    }));
    const doneVerb = {movie:'Watched',tv:'Watched',book:'Read',podcast:'Listened'}[item.media_type] || 'Done';

    const btnSize = size === 'sm' ? 'px-2 py-1 text-[10px]' : 'px-2.5 py-1.5 text-xs';

    return `
        <div class="flex items-center gap-1.5 flex-wrap">
            <button onclick="saveForLater(this, ${saveData})" class="${btnSize} bg-sage/10 hover:bg-sage hover:text-white text-sage font-medium rounded-lg transition-base">Later</button>
            <button onclick="startConsuming(this, ${consumingData})" class="${btnSize} bg-coral/10 hover:bg-coral hover:text-white text-coral font-medium rounded-lg transition-base">Now</button>
            <button onclick="quickAdd(this, ${consumeData})" class="${btnSize} bg-sage/10 hover:bg-sage hover:text-white text-sage font-medium rounded-lg transition-base">${doneVerb}</button>
            <button onclick="dismissItem(this, ${dismissData})" class="${btnSize} bg-gray-100 dark:bg-gray-800 hover:bg-coral hover:text-white text-txt-muted font-medium rounded-lg transition-base">Skip</button>
        </div>
    `;
}

// ---------------------------------------------------------------------------
// Global poster fallback. A lot of the image URLs we surface come from
// OpenLibrary cover IDs that return zero-byte responses or placeholder GIFs,
// or TMDB/iTunes URLs that occasionally 404 — with no onerror handler those
// leave blank colored squares on the page.
//
// Rather than touch every card renderer, install ONE delegated handler on
// the document that catches any <img> load failure inside a .poster-frame
// and swaps in a first-letter fallback tile, reading the title from the
// nearest card element (alt attr, or data-title, or the nearest
// [data-rec-card] title span).
//
// Registered with capture=true because <img>'s `error` event doesn't bubble
// by default.
// ---------------------------------------------------------------------------
(function installPosterFallback() {
    if (typeof document === 'undefined') return;
    if (document._posterFallbackInstalled) return;
    document._posterFallbackInstalled = true;

    function firstChar(s) {
        if (!s) return '?';
        const t = String(s).trim();
        return t ? t[0].toUpperCase() : '?';
    }

    function swap(img) {
        if (img._fallbackSwapped) return;
        img._fallbackSwapped = true;

        // Pull a title for the fallback letter from: alt attribute,
        // data-title, or the closest card's first title-bearing text node.
        let title = img.getAttribute('alt') || img.getAttribute('data-title') || '';
        if (!title) {
            const card = img.closest('[data-rec-card], .swim-lane-item, .rounded-lg, .flex');
            if (card) {
                const t = card.querySelector('.card-title, [data-title], p.font-medium, a.font-semibold, p.font-semibold, h3, h4');
                if (t) title = t.textContent || '';
            }
        }

        const frame = img.closest('.poster-frame');
        if (frame) {
            // Inside a poster-frame: replace with the standard fallback div
            const div = document.createElement('div');
            div.className = 'poster-fallback bg-sage/10';
            div.innerHTML = `<span class="text-sage text-2xl font-bold">${firstChar(title)}</span>`;
            img.replaceWith(div);
        } else {
            // Standalone img (e.g. profile list items): replace with
            // an inline fallback that inherits the img's sizing classes
            const div = document.createElement('div');
            const classes = Array.from(img.classList).filter(c => /^(w-|h-|rounded|flex-shrink)/.test(c));
            div.className = `${classes.join(' ')} bg-sage/10 flex items-center justify-center`;
            div.innerHTML = `<span class="text-sage text-sm font-bold">${firstChar(title)}</span>`;
            img.replaceWith(div);
        }
    }

    document.addEventListener('error', function (ev) {
        const t = ev.target;
        if (t && t.tagName === 'IMG') {
            swap(t);
        }
    }, true);  // capture — img error does not bubble

    // Some browsers don't fire `error` for zero-byte / 200-with-empty-body
    // responses; those images load successfully but have naturalWidth 0.
    // After load, check for that and swap too.
    document.addEventListener('load', function (ev) {
        const t = ev.target;
        if (t && t.tagName === 'IMG') {
            if (t.naturalWidth === 0 || t.naturalHeight === 0) swap(t);
        }
    }, true);
})();
