"""
Beats Recommendation Engine
─────────────────────────────
Phase 1 (active now):  Rule-based mood + time-of-day filtering.
Phase 2 (kicks in):    Random Forest trained on your real play events.

The engine auto-detects which phase to use based on how many play
events you have in the DB. < MIN_EVENTS → rule-based; >= MIN_EVENTS → ML.

This is intentional — it gives you real training data before the model
runs, which is exactly the right ML engineering approach.
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

MIN_EVENTS_FOR_ML = 50   # switch to ML model after this many play events


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
    """
    Pure logic — no training needed.
    Priority: mood tag → time-of-day fallback → shuffle all.
    """
    candidate_ids: list[str] = []

    if mood and mood in MOOD_SONG_MAP:
        candidate_ids = MOOD_SONG_MAP[mood].copy()

    # Time-of-day boost — add time-appropriate songs even if mood is set
    time_mood_map = {
        "Morning Sessions": "Happy",
        "Afternoon Focus":  "Focus",
        "Evening Vibes":    "Chill",
        "Late Night":       "Night",
    }
    time_mood = time_mood_map[_time_label(hour)]
    time_ids = MOOD_SONG_MAP.get(time_mood, [])

    # Merge without duplicates, keep mood-tagged first
    for sid in time_ids:
        if sid not in candidate_ids:
            candidate_ids.append(sid)

    # Fallback to everything
    if not candidate_ids:
        candidate_ids = [s.id for s in MOCK_SONGS]

    random.shuffle(candidate_ids)
    id_to_song = {s.id: s for s in MOCK_SONGS}
    return [id_to_song[sid] for sid in candidate_ids[:limit] if sid in id_to_song]


# ── Phase 2: ML Recommender ───────────────────────────────────────────────────

class MLRecommender:
    """
    Random Forest classifier trained on your real play history.

    Features used per play event:
      - hour_of_day        (0–23)
      - day_of_week        (0–6)
      - mood_encoded       (label encoded)
      - song_energy        (Librosa feature, if extracted)
      - song_valence       (Librosa feature, if extracted)
      - was_skipped        (negative signal)
      - was_replayed       (strong positive signal)

    Target: song_id (which song to play next)

    Training is triggered manually via POST /api/ml/train.
    Model is saved to disk and loaded on next startup.
    """

    MOOD_ENCODING = {
        "Happy": 0, "Chill": 1, "Focus": 2, "Workout": 3,
        "Night": 4, "Sad": 5,   "Party": 6, "Travel": 7,
    }

    def __init__(self):
        self.model = None
        self.song_ids: list[str] = []
        self._load_model()

    def _load_model(self):
        if os.path.exists(settings.MODEL_PATH):
            try:
                with open(settings.MODEL_PATH, "rb") as f:
                    payload = pickle.load(f)
                    self.model = payload["model"]
                    self.song_ids = payload["song_ids"]
                    logger.info(f"[ML] Loaded model from {settings.MODEL_PATH}")
            except Exception as e:
                logger.warning(f"[ML] Could not load model: {e}")

    def _save_model(self):
        os.makedirs(os.path.dirname(settings.MODEL_PATH), exist_ok=True)
        with open(settings.MODEL_PATH, "wb") as f:
            pickle.dump({"model": self.model, "song_ids": self.song_ids}, f)
        logger.info(f"[ML] Model saved to {settings.MODEL_PATH}")

    def _encode_mood(self, mood: str) -> int:
        return self.MOOD_ENCODING.get(mood, 1)  # default Chill

    async def train(self, db: AsyncSession) -> dict:
        """
        Pull all play events from DB, build feature matrix, train RF classifier.
        Returns training report dict.
        """
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score
        from sklearn.preprocessing import LabelEncoder

        result = await db.execute(select(PlayEvent))
        events = result.scalars().all()

        if len(events) < MIN_EVENTS_FOR_ML:
            return {
                "status": "skipped",
                "reason": f"Need {MIN_EVENTS_FOR_ML} events, have {len(events)}",
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

        # Weight: replayed = strong positive, skipped = negative
        df["weight"] = df.apply(
            lambda r: 2.0 if r["replayed"] else (0.3 if r["skipped"] else 1.0),
            axis=1
        )

        le = LabelEncoder()
        df["song_label"] = le.fit_transform(df["song_id"])
        self.song_ids = list(le.classes_)

        X = df[["mood_enc", "hour", "dow", "skipped", "replayed"]].values
        y = df["song_label"].values
        w = df["weight"].values

        X_train, X_test, y_train, y_test, w_train, _ = train_test_split(
            X, y, w, test_size=0.2, random_state=42
        )

        clf = RandomForestClassifier(n_estimators=100, random_state=42)
        clf.fit(X_train, y_train, sample_weight=w_train)

        acc = accuracy_score(y_test, clf.predict(X_test))
        self.model = clf
        self._save_model()

        logger.info(f"[ML] Training complete. Accuracy: {acc:.3f}")
        return {
            "status": "trained",
            "events": len(events),
            "accuracy": round(acc, 4),
            "features": ["mood_enc", "hour", "dow", "skipped", "replayed"],
        }

    def predict(self, mood: str, hour: int, limit: int = 10) -> list[str]:
        """
        Returns ranked list of song_ids predicted for this context.
        Falls back to rule-based if model isn't ready.
        """
        if self.model is None or not self.song_ids:
            return []

        mood_enc = self._encode_mood(mood)
        dow = datetime.now().weekday()

        # Get probability distribution over all songs
        X = np.array([[mood_enc, hour, dow, 0, 0]])
        probs = self.model.predict_proba(X)[0]

        # Rank by probability, return top song_ids
        ranked = sorted(
            zip(self.song_ids, probs),
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
) -> list[Song]:
    """
    Main entry point for recommendations.
    Auto-selects rule-based vs ML based on event count.
    """
    hour = datetime.now().hour

    # Check how many events we have
    count_result = await db.execute(select(func.count(PlayEvent.id)))
    event_count = count_result.scalar() or 0

    if event_count >= MIN_EVENTS_FOR_ML and _recommender.model is not None:
        logger.info(f"[ML] Using ML recommender (events={event_count})")
        ml_ids = _recommender.predict(mood or "Chill", hour, limit)

        # Fetch from catalog
        if ml_ids:
            result = await db.execute(
                select(SongCatalog).where(SongCatalog.id.in_(ml_ids))
            )
            rows = result.scalars().all()
            id_to_row = {r.id: r for r in rows}
            # Preserve ranked order
            songs = [_song_catalog_to_schema(id_to_row[sid])
                     for sid in ml_ids if sid in id_to_row]
            if songs:
                return songs

    logger.info(f"[ML] Using rule-based recommender (events={event_count})")
    return rule_based_recommend(mood, hour, limit)


async def trigger_training(db: AsyncSession) -> dict:
    return await _recommender.train(db)


def get_recommender() -> MLRecommender:
    return _recommender
