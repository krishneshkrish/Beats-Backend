"""
Mock data catalog — mirrors the frontend's mockData.ts exactly.
These are used as fallback when the DB has no real play history yet.
As you accumulate play events, the ML recommender takes over.
"""

from app.models.schemas import Song, TimelineItem, AnalyticsSummary, PlaylistMeta

MOCK_SONGS: list[Song] = [
    Song(
        id="s1",
        title="Neon Horizons",
        artist="Aether Vortex",
        album="Digital Dawn",
        artwork="https://images.unsplash.com/photo-1614149162883-504ce4d13909?w=400&q=80",
        duration=217,
        url="https://files.testfile.org/AUDIO/C/M4A/sample1.m4a",
        lyrics=["Neon lights", "Cutting through the night", "We rise above", "Into digital skies"],
    ),
    Song(
        id="s2",
        title="Midnight Drift",
        artist="Luna Echo",
        album="Tidal Waves",
        artwork="https://images.unsplash.com/photo-1493225457124-a3eb161ffa5f?w=400&q=80",
        duration=198,
        url="https://files.testfile.org/AUDIO/C/M4A/sample2.m4a",
        lyrics=["Waves of sound", "Pull me under", "Lost in the tide", "Of midnight thunder"],
    ),
    Song(
        id="s3",
        title="Phonk Adrenaline",
        artist="Drift King",
        album="Street Sessions",
        artwork="https://images.unsplash.com/photo-1571974599782-87624638275e?w=400&q=80",
        duration=183,
        url="https://files.testfile.org/AUDIO/C/M4A/sample3.m4a",
        lyrics=["Rev it up", "Streets are mine tonight", "Phonk in my veins", "Feel the adrenaline rise"],
    ),
    Song(
        id="s4",
        title="Chill Theorem",
        artist="Lo-Fi Sage",
        album="Study Room Vol.2",
        artwork="https://images.unsplash.com/photo-1470225620780-dba8ba36b745?w=400&q=80",
        duration=234,
        url="https://files.testfile.org/AUDIO/C/M4A/sample1.m4a",
        lyrics=["Pages turning slow", "Rain outside", "Coffee going cold", "Mind drifting wide"],
    ),
    Song(
        id="s5",
        title="Solar Flare",
        artist="Pulse Theory",
        album="Orbital",
        artwork="https://images.unsplash.com/photo-1446776811953-b23d57bd21aa?w=400&q=80",
        duration=251,
        url="https://files.testfile.org/AUDIO/C/M4A/sample2.m4a",
        lyrics=["Burning through the cosmos", "Flares of light", "Orbital decay", "Into endless night"],
    ),
    Song(
        id="s6",
        title="Glass Echoes",
        artist="Mira Voss",
        album="Translucent",
        artwork="https://images.unsplash.com/photo-1504898770365-14faca6a7320?w=400&q=80",
        duration=209,
        url="https://files.testfile.org/AUDIO/C/M4A/sample3.m4a",
        lyrics=["Fragile as glass", "Echoes in the hall", "Your voice lingers", "After the fall"],
    ),
    Song(
        id="s7",
        title="Iron Tempo",
        artist="Gage",
        album="Hardcode Sessions",
        artwork="https://images.unsplash.com/photo-1526478806334-5fd488fcaabc?w=400&q=80",
        duration=174,
        url="https://files.testfile.org/AUDIO/C/M4A/sample1.m4a",
        lyrics=["Iron will", "Steel in my mind", "Tempo rising", "Leaving the weak behind"],
    ),
    Song(
        id="s8",
        title="Lucid State",
        artist="Reverie",
        album="Dreamscape",
        artwork="https://images.unsplash.com/photo-1518609878373-06d740f60d8b?w=400&q=80",
        duration=262,
        url="https://files.testfile.org/AUDIO/C/M4A/sample2.m4a",
        lyrics=["Between awake and sleep", "Colours bleed", "I reach for you", "In my lucid dream"],
    ),
    Song(
        id="s9",
        title="Late Night Protocol",
        artist="Cipher",
        album="After Hours",
        artwork="https://images.unsplash.com/photo-1516450360452-9312f5e86fc7?w=400&q=80",
        duration=241,
        url="https://files.testfile.org/AUDIO/C/M4A/sample3.m4a",
        lyrics=["City sleeps", "I'm still awake", "Code running deep", "Mistakes I can't unmake"],
    ),
    Song(
        id="s10",
        title="Golden Hour",
        artist="Solstice",
        album="Meridian",
        artwork="https://images.unsplash.com/photo-1506157786151-b8491531f063?w=400&q=80",
        duration=228,
        url="https://files.testfile.org/AUDIO/C/M4A/sample1.m4a",
        lyrics=["Golden light", "Fading at the edge", "Hold this moment", "Before it slips ahead"],
    ),
]

