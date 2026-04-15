const chatMessages = document.getElementById('chat-messages');
const recInput = document.getElementById('rec-input');
const recSend = document.getElementById('rec-send');
const recTypeFilter = document.getElementById('rec-type-filter');

let conversationHistory = [];
let isStreaming = false;

// Auto-resize textarea
recInput.addEventListener('input', () => {
    recInput.style.height = 'auto';
    recInput.style.height = Math.min(recInput.scrollHeight, 120) + 'px';
});

// Send on Enter (Shift+Enter for newline)
recInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

recSend.addEventListener('click', sendMessage);

// Mood buttons
document.querySelectorAll('.mood-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        recInput.value = btn.dataset.mood;
        sendMessage();
    });
});

async function sendMessage() {
    const message = recInput.value.trim();
    if (!message || isStreaming) return;

    isStreaming = true;
    recSend.disabled = true;

    // Add user message
    appendMessage('user', message);
    conversationHistory.push({ role: 'user', content: message });
    recInput.value = '';
    recInput.style.height = 'auto';

    // Create AI message placeholder
    const aiMsg = appendMessage('ai', '');
    const contentEl = aiMsg.querySelector('.chat-content');
    const extrasEl = aiMsg.querySelector('.chat-extras');

    try {
        const resp = await fetch('/api/recommend/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message,
                media_type: recTypeFilter.value || null,
                history: conversationHistory.slice(0, -1),
            }),
        });

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let fullText = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value);
            const lines = chunk.split('\n');

            for (const line of lines) {
                if (!line.startsWith('data: ')) continue;
                try {
                    const data = JSON.parse(line.slice(6));
                    if (data.text) {
                        fullText += data.text;
                        // Strip ITEMS block from rendered text
                        const displayText = fullText.split('===ITEMS===')[0];
                        contentEl.innerHTML = renderMarkdown(displayText);
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    }
                    if (data.error) {
                        contentEl.innerHTML = `<p class="text-red-500">Error: ${escapeHtml(data.error)}</p>`;
                    }
                } catch {}
            }
        }

        // Parse structured items and render cards + follow-up chips
        const items = parseItems(fullText);
        const cleanText = fullText.split('===ITEMS===')[0];
        conversationHistory.push({ role: 'assistant', content: cleanText });

        if (items.length > 0) {
            renderCards(extrasEl, items);
        }
        renderFollowUpChips(extrasEl, message);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    } catch (err) {
        contentEl.innerHTML = `<p class="text-red-500">Failed to get recommendations. Please try again.</p>`;
    }

    isStreaming = false;
    recSend.disabled = false;
    recInput.focus();
}

function appendMessage(role, content) {
    const div = document.createElement('div');
    div.className = 'flex gap-3';

    if (role === 'user') {
        div.innerHTML = `
            <div class="flex-1"></div>
            <div class="bg-sage/10 dark:bg-sage/20 border border-sage/20 rounded-lg rounded-tr-sm px-4 py-3 max-w-2xl">
                <p class="text-sm">${escapeHtml(content)}</p>
            </div>
            <div class="w-8 h-8 bg-coral/10 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
                <svg class="w-4 h-4 text-coral" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"/></svg>
            </div>
        `;
    } else {
        div.innerHTML = `
            <div class="w-8 h-8 bg-sage/10 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5">
                <svg class="w-4 h-4 text-sage" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/></svg>
            </div>
            <div class="flex-1 max-w-2xl space-y-3">
                <div class="bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark rounded-lg rounded-tl-sm px-4 py-3">
                    <div class="chat-content text-sm">${content ? renderMarkdown(content) : '<span class="inline-block w-2 h-4 bg-sage/40 animate-pulse rounded-sm"></span>'}</div>
                </div>
                <div class="chat-extras"></div>
            </div>
        `;
    }

    chatMessages.appendChild(div);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    return div;
}

