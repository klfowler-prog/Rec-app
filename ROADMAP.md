# NextUp Roadmap

## Active / In Progress

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
