from app.models.schemas import QueueItem


class FairnessAgent:
    """
    ML concept: diversity-aware reranking.
    Prevents one genre or one listener type from dominating the queue.
    """

    # What it does: reorders a score-sorted queue so no track shares a genre with the two before it, when it can.
    # Catch it: "Your ranking puts five pop songs in a row. How do you spread genres without losing the scores?"
    # Card: docs/cards/rerank.md
    def rerank(self, queue: list[QueueItem], max_same_genre_window: int = 2) -> list[QueueItem]:
        final: list[QueueItem] = []
        remaining = queue[:]

        # LOOP: pick one track per turn until none are left
        while remaining:
            selected = None
            # STEP: collect the genres of the last two picks
            recent_genres = []
            for item in final[-max_same_genre_window:]:
                recent_genres.extend([g.lower() for g in item.track.genres])

            # STEP: scan in score order for the first track with none of those genres
            for item in remaining:
                item_genres = {g.lower() for g in item.track.genres}
                if not item_genres.intersection(recent_genres):
                    selected = item
                    break

            # DECISION: nothing qualifies, so take the best-scored track anyway
            if selected is None:
                selected = remaining[0]

            final.append(selected)
            remaining.remove(selected)

        # RETURN: same tracks, genre-spread order
        return final


def reorder_after_vote(queue: list[QueueItem]) -> list[QueueItem]:
    """After a vote: sort by the new scores, then apply the same genre rerank as Generate Queue.

    Sorting alone (the old vote path) threw away the rerank, so one vote brought back
    long same-genre runs; see benchmarks/results/fairness.md, row after_vote_sort_only.
    """
    return FairnessAgent().rerank(sorted(queue, key=lambda x: x.score, reverse=True))
