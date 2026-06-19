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

    def vote(self, party_code: str, track_id: str, value: int) -> dict[str, int]:
        if value not in (-1, 1):
            raise ValueError("vote value must be -1 or 1")
        self.votes_by_party[party_code][track_id] += value
        return dict(self.votes_by_party[party_code])

    def get_votes(self, party_code: str) -> dict[str, int]:
        return dict(self.votes_by_party[party_code])
