"""
Seeds the SongCatalog table from mock data on first startup.
Skips if songs already exist.
"""

import json
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import SongCatalog
from app.db.mock_data import MOCK_SONGS, SONG_GENRE_MAP, MOOD_SONG_MAP


def _mood_tags_for_song(song_id: str) -> list[str]:
    return [mood for mood, ids in MOOD_SONG_MAP.items() if song_id in ids]


async def seed_catalog(db: AsyncSession) -> None:
    result = await db.execute(select(SongCatalog).limit(1))
    if result.scalars().first():
        return  # already seeded

    print("[Beats] Seeding song catalog...")
    for song in MOCK_SONGS:
        row = SongCatalog(
            id=song.id,
            title=song.title,
            artist=song.artist,
            album=song.album,
            artwork=song.artwork,
            duration=song.duration,
            url=song.url,
            lyrics=json.dumps(song.lyrics or []),
            genre=SONG_GENRE_MAP.get(song.id, "Unknown"),
            mood_tags=json.dumps(_mood_tags_for_song(song.id)),
        )
        db.add(row)

    await db.commit()
    print(f"[Beats] Seeded {len(MOCK_SONGS)} songs.")
