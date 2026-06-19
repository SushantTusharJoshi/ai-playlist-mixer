"""
Large track catalog organized by genre + genre profile defaults.
Users pick ONE genre and get matched with tracks from that genre's pool.
"""
from app.models.schemas import PartySession, Track

PARTIES: dict[str, PartySession] = {}

# Genre defaults: when a user picks a genre, they get these energy/danceability prefs
GENRE_DEFAULTS: dict[str, dict] = {
    "pop":        {"energy": 0.75, "danceability": 0.78, "related": ["pop", "dance pop", "synth pop", "indie pop"]},
    "hip hop":    {"energy": 0.82, "danceability": 0.74, "related": ["hip hop", "rap", "trap", "pop rap"]},
    "r&b":        {"energy": 0.52, "danceability": 0.62, "related": ["r&b", "soul", "neo soul"]},
    "rock":       {"energy": 0.78, "danceability": 0.55, "related": ["rock", "alternative", "indie rock", "psychedelic"]},
    "edm":        {"energy": 0.90, "danceability": 0.84, "related": ["edm", "house", "electro", "dance"]},
    "indie":      {"energy": 0.48, "danceability": 0.52, "related": ["indie", "bedroom pop", "lofi", "acoustic", "alternative"]},
    "latin":      {"energy": 0.80, "danceability": 0.88, "related": ["reggaeton", "latin pop", "latin trap"]},
    "k-pop":      {"energy": 0.84, "danceability": 0.82, "related": ["k-pop", "dance pop", "pop"]},
    "country":    {"energy": 0.65, "danceability": 0.60, "related": ["country", "country pop", "folk"]},
    "jazz":       {"energy": 0.40, "danceability": 0.45, "related": ["jazz", "smooth jazz", "soul"]},
}

AVAILABLE_GENRES = list(GENRE_DEFAULTS.keys())

# Master track catalog: ~100 tracks across genres
TRACK_CATALOG: dict[str, Track] = {}

