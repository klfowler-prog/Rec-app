// Shared card actions: quick-add (consumed + rate), save-for-later, dismiss, inline rating dots.
// Used by search results and home page recommendation cards.

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

function showRatingDots(container, entryId) {
    container.innerHTML = `
        <div class="flex items-center gap-0.5 flex-wrap">
            <button onclick="rateItem(this,${entryId},1)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-coral transition-base text-[8px] font-bold text-transparent hover:text-white" title="1/10">1</button>
            <button onclick="rateItem(this,${entryId},2)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-coral transition-base text-[8px] font-bold text-transparent hover:text-white" title="2/10">2</button>
            <button onclick="rateItem(this,${entryId},3)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-coral transition-base text-[8px] font-bold text-transparent hover:text-white" title="3/10">3</button>
            <button onclick="rateItem(this,${entryId},4)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-amber-400 transition-base text-[8px] font-bold text-transparent hover:text-white" title="4/10">4</button>
            <button onclick="rateItem(this,${entryId},5)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-amber-400 transition-base text-[8px] font-bold text-transparent hover:text-white" title="5/10">5</button>
            <button onclick="rateItem(this,${entryId},6)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-yellow-500 transition-base text-[8px] font-bold text-transparent hover:text-white" title="6/10">6</button>
            <button onclick="rateItem(this,${entryId},7)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-yellow-500 transition-base text-[8px] font-bold text-transparent hover:text-white" title="7/10">7</button>
            <button onclick="rateItem(this,${entryId},8)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-emerald-400 transition-base text-[8px] font-bold text-transparent hover:text-white" title="8/10">8</button>
            <button onclick="rateItem(this,${entryId},9)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-emerald-400 transition-base text-[8px] font-bold text-transparent hover:text-white" title="9/10">9</button>
            <button onclick="rateItem(this,${entryId},10)" class="w-5 h-5 rounded-full bg-border-light dark:bg-border-dark hover:bg-emerald-500 transition-base text-[8px] font-bold text-transparent hover:text-white" title="10/10">10</button>
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
    const ratingColor = rating <= 3 ? 'text-coral' : rating <= 5 ? 'text-amber-500' : rating <= 7 ? 'text-yellow-600' : 'text-emerald-500';
    container.innerHTML = `<span class="text-xs font-semibold ${ratingColor}">${rating}/10 ✓</span>`;
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

async function saveForLater(btn, data) {
    btn.disabled = true;
    try {
        const resp = await fetch('/api/profile/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        if (resp.ok) {
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

// Helper to build the three-button action bar HTML used in cards
function buildActionBar(item, size = 'md') {
    const consumeData = escapeAttr(JSON.stringify({
        external_id: item.external_id || '', source: item.source || '', title: item.title,
        media_type: item.media_type, image_url: item.image_url || null, year: item.year || null,
        creator: item.creator || null,
        genres: (item.genres && Array.isArray(item.genres)) ? item.genres.join(', ') : (item.genres || null),
        description: item.description || null, status: 'consumed',
    }));
    const saveData = escapeAttr(JSON.stringify({
        external_id: item.external_id || '', source: item.source || '', title: item.title,
        media_type: item.media_type, image_url: item.image_url || null, year: item.year || null,
        creator: item.creator || null,
        genres: (item.genres && Array.isArray(item.genres)) ? item.genres.join(', ') : (item.genres || null),
        description: item.description || null, status: 'want_to_consume',
    }));
    const dismissData = escapeAttr(JSON.stringify({
        external_id: item.external_id || '', source: item.source || '',
        title: item.title, media_type: item.media_type,
    }));
    const verb = {movie:'Watched',tv:'Watched',book:'Read',podcast:'Listened'}[item.media_type] || 'Done';

    const btnSize = size === 'sm' ? 'px-2 py-1 text-[10px]' : 'px-2.5 py-1.5 text-xs';
    const iconBtnSize = size === 'sm' ? 'p-1' : 'p-1.5';
    const iconSize = size === 'sm' ? 'w-3 h-3' : 'w-3.5 h-3.5';

    return `
        <div class="flex items-center gap-1.5">
            <button onclick="saveForLater(this, ${saveData})" class="${iconBtnSize} bg-sage/10 hover:bg-sage hover:text-white text-sage rounded-lg transition-base" title="Save for later">
                <svg class="${iconSize}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg>
            </button>
            <button onclick="quickAdd(this, ${consumeData})" class="${btnSize} bg-sage/10 hover:bg-sage hover:text-white text-sage font-medium rounded-lg transition-base">${verb} it</button>
            <button onclick="dismissItem(this, ${dismissData})" class="${iconBtnSize} bg-gray-100 dark:bg-gray-800 hover:bg-coral hover:text-white text-txt-muted rounded-lg transition-base" title="Not interested">
                <svg class="${iconSize}" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
            </button>
        </div>
    `;
}
