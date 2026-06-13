from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Optional

from app.db.database import get_db, SongCatalog
from app.db.mock_data import SEARCH_CATALOG, MOCK_SONGS
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

    Query params:
      q    — search term
      type — optional filter: 'songs' | 'artists' | 'albums' | 'playlists'

    With no query, returns trending/catalog overview.
    """
    songs = MOCK_SONGS
    artists = list({s.artist for s in MOCK_SONGS})
    albums = list({s.album for s in MOCK_SONGS})
    playlists = MOCK_PLAYLISTS

    if not q:
        return SearchResult(
            songs=songs[:6],
            artists=artists[:6],
            albums=albums[:6],
            playlists=playlists,
        )

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

    # If type filter is set, zero out other categories
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
