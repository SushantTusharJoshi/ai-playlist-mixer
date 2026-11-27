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

    # What it does: records one voter's up/down choice on a track and returns how far the net count moved.
    # Catch it: "How do you stop one guest from voting a track to the top?"
    # Card: docs/cards/vote.md
    def vote(self, party: PartySession, track_id: str, value: int, voter: str) -> int:
        # DECISION: only +1 or -1 is a vote
        if value not in (-1, 1):
            raise ValueError("vote value must be -1 or 1")
        # STEP: look up this voter's current choice on this track
        key = f"{voter}|{track_id}"
        previous = party.vote_choices.get(key, 0)
        # DECISION: the same choice again is a duplicate, not a second vote
        if previous == value:
            raise ValueError("duplicate_vote")
        # STEP: replace the choice, so the net count moves by the difference
        party.vote_choices[key] = value
        delta = value - previous
        party.votes[track_id] = party.votes.get(track_id, 0) + delta
        # RETURN: 1 for a new vote, 2 for a switch
        return delta

    def get_votes(self, party: PartySession) -> dict[str, int]:
        return dict(party.votes)