_RAW_TRACKS = [
    # --- Pop (15) ---
    ("p01", "Levitating", "Dua Lipa", ["pop", "dance pop"], 0.82, 0.86, 0.95),
    ("p02", "Blinding Lights", "The Weeknd", ["pop", "synth pop"], 0.78, 0.70, 0.96),
    ("p03", "Cruel Summer", "Taylor Swift", ["pop"], 0.74, 0.66, 0.94),
    ("p04", "As It Was", "Harry Styles", ["pop", "synth pop"], 0.73, 0.70, 0.95),
    ("p05", "Shape of You", "Ed Sheeran", ["pop", "dance pop"], 0.65, 0.82, 0.97),
    ("p06", "Anti-Hero", "Taylor Swift", ["pop", "indie pop"], 0.64, 0.64, 0.93),
    ("p07", "Watermelon Sugar", "Harry Styles", ["pop"], 0.82, 0.76, 0.91),
    ("p08", "Stay", "The Kid LAROI & Justin Bieber", ["pop", "dance pop"], 0.76, 0.74, 0.93),
    ("p09", "Flowers", "Miley Cyrus", ["pop", "dance pop"], 0.68, 0.80, 0.94),
    ("p10", "Espresso", "Sabrina Carpenter", ["pop", "dance pop"], 0.72, 0.82, 0.92),
    ("p11", "drivers license", "Olivia Rodrigo", ["pop"], 0.44, 0.56, 0.91),
    ("p12", "good 4 u", "Olivia Rodrigo", ["pop", "pop punk"], 0.86, 0.68, 0.90),
    ("p13", "Uptown Funk", "Bruno Mars", ["pop", "funk"], 0.90, 0.88, 0.95),
    ("p14", "Shake It Off", "Taylor Swift", ["pop", "dance pop"], 0.84, 0.82, 0.93),
    ("p15", "Attention", "Charlie Puth", ["pop", "synth pop"], 0.72, 0.76, 0.88),
    # --- Hip Hop (12) ---
    ("h01", "HUMBLE.", "Kendrick Lamar", ["hip hop", "rap"], 0.80, 0.91, 0.90),
    ("h02", "SICKO MODE", "Travis Scott", ["hip hop", "trap"], 0.73, 0.83, 0.92),
    ("h03", "God's Plan", "Drake", ["rap", "pop rap"], 0.45, 0.75, 0.88),
    ("h04", "Money Trees", "Kendrick Lamar", ["hip hop", "rap"], 0.62, 0.72, 0.85),
    ("h05", "In Da Club", "50 Cent", ["hip hop", "rap"], 0.87, 0.90, 0.89),
    ("h06", "Lose Yourself", "Eminem", ["hip hop", "rap"], 0.88, 0.72, 0.92),
    ("h07", "Hotline Bling", "Drake", ["rap", "pop rap"], 0.52, 0.82, 0.91),
    ("h08", "POWER", "Kanye West", ["hip hop", "rap"], 0.78, 0.68, 0.87),
    ("h09", "All The Stars", "Kendrick Lamar & SZA", ["hip hop", "r&b"], 0.56, 0.68, 0.88),
    ("h10", "Not Like Us", "Kendrick Lamar", ["hip hop", "rap"], 0.82, 0.86, 0.93),
    ("h11", "Mask Off", "Future", ["trap", "hip hop"], 0.66, 0.84, 0.87),
    ("h12", "Starboy", "The Weeknd & Daft Punk", ["pop rap", "hip hop"], 0.68, 0.72, 0.92),
    # --- R&B (10) ---
    ("r01", "Kill Bill", "SZA", ["r&b", "pop"], 0.65, 0.70, 0.93),
    ("r02", "Thinkin Bout You", "Frank Ocean", ["r&b", "neo soul"], 0.35, 0.52, 0.86),
    ("r03", "Earned It", "The Weeknd", ["r&b", "pop"], 0.42, 0.58, 0.90),
    ("r04", "Snooze", "SZA", ["r&b", "soul"], 0.50, 0.60, 0.88),
    ("r05", "best part", "Daniel Caesar ft. H.E.R.", ["r&b", "neo soul"], 0.30, 0.55, 0.84),
    ("r06", "Redbone", "Childish Gambino", ["r&b", "soul"], 0.48, 0.74, 0.88),
    ("r07", "The Hills", "The Weeknd", ["r&b", "pop"], 0.62, 0.58, 0.91),
    ("r08", "Shirt", "SZA", ["r&b"], 0.56, 0.66, 0.85),
    ("r09", "After Hours", "The Weeknd", ["r&b", "synth pop"], 0.55, 0.52, 0.87),
    ("r10", "Kiss Me More", "Doja Cat ft. SZA", ["r&b", "pop"], 0.66, 0.78, 0.90),
    # --- Rock (10) ---
    ("k01", "Do I Wanna Know?", "Arctic Monkeys", ["rock", "indie rock"], 0.68, 0.55, 0.89),
    ("k02", "The Less I Know The Better", "Tame Impala", ["rock", "psychedelic"], 0.74, 0.78, 0.90),
    ("k03", "Mr. Brightside", "The Killers", ["rock", "alternative"], 0.92, 0.52, 0.92),
    ("k04", "505", "Arctic Monkeys", ["rock", "indie rock"], 0.82, 0.48, 0.87),
    ("k05", "Bohemian Rhapsody", "Queen", ["rock"], 0.70, 0.44, 0.94),
    ("k06", "Smells Like Teen Spirit", "Nirvana", ["rock", "alternative"], 0.92, 0.56, 0.91),
    ("k07", "Under the Bridge", "Red Hot Chili Peppers", ["rock", "alternative"], 0.56, 0.48, 0.88),
    ("k08", "Somebody Told Me", "The Killers", ["rock", "alternative"], 0.88, 0.60, 0.82),
    ("k09", "Creep", "Radiohead", ["rock", "alternative"], 0.64, 0.42, 0.89),
    ("k10", "Come As You Are", "Nirvana", ["rock", "alternative"], 0.72, 0.52, 0.87),
    # --- EDM (10) ---
    ("e01", "Summer", "Calvin Harris", ["edm", "dance"], 0.88, 0.74, 0.88),
    ("e02", "Levels", "Avicii", ["edm", "house"], 0.90, 0.72, 0.86),
    ("e03", "Animals", "Martin Garrix", ["edm", "electro"], 0.94, 0.63, 0.80),
    ("e04", "Titanium", "David Guetta ft. Sia", ["edm", "electro"], 0.82, 0.58, 0.91),
    ("e05", "Don't You Worry Child", "Swedish House Mafia", ["edm", "house"], 0.85, 0.68, 0.87),
    ("e06", "Clarity", "Zedd ft. Foxes", ["edm", "electro"], 0.80, 0.62, 0.84),
    ("e07", "Lean On", "Major Lazer & DJ Snake", ["edm", "dance"], 0.76, 0.84, 0.92),
    ("e08", "Wake Me Up", "Avicii", ["edm", "house"], 0.82, 0.70, 0.90),
    ("e09", "Scared to Be Lonely", "Martin Garrix", ["edm", "electro"], 0.78, 0.66, 0.82),
    ("e10", "Faded", "Alan Walker", ["edm", "electro"], 0.64, 0.62, 0.89),
    # --- Indie (10) ---
    ("i01", "SLOW DANCING IN THE DARK", "Joji", ["indie", "r&b"], 0.37, 0.52, 0.83),
    ("i02", "Sofia", "Clairo", ["indie", "bedroom pop"], 0.54, 0.74, 0.81),
    ("i03", "Sunflower", "Rex Orange County", ["indie", "alternative"], 0.48, 0.63, 0.78),
    ("i04", "Line Without a Hook", "Ricky Montgomery", ["indie", "acoustic"], 0.42, 0.45, 0.76),
    ("i05", "Notion", "The Rare Occasions", ["indie", "alternative"], 0.68, 0.58, 0.72),
    ("i06", "Electric Feel", "MGMT", ["indie", "psychedelic"], 0.74, 0.82, 0.85),
    ("i07", "Sweater Weather", "The Neighbourhood", ["indie", "alternative"], 0.62, 0.60, 0.90),
    ("i08", "Heat Waves", "Glass Animals", ["indie", "alternative"], 0.58, 0.72, 0.92),
    ("i09", "I Wanna Be Yours", "Arctic Monkeys", ["indie", "indie rock"], 0.48, 0.52, 0.88),
    ("i10", "Two Ghosts", "Harry Styles", ["indie", "indie pop"], 0.42, 0.48, 0.80),
    # --- Latin (10) ---
    ("l01", "Dakiti", "Bad Bunny", ["reggaeton", "latin trap"], 0.76, 0.84, 0.91),
    ("l02", "Mi Gente", "J Balvin", ["reggaeton", "latin pop"], 0.88, 0.92, 0.89),
    ("l03", "DESPECHA", "Rosalia", ["latin pop", "reggaeton"], 0.82, 0.88, 0.85),
    ("l04", "Titi Me Pregunto", "Bad Bunny", ["reggaeton", "latin pop"], 0.80, 0.86, 0.88),
    ("l05", "Despacito", "Luis Fonsi", ["reggaeton", "latin pop"], 0.66, 0.80, 0.96),
    ("l06", "Ojitos Lindos", "Bad Bunny", ["reggaeton", "r&b"], 0.55, 0.72, 0.86),
    ("l07", "Baila Conmigo", "Selena Gomez & Rauw Alejandro", ["latin pop", "reggaeton"], 0.72, 0.84, 0.84),
    ("l08", "La Bebe", "Yng Lvcas", ["reggaeton", "latin trap"], 0.84, 0.88, 0.87),
    ("l09", "Pepas", "Farruko", ["reggaeton", "latin pop"], 0.90, 0.86, 0.88),
    ("l10", "Yonaguni", "Bad Bunny", ["reggaeton", "latin pop"], 0.62, 0.78, 0.85),
    # --- K-Pop (10) ---
    ("kp01", "Dynamite", "BTS", ["k-pop", "dance pop"], 0.78, 0.82, 0.94),
    ("kp02", "How You Like That", "BLACKPINK", ["k-pop", "edm"], 0.88, 0.80, 0.91),
    ("kp03", "Super Shy", "NewJeans", ["k-pop", "pop"], 0.72, 0.86, 0.88),
    ("kp04", "Butter", "BTS", ["k-pop", "dance pop"], 0.74, 0.80, 0.93),
    ("kp05", "Pink Venom", "BLACKPINK", ["k-pop", "hip hop"], 0.90, 0.76, 0.89),
    ("kp06", "Ditto", "NewJeans", ["k-pop", "synth pop"], 0.62, 0.78, 0.87),
    ("kp07", "ANTIFRAGILE", "LE SSERAFIM", ["k-pop", "dance pop"], 0.84, 0.78, 0.86),
    ("kp08", "Next Level", "aespa", ["k-pop", "edm"], 0.86, 0.76, 0.85),
    ("kp09", "Love Dive", "IVE", ["k-pop", "pop"], 0.76, 0.82, 0.84),
    ("kp10", "Hype Boy", "NewJeans", ["k-pop", "pop"], 0.70, 0.84, 0.87),
    # --- Country (8) ---
    ("c01", "Jolene", "Dolly Parton", ["country"], 0.52, 0.56, 0.88),
    ("c02", "Take Me Home, Country Roads", "John Denver", ["country", "folk"], 0.58, 0.52, 0.90),
    ("c03", "Fast Car", "Luke Combs", ["country", "country pop"], 0.62, 0.58, 0.89),
    ("c04", "Tennessee Whiskey", "Chris Stapleton", ["country", "soul"], 0.42, 0.48, 0.88),
    ("c05", "Body Like a Back Road", "Sam Hunt", ["country pop"], 0.58, 0.72, 0.84),
    ("c06", "Cruise", "Florida Georgia Line", ["country pop"], 0.78, 0.74, 0.86),
    ("c07", "Before He Cheats", "Carrie Underwood", ["country", "country pop"], 0.72, 0.58, 0.87),
    ("c08", "Wagon Wheel", "Darius Rucker", ["country", "folk"], 0.64, 0.62, 0.85),
    # --- Jazz (5) ---
    ("j01", "So What", "Miles Davis", ["jazz"], 0.35, 0.42, 0.82),
    ("j02", "Take Five", "Dave Brubeck", ["jazz"], 0.40, 0.50, 0.80),
    ("j03", "Fly Me to the Moon", "Frank Sinatra", ["jazz", "soul"], 0.45, 0.55, 0.88),
    ("j04", "Feeling Good", "Nina Simone", ["jazz", "soul"], 0.50, 0.48, 0.86),
    ("j05", "What a Wonderful World", "Louis Armstrong", ["jazz"], 0.32, 0.40, 0.90),
]

for tid, name, artist, genres, energy, dance, pop in _RAW_TRACKS:
    TRACK_CATALOG[tid] = Track(
        id=tid, name=name, artist=artist, genres=genres,
        energy=energy, danceability=dance, popularity=pop,
    )


def tracks_for_genre(genre: str, limit: int = 12) -> list[Track]:
    """Return tracks matching a genre, sorted by popularity."""
    related = GENRE_DEFAULTS.get(genre, {}).get("related", [genre])
    related_set = {g.lower() for g in related}
    matches = []
    for t in TRACK_CATALOG.values():
        track_genres = {g.lower() for g in t.genres}
        if track_genres & related_set:
            matches.append(t)
    matches.sort(key=lambda t: t.popularity, reverse=True)
    return matches[:limit]
