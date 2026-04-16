# NextUp

A personal media recommendation engine that learns how you engage with movies, TV, books, and podcasts — then connects the dots across all of them.

## Tech Stack

- **Backend:** Python 3.11 + FastAPI
- **Frontend:** Jinja2 templates + vanilla JavaScript + Tailwind CSS
- **Database:** PostgreSQL (Supabase) via SQLAlchemy
- **AI:** Google Gemini (recommendations, taste analysis, predicted ratings)
- **Auth:** Google OAuth 2.0
- **Hosting:** Google Cloud Run
- **Image gen:** Pillow (shareable Taste DNA cards)

## Local Development

### Prerequisites

- Python 3.11+
- A Google Cloud project with OAuth credentials
- A Supabase project (or local PostgreSQL)
- API keys for: Gemini, TMDB, Google Books, NYT Books

### Setup

```bash
# Clone the repo
git clone git@github.com:klfowler-prog/Rec-app.git
cd Rec-app

# Create a virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and fill in environment variables
cp .env.example .env
# Edit .env with your API keys (see Environment Variables below)

# Run locally
uvicorn app.main:app --reload --port 8000
```

The app will be available at `http://localhost:8000`.

### Environment Variables

Create a `.env` file in the project root with these values:

```
# AI
GEMINI_API_KEY=your_gemini_api_key

# Media APIs
TMDB_API_KEY=your_tmdb_bearer_token
GOOGLE_BOOKS_API_KEY=your_google_books_api_key
NYT_API_KEY=your_nyt_api_key

# Google OAuth
GOOGLE_CLIENT_ID=your_oauth_client_id
GOOGLE_CLIENT_SECRET=your_oauth_client_secret

# Database (omit for local SQLite)
DATABASE_URL=postgresql://user:pass@host:port/dbname

# Session secret (use a random string in production)
SECRET_KEY=your_secret_key

# Admin
ADMIN_EMAIL=your_email@gmail.com
INVITE_ONLY=false
```

If `DATABASE_URL` is not set, the app uses a local SQLite database (`rec.db`).

## Deployment (Google Cloud Run)

### Prerequisites

- [Google Cloud SDK](https://cloud.google.com/sdk/docs/install) installed and authenticated
- A Google Cloud project (ours: `nextup-493018`)
- Cloud Run API enabled

### Deploy

```bash
# Make sure you're on the main branch with latest changes
git checkout main
git pull origin main

# Deploy to Cloud Run
gcloud run deploy nextup --source . --region us-central1 --quiet
```

This builds a Docker container from the source, pushes it to Google Container Registry, and deploys a new revision to Cloud Run. Takes about 2-3 minutes.

### Setting Environment Variables on Cloud Run

To add or update a single variable without affecting others:

```bash
gcloud run services update nextup --region us-central1 \
  --update-env-vars "KEY=value" --quiet
```

To set multiple variables:

```bash
gcloud run services update nextup --region us-central1 \
  --update-env-vars "KEY1=value1,KEY2=value2" --quiet
```

**Important:** Use `--update-env-vars` (not `--set-env-vars`) to add/change variables without wiping existing ones.

To view current variables:

```bash
gcloud run services describe nextup --region us-central1 \
  --format="value(spec.template.spec.containers[0].env)"
```

### Google OAuth Setup

The OAuth redirect URI must be configured in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials):

- For production: `https://your-cloud-run-url/auth/callback`
- For local dev: `http://localhost:8000/auth/callback`

### APIs to Enable

In your Google Cloud project, enable:
- Books API (`books.googleapis.com`)
- Generative Language API (for Gemini)

## Git Workflow

```bash
# For small changes, work directly on main
git add .
git commit -m "description of change"
git push origin main
gcloud run deploy nextup --source . --region us-central1 --quiet

# For bigger features, use a branch
git checkout -b my-feature
# ... make changes ...
git checkout main
git merge my-feature
git push origin main
gcloud run deploy nextup --source . --region us-central1 --quiet
```

## Project Structure

```
Rec-app/
  app/
    main.py              # FastAPI app entry point
    config.py            # Settings from environment variables
    database.py          # SQLAlchemy engine + session
    models.py            # 9 database models
    auth.py              # Google OAuth dependency
    cache.py             # Two-tier cache (memory + DB)
    schemas.py           # Pydantic request/response models
    routers/
      media.py           # Search, quizzes, recs, best bets (31 endpoints)
      pages.py           # All page routes (25 endpoints)
      profile.py         # Library CRUD, ratings, imports (16 endpoints)
      together.py        # Taste comparison + shared picks
      collections.py     # AI-generated collections
      auth.py            # Login/logout/callback
      admin.py           # User management
      recommend.py       # SSE streaming recommendations
    services/
      gemini.py          # Gemini API client
      recommendation.py  # Taste profile builder + streaming
      unified_search.py  # Aggregated search (TMDB + Google Books + iTunes)
      tmdb.py            # Movies + TV
      google_books.py    # Books (primary)
      open_library.py    # Books (fallback)
      itunes.py          # Podcasts
      nyt_books.py       # NYT bestsellers
      share_card.py      # Pillow image generation
      *_taste_quiz.py    # Quiz data + scoring (movies, TV, books)
      taste_quiz_scoring.py  # Generic scoring engine
    templates/           # 24 Jinja2 HTML templates
  static/
    js/                  # 8 vanilla JS files
    img/                 # Logo and static images
    css/                 # App styles
  Dockerfile             # Cloud Run container definition
  requirements.txt       # Python dependencies
  ROADMAP.md             # Feature roadmap and scaling plan
  .env                   # Local environment variables (not committed)
```

## Useful Commands

```bash
# Check what's deployed
gcloud run services describe nextup --region us-central1 --format="value(status.latestReadyRevisionName)"

# View recent logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nextup" --limit 20 --format="value(timestamp,textPayload)"

# View errors only
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nextup AND severity>=ERROR" --limit 10 --format="value(timestamp,textPayload)"

# Bust recommendation caches
curl -X POST https://your-cloud-run-url/api/media/refresh-recommendations
```

## Copyright

Copyright 2026 Leann Fowler. All rights reserved.
