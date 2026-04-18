# NextUp → StorySignal Roadmap

## Rebrand: NextUp → StorySignal

### Brand Concept: "Your taste has a signal. We read it."

The word "signal" threads through every surface to create a cohesive language users internalize. The goal: people say "What's your signal?" to mean "what does your personalized AI think about how you'll feel about something?"

### Vocabulary Mapping

| Current term | StorySignal term | Where it shows up |
|---|---|---|
| Predicted rating (7.5) | Signal strength (7.5) | Cards, queue, library — every card badge |
| Taste DNA | Your Signal | My Taste page, share card |
| Taste profile | Signal profile | Onboarding, settings |
| "Sharpen your recs" | "Strengthen your signal" | Home rating batch |
| "Best bet" | "Strongest signal" | Discover, home |
| Fit score badge | Signal badge | Every card with a predicted score |
| "Based on your taste" | "Your signal says..." | AI commentary, reasons |
| Quiz results | Signal calibration | Quiz completion screen |
| Resonance (heart on progress cards) | Signal boost | Home currently-into cards |
| Dismissed items | Noise | "Mark as noise" instead of "skip" |
| Abandoned | Lost signal | Status for things you dropped |

### What NOT to rename
- "Later / Now / Watched / Dropped" — clear action verbs, keep literal
- Media type labels (Movie, TV, Book, Podcast)
- "Library" — universally understood
- Basic navigation (Home, Discover, Search, Add)

### Surface-by-Surface Implementation

**1. Signal badge (predicted rating)**
- Replace colored number circle with signal-wave icon + number
- "Signal: 8.5" instead of plain "8.5"
- Appears on every movie/TV/book/podcast card across the app

**2. "Your Signal" page (currently Taste DNA)**
- Rename page + nav to "My Signal"
- Share card headline: "Leann's Signal"
- "Check out my Signal" as social CTA
- Share prompt: "What's your signal?"

**3. Onboarding**
- "Let's calibrate your signal" instead of "Build your taste profile"
- Quizzes become "signal calibration"
- Completion screen: "Signal locked in"

**4. Discover page**
- "Strongest signals" instead of "Your best bets"
- Theme sections: "Signals for tonight" / "Signals for winding down"
- AI chat: "Based on your signal, here's what I'd pick..."

**5. Together mode**
- "Compare signals" instead of "Compare tastes"
- "Signal overlap: 73%" as compatibility score
- "Where your signals align" for shared recommendations

**6. Daily habit / rating flow**
- Rating feedback: "Signal updated" with brief animation
- Rating batch header: "Strengthen your signal"
- Subtext: "More data, stronger signal"

**7. Social / sharing**
- Share card: "My Signal" with summary
- New user CTA: "What's your signal?"
- Welcome page: "Every movie you love, every book you can't put down, every show you binge — it's all signal. StorySignal reads it and connects the dots."

**8. Future: notifications**
- "New signal match: X just landed on Netflix"
- "Your signal updated — 3 new picks on Discover"

### Code/Template Changes (31 occurrences)
- [ ] `app/main.py` — FastAPI app title
- [ ] `app/services/recommendation.py` — AI system prompt
- [ ] `app/services/share_card.py` — brand text on share image
- [ ] `app/routers/media.py` — AI prompts, share text
- [ ] `app/routers/pages.py` — template context
- [ ] `app/templates/base.html` — sidebar logo + brand text
- [ ] `app/templates/welcome.html` — landing page copy, title, OG tags
- [ ] `app/templates/share_card_page.html` — OG tags
- [ ] `app/templates/index.html` — invite copy
- [ ] `app/templates/taste_dna.html` — share text
- [ ] `app/templates/onboarding.html` — welcome text
- [ ] `app/templates/access_denied.html` — page title
- [ ] `app/templates/plex_import.html` — reference
- [ ] `static/js/media_detail.js` — page title
- [ ] `README.md` + `ROADMAP.md`

### Logo
- [ ] Remove old NextUp logo references from `base.html`, `welcome.html`
- [ ] Design/provide new StorySignal logo
- [ ] Replace `static/img/a_vector_style_digital_vector_logo_for_nextup_fe.png`
- [ ] Update share card brand text in `share_card.py`

### External
- [ ] Register storysignal.com (or similar domain)
- [ ] Update Google OAuth console app name to StorySignal
- [ ] Update Google OAuth redirect URIs for new domain
- [ ] Consider renaming Cloud Run service from `nextup` to `storysignal`

