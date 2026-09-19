from pathlib import Path
from core.llm import call_json

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


def extract(transcript: str, meeting_date: str) -> dict:
    user_msg = f"MEETING_DATE: {meeting_date}\n\nTRANSCRIPT:\n{transcript}"
    return call_json(SYSTEM_PROMPT, user_msg)
_FOLLOWUP_PATH = Path(__file__).resolve().parent.parent / "prompts" / "followup.txt"
FOLLOWUP_PROMPT = _FOLLOWUP_PATH.read_text(encoding="utf-8")


def draft_followup(meeting_data: dict) -> str:
    import json
    from core.llm import get_client, MODEL
    resp = get_client().chat.completions.create(
        model=MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": FOLLOWUP_PROMPT},
            {"role": "user", "content": json.dumps(meeting_data, indent=2)},
        ],
    )
    return resp.choices[0].message.content
QA_PROMPT = """You are the memory of an AI co-worker.

Answer the user's question using ONLY the meetings provided below.

Rules:
- If the answer is not in the meetings, say "I couldn't find that in the meetings."
- Always cite which meeting you got the answer from: "(from: [Meeting Title], [date])".
- Be concise — 1 to 3 sentences.
- Do NOT invent facts.

MEETINGS:
{context}
"""


def ask_meetings(question: str, context: str) -> str:
    from core.llm import get_client, MODEL
    resp = get_client().chat.completions.create(
        model=MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": QA_PROMPT.format(context=context)},
            {"role": "user", "content": question},
        ],
    )
    return resp.choices[0].message.content