function renderMarkdown(text) {
    // Simple markdown rendering
    return text
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/\*\*\*(.*?)\*\*\*/g, '<strong><em>$1</em></strong>')
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/### (.*?)(\n|$)/g, '<h3>$1</h3>')
        .replace(/## (.*?)(\n|$)/g, '<h3>$1</h3>')
        .replace(/^- (.*?)$/gm, '<li>$1</li>')
        .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>')
        .replace(/^(.*)$/, '<p>$1</p>')
        .replace(/<p><\/p>/g, '')
        .replace(/<p><h3>/g, '<h3>')
        .replace(/<\/h3><\/p>/g, '</h3>')
        .replace(/<p><ul>/g, '<ul>')
        .replace(/<\/ul><\/p>/g, '</ul>');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function parseItems(text) {
    // Extract the ===ITEMS=== ... ===END=== block and parse JSON
    const match = text.match(/===ITEMS===([\s\S]*?)===END===/);
    if (!match) return [];
    let jsonStr = match[1].trim();
    // Strip markdown code fences if present
    if (jsonStr.startsWith('```')) {
        jsonStr = jsonStr.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '');
    }
    try {
        const parsed = JSON.parse(jsonStr);
        return Array.isArray(parsed) ? parsed : [];
    } catch {
        return [];
    }
}

// Rank search results against the AI-provided title so we don't
// blindly take results[0]. TMDB (and Open Library) will fuzzy-match
// a short query like "The Act" to unrelated titles starting with
// similar words — we need to prefer exact/startswith matches that
// also actually have posters.
function pickBestSearchResult(aiTitle, aiMediaType, results) {
    if (!Array.isArray(results) || results.length === 0) return null;
    const q = (aiTitle || '').toLowerCase().trim();

    function titleScore(item) {
        const t = (item.title || '').toLowerCase().trim();
        if (!t) return 0;
        if (t === q) return 100;
        if (t.startsWith(q) || q.startsWith(t)) return 80;
        if (t.includes(q) || q.includes(t)) return 60;
        // Word overlap
        const qw = new Set(q.split(/\s+/));
        const tw = new Set(t.split(/\s+/));
        let overlap = 0;
        for (const w of qw) if (tw.has(w)) overlap++;
        return (overlap / Math.max(qw.size, 1)) * 40;
    }

    // Strict pass: respect media_type if the AI gave us one
    let candidates = results;
    if (aiMediaType) {
        const filtered = results.filter(r => r.media_type === aiMediaType);
        if (filtered.length > 0) candidates = filtered;
    }

    // Sort by (title score desc, has image desc)
    candidates.sort((a, b) => {
        const sa = titleScore(a);
        const sb = titleScore(b);
        if (sa !== sb) return sb - sa;
        const ia = a.image_url ? 1 : 0;
        const ib = b.image_url ? 1 : 0;
        return ib - ia;
    });

    // Require at least a meaningful title score. If the top candidate
    // is under 40 the search probably returned junk — better to show
    // the AI's raw title with no cover than to link to an unrelated
    // movie with a misleading poster.
    const top = candidates[0];
    if (!top || titleScore(top) < 40) return null;
    return top;
}

async function renderCards(container, items) {
    // Search each item for poster + external IDs so we can render proper cards
    const resultsEl = document.createElement('div');
    resultsEl.className = 'grid grid-cols-1 sm:grid-cols-2 gap-2';
    container.appendChild(resultsEl);

    const enriched = await Promise.all(items.slice(0, 5).map(async (item) => {
        try {
            const params = new URLSearchParams({ q: item.title });
            if (item.media_type) params.set('media_type', item.media_type);
            const resp = await fetch(`/api/media/search?${params}`);
            const results = await resp.json();
            const best = pickBestSearchResult(item.title, item.media_type, results);
            if (best) {
                // Keep the AI's prose title if the best match's title
                // diverges wildly — but the real safeguard is in
                // pickBestSearchResult returning null on weak matches.
                return { ...best, reason: item.reason || '' };
            }
        } catch {}
        // Fallback: render a card with the AI's raw title and no cover
        // rather than linking to something unrelated.
        return {
            title: item.title, media_type: item.media_type, year: item.year,
            image_url: null, external_id: '', source: '',
            reason: item.reason || '',
        };
    }));

    resultsEl.innerHTML = enriched.map(item => chatRecCard(item)).join('');

    // "Save all" button — queue every recommendation at once
    const saveableItems = enriched.filter(i => i.external_id);
    if (saveableItems.length > 1) {
        const saveAllBtn = document.createElement('button');
        saveAllBtn.className = 'mt-2 w-full px-3 py-2 bg-sage/10 hover:bg-sage hover:text-white text-sage text-xs font-medium rounded-lg transition-base inline-flex items-center justify-center gap-1.5';
        saveAllBtn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 5a2 2 0 012-2h10a2 2 0 012 2v16l-7-3.5L5 21V5z"/></svg> Save all ${saveableItems.length} to queue`;
        saveAllBtn.onclick = async () => {
            saveAllBtn.disabled = true;
            saveAllBtn.textContent = 'Saving...';
            let saved = 0;
            for (const item of saveableItems) {
                try {
                    const resp = await fetch('/api/profile/', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            external_id: item.external_id, source: item.source, title: item.title,
                            media_type: item.media_type, image_url: item.image_url || null,
                            year: item.year || null, creator: item.creator || null,
                            genres: item.genres ? (Array.isArray(item.genres) ? item.genres.join(', ') : item.genres) : null,
                            description: item.description || null, status: 'want_to_consume',
                        }),
                    });
                    if (resp.ok || resp.status === 409) saved++;
                } catch {}
            }
            saveAllBtn.innerHTML = `<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg> ${saved} saved to queue`;
        };
        container.appendChild(saveAllBtn);
    }
}

