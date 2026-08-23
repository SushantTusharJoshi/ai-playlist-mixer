from collections import defaultdict


class VotingAgent:
    """
    Handles session feedback. Later this can become an online learning layer:
    - epsilon-greedy bandit
    - Thompson sampling
    - logistic model trained from votes/skips
    """

    def __init__(self) -> None:
        self.votes_by_party: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # Track which users voted on which tracks: {party: {(user_id, track_id)}}
        self.user_votes: dict[str, set[tuple[str, str]]] = defaultdict(set)

    def has_voted(self, party_code: str, user_id: str, track_id: str) -> bool:
        return (user_id, track_id) in self.user_votes[party_code]

    def vote(self, party_code: str, track_id: str, value: int, voted_by: str = "") -> dict[str, int]:
        if value not in (-1, 1):
            raise ValueError("vote value must be -1 or 1")
        if voted_by:
            if self.has_voted(party_code, voted_by, track_id):
                raise ValueError("duplicate_vote")
            self.user_votes[party_code].add((voted_by, track_id))
        self.votes_by_party[party_code][track_id] += value
        return dict(self.votes_by_party[party_code])

    def get_votes(self, party_code: str) -> dict[str, int]:
        return dict(self.votes_by_party[party_code])
