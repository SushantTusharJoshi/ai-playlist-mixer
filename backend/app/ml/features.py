"""
ML feature engineering and clustering for the playlist mixer.

This module handles all the actual ML work:
- Content-based user-track affinity scoring
- User taste vectorization
- KMeans guest clustering
- Cosine similarity between users

The LLM agent handles explanation; this module handles math.
"""
from __future__ import annotations

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics.pairwise import cosine_similarity as sklearn_cosine

from app.models.schemas import Track, UserProfile


# --- Genre vocabulary for vectorization ---
# Expand this as you add more dummy users or pull from Spotify
GENRE_VOCAB = [
    "pop", "dance pop", "r&b", "hip hop", "rap", "trap",
    "indie", "lofi", "acoustic", "edm", "house", "electro pop",
    "rock", "alternative", "bedroom pop", "synthpop", "big room",
    "latin", "reggaeton", "country", "metal", "jazz", "classical",
    "soul", "funk", "punk", "k-pop",
]


def genre_overlap(track: Track, user: UserProfile) -> float:
    """Jaccard similarity between track genres and user genre preferences."""
    track_genres = {g.lower() for g in track.genres}
    user_genres = {g.lower() for g in user.top_genres}
    if not track_genres or not user_genres:
        return 0.0
    return len(track_genres & user_genres) / len(track_genres | user_genres)


def user_track_affinity(track: Track, user: UserProfile) -> float:
    """
    Content-based recommendation score.
    Transparent baseline before training a ranking model.

    Weights:
      50% genre overlap (Jaccard)
      25% energy proximity
      20% danceability proximity
       5% raw popularity
    """
    genre_score = genre_overlap(track, user)
    energy_score = 1 - abs(track.energy - user.preferred_energy)
    dance_score = 1 - abs(track.danceability - user.preferred_danceability)

    return float(
        0.50 * genre_score
        + 0.25 * energy_score
        + 0.20 * dance_score
        + 0.05 * track.popularity
    )


def party_vector(users: list[UserProfile]) -> np.ndarray:
    """Aggregate user taste into a session-level vector."""
    if not users:
        return np.array([0.5, 0.5])
    return np.array([
        np.mean([u.preferred_energy for u in users]),
        np.mean([u.preferred_danceability for u in users]),
    ])


# --- New: Vectorization and Clustering ---

def user_to_vector(user: UserProfile) -> np.ndarray:
    """
    Convert a user profile to a feature vector.
    Dimensions: [energy, danceability, genre_1, genre_2, ..., genre_n]

    This is the vector the ranking agent's doc describes:
    user_vector = [energy, danceability, pop_affinity, hiphop_affinity, ...]
    """
    genre_vec = [
        1.0 if g in [x.lower() for x in user.top_genres] else 0.0
        for g in GENRE_VOCAB
    ]
    return np.array(
        [user.preferred_energy, user.preferred_danceability] + genre_vec,
        dtype=np.float64,
    )


def cluster_guests(
    users: list[UserProfile], max_clusters: int = 3
) -> dict:
    """
    KMeans clustering on user taste vectors.

    Returns:
        {
            "clusters": {0: ["pop-listener", ...], 1: ["chill-listener", ...]},
            "n_clusters": 2,
            "labels": {"pop-listener": 0, "chill-listener": 1, ...},
            "cluster_genres": {0: ["pop", "dance pop"], 1: ["indie", "lofi"]},
        }
    """
    if len(users) < 2:
        return {
            "clusters": {0: [u.id for u in users]},
            "n_clusters": 1,
            "labels": {users[0].id: 0} if users else {},
            "cluster_genres": {0: users[0].top_genres if users else []},
        }

    vectors = np.array([user_to_vector(u) for u in users])
    k = min(max_clusters, len(users))

    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    raw_labels = km.fit_predict(vectors)

    clusters: dict[int, list[str]] = {}
    labels: dict[str, int] = {}
    for i, user in enumerate(users):
        label = int(raw_labels[i])
        labels[user.id] = label
        clusters.setdefault(label, []).append(user.id)

    # Identify dominant genres per cluster
    cluster_genres: dict[int, list[str]] = {}
    for label, member_ids in clusters.items():
        genre_counts: dict[str, int] = {}
        for uid in member_ids:
            user = next(u for u in users if u.id == uid)
            for g in user.top_genres:
                genre_counts[g] = genre_counts.get(g, 0) + 1
        top = sorted(genre_counts, key=genre_counts.get, reverse=True)[:3]
        cluster_genres[label] = top

    return {
        "clusters": clusters,
        "n_clusters": k,
        "labels": labels,
        "cluster_genres": cluster_genres,
    }


def user_similarity_matrix(users: list[UserProfile]) -> dict:
    """
    Cosine similarity between all pairs of users.
    Useful for the LLM agent to explain taste overlap.
    """
    if len(users) < 2:
        return {"matrix": [], "ids": [u.id for u in users]}

    vectors = np.array([user_to_vector(u) for u in users])
    sim = sklearn_cosine(vectors)

    return {
        "matrix": sim.tolist(),
        "ids": [u.id for u in users],
    }
