"""
Beats Recommendation Engine
─────────────────────────────
Phase 1 (active now):  Rule-based mood + time-of-day filtering.
Phase 2 (kicks in):    Random Forest trained on your real play events.

Upgraded to support multi-user profile separation. The engine isolates 
training data and classification matrices per username context.
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
from app.db.mock_data import MOCK_SONGS, MOOD_SONG_MAP, SONG_GENRE_MAP
from app.models.schemas import Song
from app.core.config import get_settings

logger = logging.getLogger("beats.ml")
settings = get_settings()

MIN_EVENTS_FOR_ML = 50   # switch to ML model after this many play events per user


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
    else:
        return "Late Night"


# ── Phase 1: Rule-Based Recommender ──────────────────────────────────────────

def rule_based_recommend(
    mood: Optional[str],
    hour: int,
    limit: int = 10
) -> list[Song]:
    candidate_ids: list[str] = []

    if mood and mood in MOOD_SONG_MAP:
        candidate_ids = MOOD_SONG_MAP[mood].copy()

    time_mood_map = {
        "Morning Sessions": "Happy",
        "Afternoon Focus":  "Focus",
        "Evening Vibes":    "Chill",
        "Late Night":       "Night",
    }
    time_mood = time_mood_map[_time_label(hour)]
    time_ids = MOOD_SONG_MAP.get(time_mood, [])

    for sid in time_ids:
        if sid not in candidate_ids:
            candidate_ids.append(sid)

    if not candidate_ids:
        candidate_ids = [s.id for s in MOCK_SONGS]

    random.shuffle(candidate_ids)
    id_to_song = {s.id: s for s in MOCK_SONGS}
    return [id_to_song[sid] for sid in candidate_ids[:limit] if sid in id_to_song]


# ── Phase 2: ML Recommender ───────────────────────────────────────────────────

class MLRecommender:
    """
    Random Forest classifier isolated per user profile.
    Tracks distinct matrix sets inside a global pickle file dictionary.
    """

    MOOD_ENCODING = {
        "Happy": 0, "Chill": 1, "Focus": 2, "Workout": 3,
        "Night": 4, "Sad": 5,   "Party": 6, "Travel": 7,
    }

    def __init__(self):
        self.models: dict = {}         # Keyed by username -> RandomForestClassifier
        self.song_ids_map: dict = {}    # Keyed by username -> list of song IDs
        self._load_model()

    def _load_model(self):
        if os.path.exists(settings.MODEL_PATH):
            try:
                with open(settings.MODEL_PATH, "rb") as f:
                    payload = pickle.load(f)
                    # Graceful fallback handler for legacy single-user models
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
        """
        Gathers telemetry rows bounded strictly by active username to train a unique RF grid.
        """
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score
        from sklearn.preprocessing import LabelEncoder

        # Fetch tracking rows isolating target user profile context
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
        """
        Runs ranked context probability predictions against the specific user's model block.
        """
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
    username: str = "default_user",  # ✅ Added user context keyword argument
) -> list[Song]:
    """
    Main entry point for recommendation routing operations.
    Determines matrix usage based on the user's personal event logs.
    """
    hour = datetime.now().hour

    # Pull interaction limits specifically mapping back to the current profile
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

    logger.info(f"[ML] Fallback route triggered: Using rule-based matrix for '{username}' (events={event_count})")
    return rule_based_recommend(mood, hour, limit)


async def trigger_training(db: AsyncSession, username: str = "default_user") -> dict:
    return await _recommender.train(db, username)


def get_recommender() -> MLRecommender:
    return _recommender