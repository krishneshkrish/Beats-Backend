"""
Beats Recommendation Engine
─────────────────────────────
Phase 1 (active now):  Rule-based mood + time-of-day filtering from DB Catalog.
Phase 2 (kicks in):    Random Forest trained on your real play events.

Upgraded to dynamically fallback to real database catalog items rather than 
hardcoded mock song elements. Fully user-scoped layout matrix maps.
"""

import os
import json
import pickle
import random
import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.database import PlayEvent, SongCatalog
from app.db.mock_data import MOCK_SONGS, MOOD_SONG_MAP
from app.models.schemas import Song
from app.core.config import get_settings

logger = logging.getLogger("beats.ml")
settings = get_settings()

MIN_EVENTS_FOR_ML = 2   # ✅ Set low for seamless multi-user testing validation


# ── Helpers ───────────────────────────────────────────────────────────────────

def _song_catalog_to_schema(row: SongCatalog) -> Song:
    return Song(
        id=row.id,
        title=row.title,
        artist=row.artist,
        album=row.album,
        artwork=row.artwork,
        duration=row.duration,
        url=row.url,
        lyrics=json.loads(row.lyrics) if row.lyrics else None,
    )


def _time_label(hour: int) -> str:
    if 5 <= hour < 12:
        return "Morning Sessions"
    elif 12 <= hour < 17:
        return "Afternoon Focus"
    elif 17 <= hour < 22:
        return "Evening Vibes"
    else:  # ✅ Indentation fixed cleanly here to match alignment rules
        return "Late Night"


# ── Phase 1: Database-Driven Rule Recommender ─────────────────────────────────

async def rule_based_recommend(
    db: AsyncSession,
    mood: Optional[str],
    hour: int,
    limit: int = 10
) -> list[Song]:
    """
    Queries real songs stored inside our dynamic database SongCatalog table,
    filtering elements dynamically to match current mood parameters.
    """
    try:
        # 1. Pull all songs cached inside the production database catalog
        result = await db.execute(select(SongCatalog))
        catalog_rows = result.scalars().all()
        
        candidates = []
        target_mood = mood.lower() if mood else "chill"
        
        # 2. Filter tracks matching target mood strings inside the JSON column
        for row in catalog_rows:
            try:
                tags = [t.lower() for t in json.loads(row.mood_tags)] if row.mood_tags else []
            except Exception:
                tags = []
                
            if target_mood in tags or not mood:
                candidates.append(_song_catalog_to_schema(row))
                
        # 3. Fallback: If no catalog item matches the mood tag, grab all available real songs
        if not candidates and catalog_rows:
            candidates = [_song_catalog_to_schema(row) for row in catalog_rows]
            
        # 4. Crisis Fallback: If database catalog table is entirely empty, yield mock template items
        if not candidates:
            candidates = [Song(
                id=s.id, title=s.title, artist=s.artist, album=s.album,
                artwork=s.artwork, duration=s.duration, url=s.url, lyrics=s.lyrics
            ) for s in MOCK_SONGS]
            
        random.shuffle(candidates)
        return candidates[:limit]

    except Exception as e:
        logger.error(f"[Rule Fallback Error] Failed to scan catalog rows: {str(e)}")
        return [Song(id=s.id, title=s.title, artist=s.artist, album=s.album, artwork=s.artwork, duration=s.duration, url=s.url) for s in MOCK_SONGS[:limit]]


# ── Phase 2: ML Recommender ───────────────────────────────────────────────────