---

## Active / In Progress

### My Taste Visual Redesign (next up)
Three shareable visual features for the My Taste page. Each should be visually striking, fun to look at, and shareable to social media (with server-side image generation like the Taste DNA share card).

**1. Signature Shelf — editable poster display**
- Large poster row (bookshelf-style) of the user's defining items
- User can edit: tap "Edit" to search/swap items, reorder by drag
- Changing signature items triggers a re-analysis of the taste profile
- Shareable: generates a "My Shelf" image card with posters + name
- Files: `taste_dna.html` (UI), new endpoint for saving custom signatures, `share_card.py` (image gen)

**2. Taste Map — genre visualization**
- Colored bubbles sized by how many items rated in each genre
- Top genres large and prominent, smaller ones around the edges
- Color-coded by media type (blue=movie, purple=TV, amber=books, green=podcast)
- Shareable: generates a visual map image
- Data source: aggregate genres from all rated MediaEntry items
- Files: new JS visualization (canvas or SVG), new share image generator

**3. Taste Timeline — how your taste evolves**
- Horizontal timeline showing rating activity over time
- Highlights streaks: "March: thriller streak" / "April: pivoted to comedies"
- Shows monthly avg rating and genre shifts
- Encourages continued rating ("your timeline grows as you rate")
- Shareable: generates a timeline image
- Data source: MediaEntry.rated_at grouped by month + genres

**Implementation order:** Signature Shelf first (most impactful, builds on existing feature), then Taste Map (new visual), then Timeline (most complex data aggregation).

**Design principles:**
- Each feature should look great as a phone screenshot
- Each has a dedicated share button → social share dialog (Facebook, X, WhatsApp, native)
- Server-side Pillow image generation for each (like the existing Taste DNA card)
- The visuals should make people say "I want one of those" — that's the viral hook

---

### Quiz Pool Expansion (started 2026-04-14)
- Expand movie pool from 93 to ~100 items with mainstream/comfort titles
- Expand TV pool to ~80-100 with comfort TV, cooking shows, reality
- Expand fiction pool to ~50 with romance, beach reads, thrillers
- Expand nonfiction pool to ~25 with self-help, memoir, food writing
- Add adaptive stopping logic (confidence threshold → early finish at ~8-12 items)
- 6 new scene tags added: feel-good/comfort, suspense/mystery, history/war, cooking/food, self-improvement, faith/wholesome

### Quick-Add Queue Feature (starting now)
- Quick-add bar on Home page for capturing titles fast
- Floating action button (FAB) on mobile — always-visible "+" for instant capture
- "Save all" button on Discover after AI chat recommendations

---

## Scaling Plan

### Phase 1: Ready to Share Widely (1-2 weeks)
- [ ] Custom domain (register + Cloudflare setup)
- [ ] Sentry error tracking
- [ ] PWA setup (manifest.json, service worker, installable on mobile)
- [ ] Quick performance wins (preconnect hints, lazy loading, cache headers)

### Phase 2: Ready for Paying Users (1-2 months)
- [ ] CI/CD pipeline (GitHub Actions → Cloud Run)
- [ ] Basic test coverage (auth, CRUD, recs, cache)
- [ ] Stripe subscription integration (free tier + pro tier)
- [ ] Email system (Resend — welcome, digest, subscription emails)
- [ ] Build Tailwind locally (300KB CDN → 15KB purged)
- [ ] Rate limiting (slowapi)

### Phase 3: Scale (3-6 months)
- [ ] Enhanced PWA (push notifications, offline sync, share targets)
- [ ] Social features (public profiles, shareable collections, OG previews)
- [ ] Redis cache for multi-instance Cloud Run
- [ ] Advanced monitoring + alerting
- [ ] Performance optimization (shared httpx clients, background tasks)
- [ ] Database evaluation (Supabase Pro vs Cloud SQL)
- [ ] Native mobile app evaluation (enhanced PWA vs React Native)

---

## Recommendation Engine Evolution

### Phase 1: Outcome Tracking (DONE — deployed)
- [x] `rec_events` table: logs every item shown + which surface + predicted_rating
- [x] Impression logging on best_bet and theme surfaces
- [x] Outcome recording: saved, started, consumed, dismissed + user_rating
- [x] Feedback block injected into home_bundle and best_bet prompts
- [ ] Add impression logging to top_picks, related_items, new_releases surfaces
- [ ] Dashboard/query to measure hit rate per surface (% saved, % dismissed, avg user_rating)

