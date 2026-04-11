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
                        contentEl.innerHTML = renderMarkdown(fullText);
                        chatMessages.scrollTop = chatMessages.scrollHeight;
                    }
                    if (data.error) {
                        contentEl.innerHTML = `<p class="text-red-500">Error: ${escapeHtml(data.error)}</p>`;
                    }
                } catch {}
            }
        }

        conversationHistory.push({ role: 'assistant', content: fullText });
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
            <div class="bg-surface-light dark:bg-surface-dark border border-border-light dark:border-border-dark rounded-lg rounded-tl-sm px-4 py-3 max-w-2xl">
                <div class="chat-content text-sm">${content ? renderMarkdown(content) : '<span class="inline-block w-2 h-4 bg-sage/40 animate-pulse rounded-sm"></span>'}</div>
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
