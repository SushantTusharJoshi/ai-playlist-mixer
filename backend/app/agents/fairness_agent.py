from app.models.schemas import QueueItem


class FairnessAgent:
    """
    ML concept: diversity-aware reranking.
    Prevents one genre or one listener type from dominating the queue.
    """

    def rerank(self, queue: list[QueueItem], max_same_genre_window: int = 2) -> list[QueueItem]:
        final: list[QueueItem] = []
        remaining = queue[:]

        while remaining:
            selected = None
            recent_genres = []
            for item in final[-max_same_genre_window:]:
                recent_genres.extend([g.lower() for g in item.track.genres])

            for item in remaining:
                item_genres = {g.lower() for g in item.track.genres}
                if not item_genres.intersection(recent_genres):
                    selected = item
                    break

            if selected is None:
                selected = remaining[0]

            final.append(selected)
            remaining.remove(selected)

        return final
