"""Tests for pure ML feature functions."""
from __future__ import annotations

from app.ml.features import cluster_guests, genre_overlap, party_vector, user_track_affinity
from app.models.schemas import Track, UserProfile


def _track(**kw) -> Track:
    defaults = dict(id="t1", name="Song", artist="Artist", genres=["pop"], energy=0.7, danceability=0.7, popularity=0.8)
    defaults.update(kw)
    return Track(**defaults)


def _user(**kw) -> UserProfile:
    defaults = dict(
        id="u1",
        display_name="Test",
        source="custom",
        genre="pop",
        top_genres=["pop", "dance pop"],
        preferred_energy=0.75,
        preferred_danceability=0.78,
    )
    defaults.update(kw)
    return UserProfile(**defaults)


# ── genre_overlap ────────────────────────────────


def test_genre_overlap_matching():
    t = _track(genres=["pop", "dance pop"])
    u = _user(top_genres=["pop", "dance pop", "synth pop"])
    score = genre_overlap(t, u)
    # Jaccard: intersection=2, union=3 -> 2/3
    assert abs(score - 2 / 3) < 1e-9


def test_genre_overlap_disjoint():
    t = _track(genres=["rock", "alternative"])
    u = _user(top_genres=["pop", "dance pop"])
    score = genre_overlap(t, u)
    assert score == 0.0


# ── user_track_affinity ──────────────────────────


def test_user_track_affinity_returns_score():
    t = _track()
    u = _user()
    score = user_track_affinity(t, u)
    assert 0.0 <= score <= 1.5  # Generous upper bound because of the popularity component


def test_user_track_affinity_higher_for_matching_genre():
    t_match = _track(genres=["pop", "dance pop"])
    t_mismatch = _track(genres=["metal", "punk"], id="t2")
    u = _user()
    assert user_track_affinity(t_match, u) > user_track_affinity(t_mismatch, u)


# ── party_vector ─────────────────────────────────


def test_party_vector_single_user():
    u = _user(preferred_energy=0.8, preferred_danceability=0.6)
    vec = party_vector([u])
    assert abs(vec[0] - 0.8) < 1e-9
    assert abs(vec[1] - 0.6) < 1e-9


def test_party_vector_multiple_users():
    u1 = _user(id="u1", preferred_energy=0.8, preferred_danceability=0.6)
    u2 = _user(id="u2", preferred_energy=0.4, preferred_danceability=0.9)
    vec = party_vector([u1, u2])
    assert abs(vec[0] - 0.6) < 1e-9   # mean energy
    assert abs(vec[1] - 0.75) < 1e-9  # mean danceability


# ── cluster_guests ───────────────────────────────


def test_cluster_guests_single_user():
    u = _user()
    result = cluster_guests([u])
    assert result["n_clusters"] == 1
    assert u.id in result["clusters"][0]


def test_cluster_guests_multiple_users():
    users = [
        _user(id="u1", top_genres=["pop", "dance pop"], preferred_energy=0.9),
        _user(id="u2", top_genres=["rock", "alternative"], preferred_energy=0.3),
        _user(id="u3", top_genres=["pop", "synth pop"], preferred_energy=0.85),
    ]
    result = cluster_guests(users)
    assert result["n_clusters"] >= 2
    # Every user should appear in exactly one cluster
    all_members = []
    for members in result["clusters"].values():
        all_members.extend(members)
    assert sorted(all_members) == sorted(["u1", "u2", "u3"])