class MLRecommender:
    MOOD_ENCODING = {
        "Happy": 0, "Chill": 1, "Focus": 2, "Workout": 3,
        "Night": 4, "Sad": 5,   "Party": 6, "Travel": 7,
    }

    def __init__(self):
        self.models: dict = {}         
        self.song_ids_map: dict = {}    
        self._load_model()

    def _load_model(self):
        if os.path.exists(settings.MODEL_PATH):
            try:
                with open(settings.MODEL_PATH, "rb") as f:
                    payload = pickle.load(f)
                    if "model" in payload and "song_ids" in payload:
                        self.models = {"default_user": payload["model"]}
                        self.song_ids_map = {"default_user": payload["song_ids"]}
                    else:
                        self.models = payload.get("models", {})
                        self.song_ids_map = payload.get("song_ids_map", {})
                    logger.info(f"[ML] Loaded models for profile contexts: {list(self.models.keys())}")
            except Exception as e:
                logger.warning(f"[ML] Could not parse matrix load configuration: {e}")

    def _save_model(self):
        os.makedirs(os.path.dirname(settings.MODEL_PATH), exist_ok=True)
        with open(settings.MODEL_PATH, "wb") as f:
            pickle.dump({"models": self.models, "song_ids_map": self.song_ids_map}, f)
        logger.info(f"[ML] Scoped profile matrices saved safely to disk.")

    def _encode_mood(self, mood: str) -> int:
        return self.MOOD_ENCODING.get(mood, 1)

    async def train(self, db: AsyncSession, username: str = "default_user") -> dict:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score
        from sklearn.preprocessing import LabelEncoder

        result = await db.execute(select(PlayEvent).where(PlayEvent.username == username))
        events = result.scalars().all()

        if len(events) < MIN_EVENTS_FOR_ML:
            return {
                "status": "skipped",
                "reason": f"Profile '{username}' requires {MIN_EVENTS_FOR_ML} data interactions, currently has {len(events)}",
                "events": len(events),
            }

        df = pd.DataFrame([{
            "song_id":     e.song_id,
            "mood_enc":    self._encode_mood(e.mood_tag),
            "hour":        e.hour_of_day,
            "dow":         e.day_of_week,
            "skipped":     int(e.was_skipped),
            "replayed":    int(e.was_replayed),
        } for e in events])

        df["weight"] = df.apply(
            lambda r: 2.0 if r["replayed"] else (0.3 if r["skipped"] else 1.0),
            axis=1
        )

        le = LabelEncoder()
        df["song_label"] = le.fit_transform(df["song_id"])
        self.song_ids_map[username] = list(le.classes_)

        X = df[["mood_enc", "hour", "dow", "skipped", "replayed"]].values
        y = df["song_label"].values
        w = df["weight"].values

        X_train, X_test, y_train, y_test, w_train, _ = train_test_split(
            X, y, w, test_size=0.2, random_state=42
        )

        clf = RandomForestClassifier(n_estimators=100, random_state=42)
        clf.fit(X_train, y_train, sample_weight=w_train)

        acc = accuracy_score(y_test, clf.predict(X_test))
        self.models[username] = clf
        self._save_model()

        logger.info(f"[ML] Training execution success for '{username}'. Matrix Accuracy: {acc:.3f}")
        return {
            "status": "trained",
            "username": username,
            "events": len(events),
            "accuracy": round(acc, 4),
            "features": ["mood_enc", "hour", "dow", "skipped", "replayed"],
        }

    def predict(self, username: str, mood: str, hour: int, limit: int = 10) -> list[str]:
        model = self.models.get(username)
        song_ids = self.song_ids_map.get(username)

        if model is None or not song_ids:
            return []

        mood_enc = self._encode_mood(mood)
        dow = datetime.now().weekday()

        X = np.array([[mood_enc, hour, dow, 0, 0]])
        probs = model.predict_proba(X)[0]

        ranked = sorted(
            zip(song_ids, probs),
            key=lambda x: x[1],
            reverse=True
        )
        return [sid for sid, _ in ranked[:limit]]


# ── Unified Recommend Function ────────────────────────────────────────────────

_recommender = MLRecommender()


async def get_recommendations(
    db: AsyncSession,
    mood: Optional[str],
    limit: int = 10,
    context: str = "home",
    username: str = "default_user",
) -> list[Song]:
    hour = datetime.now().hour

    count_result = await db.execute(select(func.count(PlayEvent.id)).where(PlayEvent.username == username))
    event_count = count_result.scalar() or 0

    if event_count >= MIN_EVENTS_FOR_ML and _recommender.models.get(username) is not None:
        logger.info(f"[ML] Deploying specialized profile ML recommender matrix for '{username}' (events={event_count})")
        ml_ids = _recommender.predict(username, mood or "Chill", hour, limit)

        if ml_ids:
            result = await db.execute(
                select(SongCatalog).where(SongCatalog.id.in_(ml_ids))
            )
            rows = result.scalars().all()
            id_to_row = {r.id: r for r in rows}
            songs = [_song_catalog_to_schema(id_to_row[sid])
                     for sid in ml_ids if sid in id_to_row]
            if songs:
                return songs

    logger.info(f"[ML] Fallback route triggered: Using database-backed rule matrix for '{username}' (events={event_count})")
    return await rule_based_recommend(db, mood, hour, limit)


async def trigger_training(db: AsyncSession, username: str = "default_user") -> dict:
    return await _recommender.train(db, username)


def get_recommender() -> MLRecommender:
    return _recommender
