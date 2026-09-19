from pathlib import Path
from core.llm import call_json

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "extract.txt"
SYSTEM_PROMPT = _PROMPT_PATH.read_text(encoding="utf-8")


def extract(transcript: str, meeting_date: str) -> dict:
    user_msg = f"MEETING_DATE: {meeting_date}\n\nTRANSCRIPT:\n{transcript}"
    return call_json(SYSTEM_PROMPT, user_msg)
def extract_sanitized(transcript: str, meeting_date: str):
    from core.sanitizer import sanitize, detokenize_obj, validate_output
    from core.db import get_setting

    custom_terms = [
        t.strip() for t in (get_setting("custom_terms", "") or "").splitlines()
        if t.strip()
    ]
    clean, vault = sanitize(transcript, mask_names=True, custom_terms=custom_terms)

    # --- Get raw LLM output (as text) so we can validate it ---
    from core.llm import get_client, MODEL
    from core.extractor import SYSTEM_PROMPT
    import json

    resp = get_client().chat.completions.create(
        model=MODEL,
        response_format={"type": "json_object"},
        temperature=0.1,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"MEETING_DATE: {meeting_date}\n\nTRANSCRIPT:\n{clean}"},
        ],
    )
    raw_text = resp.choices[0].message.content

    # --- Validate BEFORE detokenizing ---
    warnings = validate_output(raw_text, vault)

    # --- Detokenize ---
    raw_json = json.loads(raw_text)
    final = detokenize_obj(raw_json, vault)

    return final, vault, clean, warnings


def draft_followup_sanitized(meeting_data: dict):
    """Draft email but sanitize before sending to LLM, detokenize after."""
    from core.sanitizer import sanitize, detokenize
    import json

    # Serialize, sanitize, then let the LLM work on the sanitized version
    payload = json.dumps(meeting_data, indent=2)
    clean_payload, vault = sanitize(payload)

    from core.llm import get_client, MODEL
    from pathlib import Path

    prompt_path = Path(__file__).resolve().parent.parent / "prompts" / "followup.txt"
    FOLLOWUP = prompt_path.read_text(encoding="utf-8")

    resp = get_client().chat.completions.create(
        model=MODEL,
        temperature=0.3,
        messages=[
            {"role": "system", "content": FOLLOWUP},
            {"role": "user", "content": clean_payload},
        ],
    )
    email = resp.choices[0].message.content
    return detokenize(email, vault)
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