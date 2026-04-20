"""Tests for app.recommenders.tonight — the Tonight hero pick logic."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.recommenders.tonight import (
    MIN_SIGNAL_SCORE,
    _build_reason,
    _entry_to_media_result,
    _fmt_rating,
    _truncate,
    build_tonight,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(id: int = 1, name: str = "Leann") -> MagicMock:
    user = MagicMock()
    user.id = id
    user.name = name
    return user


def _make_entry(
    id: int = 100,
    user_id: int = 1,
    external_id: str = "tt1234",
    source: str = "tmdb",
    title: str = "Test Movie",
    media_type: str = "movie",
    status: str = "want_to_consume",
    rating: float | None = None,
    predicted_rating: float | None = 4.5,
    creator: str | None = "Denis Villeneuve",
    genres: str | None = "Sci-Fi, Drama",
    image_url: str | None = "https://image.tmdb.org/t/p/w500/test.jpg",
    year: int | None = 2024,
    description: str | None = "A great film",
    created_at: datetime | None = None,
    rated_at: datetime | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.id = id
    entry.user_id = user_id
    entry.external_id = external_id
    entry.source = source
    entry.title = title
    entry.media_type = media_type
    entry.status = status
    entry.rating = rating
    entry.predicted_rating = predicted_rating
    entry.creator = creator
    entry.genres = genres
    entry.image_url = image_url
    entry.year = year
    entry.description = description
    entry.created_at = created_at or datetime.utcnow()
    entry.rated_at = rated_at
    return entry


class FakeQuery:
    """Chainable mock that simulates SQLAlchemy's db.query().filter().all() pattern."""

    def __init__(self, results=None):
        self._results = results or []

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def all(self):
        return self._results

    def first(self):
        return self._results[0] if self._results else None


# ---------------------------------------------------------------------------
# Tests: build_tonight
# ---------------------------------------------------------------------------

