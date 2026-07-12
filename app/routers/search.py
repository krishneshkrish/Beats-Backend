import json
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.db.database import get_db, SongCatalog
from app.db.mock_data import MOCK_SONGS
from app.models.schemas import SearchResult, Song, PlaylistMeta

router = APIRouter(prefix="/api", tags=["search"])

MOCK_PLAYLISTS = [
    PlaylistMeta(id="p1", name="Late Night Drives",  artwork=MOCK_SONGS[8].artwork,  songCount=12),
    PlaylistMeta(id="p2", name="Morning Ritual",     artwork=MOCK_SONGS[9].artwork,  songCount=8),
    PlaylistMeta(id="p3", name="Gym Beast Mode",     artwork=MOCK_SONGS[6].artwork,  songCount=15),
    PlaylistMeta(id="p4", name="Focus Flow",         artwork=MOCK_SONGS[3].artwork,  songCount=20),
    PlaylistMeta(id="p5", name="Phonk Sessions",     artwork=MOCK_SONGS[2].artwork,  songCount=9),
    PlaylistMeta(id="p6", name="Chill Evenings",     artwork=MOCK_SONGS[5].artwork,  songCount=14),
]


@router.get("/search", response_model=SearchResult)
async def search(
    q: Optional[str] = Query(default=None),
    type: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """
    Full-text search across all catalog entities.
    Upgraded to pull real tracks dynamically from the database SongCatalog
    to completely displace mock/dummy entries when the query is empty.
    """
    # 1. Gather all real tracks currently cached inside your database catalog table
    db_result = await db.execute(select(SongCatalog))
    catalog_rows = db_result.scalars().all()
    
    db_songs = []
    for row in catalog_rows:
        try:
            lyrics_parsed = json.loads(row.lyrics) if row.lyrics else None
        except Exception:
            lyrics_parsed = None
            
        db_songs.append(Song(
            id=row.id,
            title=row.title,
            artist=row.artist,
            album=row.album,
            artwork=row.artwork,
            duration=row.duration,
            url=row.url,
            lyrics=lyrics_parsed
        ))

    # 2. Prioritize your real database assets. Fallback to templates only if database is blank
    if db_songs:
        songs = db_songs
    else:
        songs = [
            Song(
                id=s.id, title=s.title, artist=s.artist, album=s.album, 
                artwork=s.artwork, duration=s.duration, url=s.url
            ) for s in MOCK_SONGS
        ]

    # 3. Dynamically extract unique artists and albums matching the active song stack
    artists = list({s.artist for s in songs if s.artist})
    albums = list({s.album for s in songs if s.album})
    playlists = MOCK_PLAYLISTS

    # Mix real artwork grids onto the mock playlists if data is available to make it look unique
    if db_songs:
        for i, playlist in enumerate(playlists):
            if i < len(db_songs):
                playlist.artwork = db_songs[i].artwork

    # Case A: Search input box is empty (Dashboard Initial State View)
    if not q:
        return SearchResult(
            songs=songs[:6],
            artists=artists[:6],
            albums=albums[:6],
            playlists=playlists,
        )

    # Case B: Active Text Filtering Logic execution
    term = q.lower().strip()

    filtered_songs = [
        s for s in songs
        if term in s.title.lower()
        or term in s.artist.lower()
        or term in s.album.lower()
    ]

    filtered_artists = [a for a in artists if term in a.lower()]
    filtered_albums = [al for al in albums if term in al.lower()]
    filtered_playlists = [p for p in playlists if term in p.name.lower()]

    # Apply category filters matching your specific type query tags
    if type == "songs":
        filtered_artists, filtered_albums, filtered_playlists = [], [], []
    elif type == "artists":
        filtered_songs, filtered_albums, filtered_playlists = [], [], []
    elif type == "albums":
        filtered_songs, filtered_artists, filtered_playlists = [], [], []
    elif type == "playlists":
        filtered_songs, filtered_artists, filtered_albums = [], [], []

    return SearchResult(
        songs=filtered_songs,
        artists=filtered_artists,
        albums=filtered_albums,
        playlists=filtered_playlists,
    )
