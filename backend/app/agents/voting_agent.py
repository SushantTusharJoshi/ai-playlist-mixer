from app.models.schemas import PartySession

VOTE_CAP = 5          # votes beyond +/-5 stop moving a track
VOTE_WEIGHT = 0.04    # score change per counted vote


def vote_boost(votes: int) -> float:
    """Score boost for a net vote count, clamped to +/- VOTE_CAP votes."""
    return min(max(votes, -VOTE_CAP), VOTE_CAP) * VOTE_WEIGHT


class VotingAgent:
    """
    Handles session feedback. Votes live on the PartySession so they are
    saved and restored with the rest of the room.

    Each voter (a guest key or the host) holds one choice per track: +1 or -1.
    Voting the same way twice is rejected; switching from +1 to -1 moves the
    net count by 2. So one voter can move a track by at most one vote.

    Later this can become an online learning layer:
    - epsilon-greedy bandit
    - Thompson sampling
    - logistic model trained from votes/skips
    """

    def has_voted(self, party: PartySession, voter: str, track_id: str, value: int | None = None) -> bool:
        current = party.vote_choices.get(f"{voter}|{track_id}")
        if value is None:
            return current is not None
        return current == value

    def vote(self, party: PartySession, track_id: str, value: int, voter: str) -> int:
        if value not in (-1, 1):
            raise ValueError("vote value must be -1 or 1")
        key = f"{voter}|{track_id}"
        previous = party.vote_choices.get(key, 0)
        if previous == value:
            raise ValueError("duplicate_vote")
        party.vote_choices[key] = value
        delta = value - previous
        party.votes[track_id] = party.votes.get(track_id, 0) + delta
        return delta

    def get_votes(self, party: PartySession) -> dict[str, int]:
        return dict(party.votes)