class TestBuildTonight:
    """Integration-level tests for the main build_tonight entry point."""

    def test_no_unrated_candidates_returns_none(self):
        """No queue items at all → None."""
        user = _make_user()
        db = MagicMock()
        # First query returns empty (no queue items), rest return empty too
        db.query.return_value = FakeQuery([])

        result = build_tonight(user, db)
        assert result is None

    def test_no_candidates_above_threshold_returns_none(self):
        """Queue items exist but predicted_rating too low → None."""
        user = _make_user()
        low_item = _make_entry(predicted_rating=3.0)  # signal_score = 6.0 < 7.5

        db = MagicMock()
        db.query.return_value = FakeQuery([low_item])

        result = build_tonight(user, db)
        assert result is None

    def test_one_strong_candidate_returns_it(self):
        """Single qualifying item with a genre anchor → returned."""
        user = _make_user()
        candidate = _make_entry(
            id=1, predicted_rating=4.5, genres="Sci-Fi, Drama", creator=None
        )
        anchor = _make_entry(
            id=2, user_id=1, status="consumed", rating=5.0,
            title="Blade Runner 2049", genres="Sci-Fi, Thriller",
            rated_at=datetime.utcnow(),
        )

        call_count = [0]
        def fake_query(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # _get_candidates: queue items
                return FakeQuery([candidate])
            # creator=None so _try_creator_reason returns early (no query)
            if call_count[0] == 2:
                # _try_genre_reason: rated items for genre matching
                return FakeQuery([anchor])
            return FakeQuery([])

        db = MagicMock()
        db.query.side_effect = fake_query

        with patch("app.recommenders.tonight._get_provider_names", return_value=["Netflix"]):
            result = build_tonight(user, db)

        assert result is not None
        assert result.item.title == "Test Movie"
        assert result.item.signal_score == 9.0  # 4.5 * 2
        assert len(result.reason) <= 140
        assert "Blade Runner 2049" in result.reason
        assert "Netflix" in result.providers

    def test_multiple_candidates_picks_highest_signal(self):
        """Multiple items above threshold → highest predicted_rating wins."""
        user = _make_user()
        weak = _make_entry(id=1, title="Good Movie", predicted_rating=4.0)
        strong = _make_entry(id=2, title="Great Movie", predicted_rating=4.8)

        anchor = _make_entry(
            id=10, status="consumed", rating=5.0,
            title="Interstellar", genres="Sci-Fi, Drama",
        )

        call_count = [0]
        def fake_query(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeQuery([weak, strong])
            if call_count[0] == 2:
                # creator match
                return FakeQuery([])
            if call_count[0] == 3:
                # genre match
                return FakeQuery([anchor])
            return FakeQuery([])

        db = MagicMock()
        db.query.side_effect = fake_query

        with patch("app.recommenders.tonight._get_provider_names", return_value=[]):
            result = build_tonight(user, db)

        assert result is not None
        assert result.item.title == "Great Movie"
        assert result.item.signal_score == 9.6  # 4.8 * 2

    def test_reason_mentions_real_anchor(self):
        """The reason string references a specific title or creator from the profile."""
        user = _make_user()
        candidate = _make_entry(
            id=1, predicted_rating=4.5, creator="Christopher Nolan"
        )
        creator_match = _make_entry(
            id=5, status="consumed", rating=5.0,
            title="The Dark Knight", creator="Christopher Nolan",
        )

        call_count = [0]
        def fake_query(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeQuery([candidate])
            if call_count[0] == 2:
                # creator match query
                return FakeQuery([creator_match])
            return FakeQuery([])

        db = MagicMock()
        db.query.side_effect = fake_query

        with patch("app.recommenders.tonight._get_provider_names", return_value=[]):
            result = build_tonight(user, db)

        assert result is not None
        assert "The Dark Knight" in result.reason
        assert len(result.reason) <= 140


# ---------------------------------------------------------------------------
# Tests: _build_reason
# ---------------------------------------------------------------------------

class TestBuildReason:

    def test_creator_reason_single_match(self):
        user = _make_user()
        entry = _make_entry(creator="Nolan")
        anchor = _make_entry(
            id=5, status="consumed", rating=5.0,
            title="Inception", creator="Nolan",
        )

        call_count = [0]
        def fake_query(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeQuery([anchor])
            return FakeQuery([])

        db = MagicMock()
        db.query.side_effect = fake_query

        reason = _build_reason(entry, user, db)
        assert reason is not None
        assert "Inception" in reason
        assert "5" in reason
        assert len(reason) <= 140

    def test_creator_reason_multiple_matches(self):
        user = _make_user()
        entry = _make_entry(creator="Nolan")
        match1 = _make_entry(id=5, status="consumed", rating=5.0, title="Inception", creator="Nolan")
        match2 = _make_entry(id=6, status="consumed", rating=4.5, title="Interstellar", creator="Nolan")

        call_count = [0]
        def fake_query(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeQuery([match1, match2])
            return FakeQuery([])

        db = MagicMock()
        db.query.side_effect = fake_query

        reason = _build_reason(entry, user, db)
        assert reason is not None
        assert "2 titles" in reason
        assert len(reason) <= 140

    def test_genre_reason_cites_anchor_title(self):
        user = _make_user()
        # creator=None so _try_creator_reason returns early (no query)
        entry = _make_entry(creator=None, genres="Drama, Thriller")
        anchor = _make_entry(
            id=10, status="consumed", rating=4.5,
            title="Parasite", genres="Drama, Comedy",
        )

        call_count = [0]
        def fake_query(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeQuery([anchor])  # genre (first query since creator is skipped)
            return FakeQuery([])

        db = MagicMock()
        db.query.side_effect = fake_query

        reason = _build_reason(entry, user, db)
        assert reason is not None
        assert "Parasite" in reason
        assert "drama" in reason.lower()
        assert len(reason) <= 140

    def test_no_signals_returns_none(self):
        user = _make_user()
        entry = _make_entry(creator=None, genres=None)

        db = MagicMock()
        db.query.return_value = FakeQuery([])

        reason = _build_reason(entry, user, db)
        assert reason is None


# ---------------------------------------------------------------------------
# Tests: helpers
# ---------------------------------------------------------------------------

class TestHelpers:

    def test_entry_to_media_result_maps_fields(self):
        entry = _make_entry(genres="Sci-Fi, Drama")
        result = _entry_to_media_result(entry, 9.0)
        assert result.external_id == "tt1234"
        assert result.source == "tmdb"
        assert result.title == "Test Movie"
        assert result.signal_score == 9.0
        assert result.genres == ["Sci-Fi", "Drama"]

    def test_entry_to_media_result_no_genres(self):
        entry = _make_entry(genres=None)
        result = _entry_to_media_result(entry, 8.0)
        assert result.genres == []

    def test_fmt_rating_integer(self):
        assert _fmt_rating(5.0) == "5"
        assert _fmt_rating(4.0) == "4"

    def test_fmt_rating_decimal(self):
        assert _fmt_rating(4.5) == "4.5"
        assert _fmt_rating(3.7) == "3.7"

    def test_fmt_rating_none(self):
        assert _fmt_rating(None) == "?"

    def test_truncate_short_string(self):
        assert _truncate("Hello", 140) == "Hello"

    def test_truncate_long_string(self):
        long_str = "A" * 200
        result = _truncate(long_str, 140)
        assert len(result) == 140
        assert result.endswith("\u2026")

    def test_truncate_exact_length(self):
        s = "A" * 140
        assert _truncate(s, 140) == s
