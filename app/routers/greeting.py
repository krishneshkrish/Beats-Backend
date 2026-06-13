from fastapi import APIRouter
from datetime import datetime
from app.models.schemas import GreetingResponse

router = APIRouter(prefix="/api", tags=["greeting"])


GREETING_MAP = {
    "morning": [
        ("Rise and vibe.", "Your morning playlist is already warmed up."),
        ("Good morning.", "Start your day with crystal clear soundwaves."),
        ("Early bird mode.", "Your focus mix is ready and waiting."),
    ],
    "afternoon": [
        ("Midday momentum.", "Stay in focus mode with our ambient flows."),
        ("Good afternoon.", "Keep the energy up with your afternoon picks."),
        ("Halfway there.", "The perfect soundtrack for the second half of your day."),
    ],
    "evening": [
        ("Golden hour.", "Unwind your mind. The night is yours."),
        ("Good evening.", "Time to decompress. Your evening mix is set."),
        ("Day well spent.", "Let the music carry you through the evening."),
    ],
    "night": [
        ("The city sleeps.", "Your playlist doesn't. Late night mode activated."),
        ("Good night, night owl.", "Deep synth dreams await. Soft acoustics queued."),
        ("Still awake?", "Your late-night companion is right here."),
    ],
}


def _time_slot(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 22:
        return "evening"
    else:
        return "night"


@router.get("/greeting", response_model=GreetingResponse)
async def get_greeting():
    hour = datetime.now().hour
    slot = _time_slot(hour)
    options = GREETING_MAP[slot]

    # Rotate greeting by minute so it feels fresh each visit
    index = datetime.now().minute % len(options)
    message, submessage = options[index]

    return GreetingResponse(message=message, submessage=submessage)
