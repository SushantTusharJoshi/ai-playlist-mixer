from collections import defaultdict

from app.ml.features import user_track_affinity
from app.models.schemas import QueueItem, Track, UserProfile


class RankingAgent:
    """
    Hybrid recommender baseline:
    - content-based affinity
    - multi-user coverage
    - popularity
    - vote updates
    Later: swap this with LambdaMART / LightGBMRanker / contextual bandit.
    """

    def build_candidate_pool(self, users: list[UserProfile]) -> list[Track]:
        by_id: dict[str, Track] = {}
        for user in users:
            for track in user.candidate_tracks:
                by_id[track.id] = track
        return list(by_id.values())

    def rank(self, users: list[UserProfile], votes: dict[str, int] | None = None) -> list[QueueItem]:
        votes = votes or defaultdict(int)
        candidates = self.build_candidate_pool(users)
        queue: list[QueueItem] = []

        for track in candidates:
            affinities = {u.id: user_track_affinity(track, u) for u in users}
            matched_users = [uid for uid, score in affinities.items() if score >= 0.55]
            avg_affinity = sum(affinities.values()) / max(len(affinities), 1)
            coverage = len(matched_users) / max(len(users), 1)
            vote_boost = min(max(votes.get(track.id, 0), -5), 5) * 0.04

            score = 0.55 * avg_affinity + 0.30 * coverage + 0.10 * track.popularity + vote_boost

            reasons = []
            if coverage >= 0.5:
                reasons.append("matches multiple guests")
            if track.popularity >= 0.85:
                reasons.append("recognizable party track")
            if vote_boost > 0:
                reasons.append("boosted by guest votes")

            queue.append(
                QueueItem(
                    track=track,
                    score=round(score, 4),
                    reasons=reasons,
                    votes=votes.get(track.id, 0),
                    matched_users=matched_users,
                )
            )

        return sorted(queue, key=lambda x: x.score, reverse=True)