function chatRecCard(item) {
    const typeBadgeColors = {
        movie: 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-400',
        tv: 'bg-purple-50 text-purple-600 dark:bg-purple-900/30 dark:text-purple-400',
        book: 'bg-amber-50 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400',
        podcast: 'bg-green-50 text-green-600 dark:bg-green-900/30 dark:text-green-400',
    };
    const badgeClass = typeBadgeColors[item.media_type] || typeBadgeColors.movie;
    const link = item.external_id ? `/media/${item.media_type}/${item.external_id}?source=${item.source}` : '#';
    const safeTitle = item.title || 'Untitled';
    const image = item.image_url
        ? `<img src="${item.image_url}" alt="" class="w-14 h-20 object-cover rounded flex-shrink-0">`
        : `<div class="w-14 h-20 bg-sage/10 rounded flex-shrink-0 flex items-center justify-center"><span class="text-sage text-lg">${escapeHtml(safeTitle[0] || '?')}</span></div>`;

    let actions;
    if (typeof buildActionBar === 'function') {
        actions = `<div class="quick-add-area mt-1.5">${buildActionBar(item, 'sm')}</div>`;
    } else {
        actions = '';
    }

    return `
        <div class="bg-bg-light dark:bg-bg-dark border border-border-light dark:border-border-dark rounded-lg p-2.5 flex gap-2.5" data-rec-card>
            <a href="${link}" class="flex-shrink-0">${image}</a>
            <div class="flex-1 min-w-0">
                <div class="flex items-center gap-1.5 mb-0.5">
                    <span class="px-1.5 py-0.5 ${badgeClass} text-[9px] font-semibold rounded capitalize">${item.media_type}</span>
                    ${item.year ? `<span class="text-[10px] text-txt-muted">${item.year}</span>` : ''}
                </div>
                <a href="${link}" class="text-xs font-semibold block truncate hover:text-sage transition-base">${escapeHtml(safeTitle)}</a>
                <p class="text-[10px] text-txt-muted line-clamp-2 leading-tight mt-0.5">${escapeHtml(item.reason || '')}</p>
                ${actions}
            </div>
        </div>
    `;
}

function renderFollowUpChips(container, lastMessage) {
    const chips = [
        { label: 'Darker', query: 'Same vibe but darker' },
        { label: 'Lighter', query: 'Same vibe but lighter' },
        { label: 'Shorter', query: 'Same but shorter' },
        { label: 'Older', query: 'Same but older, classics' },
        { label: 'Newer', query: 'Same but from the last 5 years' },
        { label: 'Different medium', query: 'Same essence but in a different media type' },
        { label: 'More like these', query: 'Give me more recommendations like these' },
    ];
    const chipsEl = document.createElement('div');
    chipsEl.className = 'flex flex-wrap gap-1.5';
    chipsEl.innerHTML = chips.map(c =>
        `<button onclick="sendFollowUp('${c.query.replace(/'/g, "\\'")}')" class="px-2.5 py-1 bg-sage/10 hover:bg-sage hover:text-white text-sage text-[11px] font-medium rounded-full transition-base">${c.label}</button>`
    ).join('');
    container.appendChild(chipsEl);
}

function sendFollowUp(query) {
    recInput.value = query;
    sendMessage();
}
