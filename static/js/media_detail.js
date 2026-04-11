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

        // Check if already in profile
        const checkResp = await fetch(`/api/profile/check/${currentMedia.source}/${EXTERNAL_ID}`);
        const checkData = await checkResp.json();
        if (checkData.in_profile) {
            document.getElementById('add-to-profile-btn').classList.add('hidden');
            document.getElementById('already-in-profile').classList.remove('hidden');
        }

        detailLoading.classList.add('hidden');
        detailContent.classList.remove('hidden');

        // Update page title
        document.title = `${currentMedia.title} — Rec`;
    } catch (err) {
        detailLoading.innerHTML = `<p class="text-txt-muted">Could not load details for this item.</p>`;
    }
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

        if (resp.ok) {
            addModal.classList.add('hidden');
            document.getElementById('add-to-profile-btn').classList.add('hidden');
            document.getElementById('already-in-profile').classList.remove('hidden');
        } else if (resp.status === 409) {
            addModal.classList.add('hidden');
            document.getElementById('add-to-profile-btn').classList.add('hidden');
            document.getElementById('already-in-profile').classList.remove('hidden');
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
