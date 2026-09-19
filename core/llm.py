import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

_client = None

def get_client() -> Groq:
    global _client
    if _client is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY missing. Add it to your .env file.")
        _client = Groq(api_key=api_key)
    return _client


MODEL = "openai/gpt-oss-120b"


def call_json(system: str, user: str) -> dict:
    """Call Groq and force a JSON response."""
    resp = get_client().chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        temperature=0.1,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return json.loads(resp.choices[0].message.content)
def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """Send audio bytes to Groq Whisper, return the transcript text."""
    resp = get_client().audio.transcriptions.create(
        file=(filename, file_bytes),
        model="whisper-large-v3-turbo",
        response_format="text",
    )
    return resp if isinstance(resp, str) else resp.text
def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """Send audio bytes to Groq Whisper, return the transcript text."""
    resp = get_client().audio.transcriptions.create(
        file=(filename, file_bytes),
        model="whisper-large-v3-turbo",
        response_format="text",
    )
    return resp if isinstance(resp, str) else resp.text