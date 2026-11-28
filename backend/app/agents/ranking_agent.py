from collections import defaultdict

from app.agents.voting_agent import vote_boost as clamped_vote_boost
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

    def build_candidate_pool(self, users: list[UserProfile], extra: list[Track] | None = None) -> list[Track]:
        by_id: dict[str, Track] = {}
        for user in users:
            for track in user.candidate_tracks:
                by_id[track.id] = track
        for track in extra or []:
            by_id.setdefault(track.id, track)
        return list(by_id.values())

    # What it does: scores every guest's candidate track for the whole room and sorts best first.
    # Catch it: "How do you rank songs for a group instead of one listener?"
    # Card: docs/cards/ranking-score.md
    def rank(self, users: list[UserProfile], votes: dict[str, int] | None = None,
             extra: list[Track] | None = None) -> list[QueueItem]:
        votes = votes or defaultdict(int)
        # STEP: pool every guest's candidate tracks plus tracks added to the queue by hand, de-duplicated by id
        candidates = self.build_candidate_pool(users, extra)
        queue: list[QueueItem] = []

        # LOOP: score each candidate against every guest
        for track in candidates:
            # STEP: affinity per guest; a guest is matched at 0.55 or more
            affinities = {u.id: user_track_affinity(track, u) for u in users}
            matched_users = [uid for uid, score in affinities.items() if score >= 0.55]
            avg_affinity = sum(affinities.values()) / max(len(affinities), 1)
            coverage = len(matched_users) / max(len(users), 1)
            vote_boost = clamped_vote_boost(votes.get(track.id, 0))

            # STEP: blend average affinity, coverage, popularity and the clamped vote boost
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

        # RETURN: best score first (the genre rerank runs after this)
        return sorted(queue, key=lambda x: x.score, reverse=True)