# Mood → song ID mapping — mirrors MOOD_SONG_MAP from frontend
MOOD_SONG_MAP: dict[str, list[str]] = {
    "Happy":   ["s1", "s5", "s10"],
    "Chill":   ["s2", "s4", "s6", "s8"],
    "Focus":   ["s4", "s8", "s9"],
    "Workout": ["s3", "s7", "s5"],
    "Night":   ["s2", "s6", "s9"],
    "Sad":     ["s6", "s8", "s2"],
    "Party":   ["s1", "s3", "s7", "s10"],
    "Travel":  ["s5", "s10", "s1"],
}

# Genre tagging for each song (used in analytics)
SONG_GENRE_MAP: dict[str, str] = {
    "s1": "Electronic",
    "s2": "Ambient",
    "s3": "Phonk",
    "s4": "Lo-Fi",
    "s5": "Electronic",
    "s6": "Indie",
    "s7": "Hip-Hop",
    "s8": "Ambient",
    "s9": "Electronic",
    "s10": "Pop",
}

MOCK_ANALYTICS = AnalyticsSummary(
    totalTime=4260,        # minutes
    weeklyTime=345,
    streak=12,
    topArtist="Aether Vortex",
    topGenre="Electronic",
    topSong="Neon Horizons",
    circularProgress=[
        {"label": "Daily Goal", "value": 72, "color": "#FF3B30"},
        {"label": "Weekly",     "value": 58, "color": "#FF3B30"},
        {"label": "Streak",     "value": 85, "color": "#FF3B30"},
    ],
    genreData=[
        {"name": "Electronic", "value": 38},
        {"name": "Lo-Fi",      "value": 22},
        {"name": "Ambient",    "value": 18},
        {"name": "Phonk",      "value": 12},
        {"name": "Indie",      "value": 6},
        {"name": "Others",     "value": 4},
    ],
    heatmapData=[
        {"day": "Mon", "count": 45},
        {"day": "Tue", "count": 62},
        {"day": "Wed", "count": 30},
        {"day": "Thu", "count": 78},
        {"day": "Fri", "count": 91},
        {"day": "Sat", "count": 110},
        {"day": "Sun", "count": 55},
    ],
)

def _song_by_id(sid: str) -> Song:
    return next(s for s in MOCK_SONGS if s.id == sid)

MOCK_JOURNEY: list[TimelineItem] = [
    TimelineItem(
        id="j1",
        timestamp="2025-06-07T07:15:00Z",
        song=_song_by_id("s10"),
        moodTag="Happy",
        timeLabel="Morning Sessions",
        isMilestone=True,
        milestoneText="Best morning streak — 7 days in a row 🔥",
    ),
    TimelineItem(
        id="j2",
        timestamp="2025-06-07T07:35:00Z",
        song=_song_by_id("s4"),
        moodTag="Focus",
        timeLabel="Morning Sessions",
    ),
    TimelineItem(
        id="j3",
        timestamp="2025-06-07T13:10:00Z",
        song=_song_by_id("s8"),
        moodTag="Focus",
        timeLabel="Afternoon Focus",
        isMilestone=True,
        milestoneText="100 hours of Ambient music 🎧",
    ),
    TimelineItem(
        id="j4",
        timestamp="2025-06-07T18:45:00Z",
        song=_song_by_id("s1"),
        moodTag="Chill",
        timeLabel="Evening Vibes",
    ),
    TimelineItem(
        id="j5",
        timestamp="2025-06-07T23:20:00Z",
        song=_song_by_id("s9"),
        moodTag="Night",
        timeLabel="Late Night",
        isMilestone=True,
        milestoneText="New artist discovered: Cipher 🌙",
    ),
]

SEARCH_CATALOG = {
    "songs": MOCK_SONGS,
    "artists": list({s.artist for s in MOCK_SONGS}),
    "albums": list({s.album for s in MOCK_SONGS}),
    "playlists": [
        PlaylistMeta(id="p1", name="Late Night Drives", artwork=MOCK_SONGS[8].artwork, songCount=12),
        PlaylistMeta(id="p2", name="Morning Ritual",    artwork=MOCK_SONGS[9].artwork, songCount=8),
        PlaylistMeta(id="p3", name="Gym Beast Mode",    artwork=MOCK_SONGS[6].artwork, songCount=15),
        PlaylistMeta(id="p4", name="Focus Flow",        artwork=MOCK_SONGS[3].artwork, songCount=20),
    ],
}
