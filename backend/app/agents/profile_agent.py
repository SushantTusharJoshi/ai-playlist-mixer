from app.models.schemas import UserProfile


class ProfileAgent:
    """
    Converts raw Spotify or dummy profile data into a normalized UserProfile.
    Later: add Spotify Web API parsing here.
    """

    def normalize_dummy_user(self, user: UserProfile) -> UserProfile:
        user.top_genres = [g.lower().strip() for g in user.top_genres]
        user.top_artists = [a.strip() for a in user.top_artists]
        return user