### Phase 2: Feedback-Driven Calibration (next 2-4 weeks)
- [ ] Analyze accumulated outcome data: which surfaces have best hit rates?
- [ ] Weight rec_feedback block more heavily once data volume is meaningful (~100+ outcomes)
- [ ] Track "predicted_rating vs actual user_rating" accuracy — how well is the AI calibrated?
- [ ] Add "recs that were saved but never rated" as a signal (aspiration vs reality gap)
- [ ] Surface-level tuning: if theme_tonight_binge has 80% dismiss rate, investigate prompt quality

### Phase 3: Item Embeddings & Retrieval (4-8 weeks out)
- [ ] Compute embeddings for all items in users' libraries (Gemini embedding API or sentence-transformers)
- [ ] Build nearest-neighbor index (FAISS or pgvector in Supabase)
- [ ] Retrieve-then-rank: pull 50 nearest items to user's top-rated, then ask AI to pick + explain
- [ ] Replace "AI generates titles from memory" with "AI selects from real candidate pool"
- [ ] Expected improvements: fewer hallucinated titles, better thematic matches, lower API cost

### Phase 4: Collaborative Filtering (when user base supports it — 50+ active users)
- [ ] Item-item co-occurrence matrix from media_entries (users who rated X highly also rated Y)
- [ ] Taste cluster identification from overlapping profiles
- [ ] Blend collaborative signal into existing AI prompts: "statistically, users like you also loved..."
- [ ] Together mode generalization: taste clusters as implicit "together" groups

---

## Feature Ideas (Backlog)

### High Priority
- **Web Share Target** — share a title FROM another app into NextUp, auto-search and offer to save
- **Weekly digest email** — "Here's what's new for you this week" with best bets + new releases
- **Public taste profiles** — shareable URL showing someone's taste DNA, top 10, themes
- **Import from Letterboxd** — CSV import for movie-heavy users
- **Notification when queued item hits streaming** — "X is now on Netflix"

### Medium Priority
- **Reading/watching progress** — "I'm on episode 4" or "page 150"
- **Recommendations with friends** — "Based on what you AND Josh both love..."
- **Seasonal/holiday collections** — AI-generated "Halloween movies for you" etc.
- **Podcast episode-level tracking** — not just the show, specific episodes
- **Dark mode share card** — match user's theme preference

### Lower Priority
- **Achievement system** — "You've rated 100 items!" milestones
- **Year in review** — Spotify Wrapped-style annual summary
- **Genre deep-dives** — "Your relationship with horror" analysis page
- **Custom lists** — beyond the AI collections, manual curation
- **API for third-party integrations** — webhooks, Zapier, etc.

---

## Completed (2026-04-13 — 2026-04-15)

- Welcome/landing page with poster grid background
- Admin panel with user management + delete
- In-app user access management (invite-only + open signup)
- Google Books as primary book API (replaced Open Library)
- Persistent DB cache (survives deploys)
- Shareable Taste DNA cards (portrait + landscape + social share buttons)
- Onboarding wizard (generation, scenes, media types)
- 6 new onboarding scene tags
- Movie quiz pool expanded from 25 → 93
- Abandoned status + "didn't finish" flow
- Auto-predicted ratings on save
- Contextual navigation teasers on Home
- Refresh buttons on Home + Discover
- Post-rating popup removed
- Security hardening (HTTPS cookies, auth on search, no email leak, XSS fixes)
- Copyright footer
- Genre depth vs exposure prompt guidance
- Practical-title awareness in AI prompts
- Recency balance in AI prompts
- Comfort rewatches in wind-down/background themes
- Book cover + description backfill via Google Books
- Detail page fix for ISBN-based books
- Taste DNA page reorganization + shareable card
- Together Mode promoted + invite link
- "What are you into right now?" prompt for empty state

---

## Monthly Cost Estimate (at scale)

| Service | Estimate |
|---------|----------|
| Cloud Run | $5-20 |
| Supabase Pro | $25 |
| Cloudflare | $0 |
| Sentry | $0 |
| Resend | $0-20 |
| Gemini API | $5-50 |
| Stripe | 2.9% + $0.30/txn |
| Domain | ~$1/mo |
| **Total** | **~$50-120/month** |

Break-even at ~15-20 paying users at $5-8/month.
