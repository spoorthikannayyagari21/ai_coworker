import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "coworker.db"
DB_PATH.parent.mkdir(exist_ok=True)


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            summary TEXT,
            decisions_json TEXT,
            people_json TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            meeting_id INTEGER,
            task TEXT NOT NULL,
            owner TEXT,
            deadline TEXT,
            priority TEXT DEFAULT 'medium',
            status TEXT DEFAULT 'pending',
            source_quote TEXT,
            FOREIGN KEY(meeting_id) REFERENCES meetings(id)
        );
        """)
    init_settings_table()

def save_meeting(title, date, summary, decisions, people):
    import json

    # --- Normalize people: flatten nested lists, coerce to strings ---
    if not isinstance(people, list):
        people = [people] if people else []
    flat_people = []
    for p in people:
        if isinstance(p, (list, tuple)):
            flat_people.extend([str(x) for x in p if x])
        elif p:
            flat_people.append(str(p))
    people = flat_people

    # --- Normalize decisions: each item must be a dict with a "decision" key ---
    if not isinstance(decisions, list):
        decisions = []
    clean_decisions = []
    for d in decisions:
        if isinstance(d, dict):
            clean_decisions.append({
                "decision": str(d.get("decision", "") or ""),
                "quote": str(d.get("quote", "") or ""),
            })
        elif isinstance(d, str):
            clean_decisions.append({"decision": d, "quote": ""})
    decisions = clean_decisions
    print("DEBUG decisions:", type(decisions), decisions)
    print("DEBUG people:", type(people), people)
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO meetings(title,date,summary,decisions_json,people_json) VALUES (?,?,?,?,?)",
            (
                title or "",
                date or "",
                summary or "",
                json.dumps(decisions),
                json.dumps(people),
            ),
        )
        return cur.lastrowid

def save_tasks(meeting_id, items):
    with _conn() as c:
        for it in items:
            # Strings → dict
            if isinstance(it, str):
                it = {"task": it, "owner": "UNASSIGNED",
                      "deadline": None, "priority": "medium",
                      "source_quote": ""}
            elif not isinstance(it, dict):
                continue

            # Coerce every field to a plain type
            task_text = it.get("task") or ""
            if isinstance(task_text, (list, tuple)):
                task_text = " ".join(str(x) for x in task_text)
            owner = it.get("owner") or "UNASSIGNED"
            if isinstance(owner, (list, tuple)):
                owner = ", ".join(str(x) for x in owner)
            deadline = it.get("deadline")
            if isinstance(deadline, (list, tuple)):
                deadline = deadline[0] if deadline else None
            priority = it.get("priority") or "medium"
            if isinstance(priority, (list, tuple)):
                priority = priority[0] if priority else "medium"
            source_quote = it.get("source_quote") or ""
            if isinstance(source_quote, (list, tuple)):
                source_quote = " ".join(str(x) for x in source_quote)

            c.execute(
                """INSERT INTO tasks(meeting_id,task,owner,deadline,priority,source_quote)
                   VALUES (?,?,?,?,?,?)""",
                (meeting_id, str(task_text), str(owner),
                 str(deadline) if deadline else None,
                 str(priority), str(source_quote)),
            )


def get_meetings():
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM meetings ORDER BY id DESC")]


def get_meeting(mid):
    with _conn() as c:
        r = c.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
        return dict(r) if r else None


def get_tasks(status=None):
    q = "SELECT * FROM tasks"
    args = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY id DESC"
    with _conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def update_task_status(tid, status):
    with _conn() as c:
        c.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))


def stats():
    with _conn() as c:
        total_meetings = c.execute("SELECT COUNT(*) FROM meetings").fetchone()[0]
        total_tasks    = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        pending        = c.execute("SELECT COUNT(*) FROM tasks WHERE status='pending'").fetchone()[0]
        in_progress    = c.execute("SELECT COUNT(*) FROM tasks WHERE status='in_progress'").fetchone()[0]
        done           = c.execute("SELECT COUNT(*) FROM tasks WHERE status='done'").fetchone()[0]
        high           = c.execute("SELECT COUNT(*) FROM tasks WHERE priority='high' AND status!='done'").fetchone()[0]
    rate = int((done / total_tasks) * 100) if total_tasks else 0
    return {
        "meetings": total_meetings, "tasks": total_tasks,
        "pending": pending, "in_progress": in_progress,
        "done": done, "high": high, "completion_rate": rate,
    }
def overdue_tasks():
    from datetime import date
    today = date.today().isoformat()
    with _conn() as c:
        return [dict(r) for r in c.execute(
            """SELECT * FROM tasks
               WHERE status != 'done'
                 AND deadline IS NOT NULL
                 AND deadline != ''
                 AND deadline < ?
               ORDER BY deadline ASC""",
            (today,),
        )]
    
def all_meetings_text():
    """Return a single string with all meetings, for RAG-lite."""
    import json
    meetings = get_meetings()
    if not meetings:
        return ""
    chunks = []
    for m in meetings:
        try:
            decisions = json.loads(m["decisions_json"] or "[]")
        except Exception:
            decisions = []
        try:
            people = json.loads(m["people_json"] or "[]")
        except Exception:
            people = []
        decision_str = "; ".join(
            d.get("decision", "") if isinstance(d, dict) else str(d)
            for d in decisions
        )
        chunks.append(
            f"MEETING: {m['title']} (date: {m['date']})\n"
            f"Summary: {m['summary']}\n"
            f"Decisions: {decision_str}\n"
            f"People: {', '.join(people)}"
        )
    return "\n\n---\n\n".join(chunks)  
import re
from datetime import datetime

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "do", "does", "did",
    "what", "who", "when", "where", "why", "how", "about", "on", "in",
    "of", "to", "for", "and", "or", "we", "i", "you", "they", "it",
    "this", "that", "with", "at", "by", "from", "as", "be", "been",
}


def _tokenize(text: str) -> set:
    """Lowercase, strip punctuation, drop stopwords."""
    if not text:
        return set()
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def score_meeting(meeting: dict, question: str, query_terms: set, today: str) -> float:
    """Score a single meeting against the question."""
    score = 0.0

    # 1. Word overlap between question and (title + summary + decisions)
    haystack = " ".join([
        meeting.get("title") or "",
        meeting.get("summary") or "",
        meeting.get("decisions_json") or "",
        meeting.get("people_json") or "",
    ])
    haystack_terms = _tokenize(haystack)
    overlap = len(query_terms & haystack_terms)
    score += overlap * 2.0  # each matching term counts a lot

    # 2. Title match bonus
    title_terms = _tokenize(meeting.get("title") or "")
    score += len(query_terms & title_terms) * 1.5

    # 3. Recency bonus — newer meetings get a small boost
    try:
        mdate = datetime.fromisoformat(meeting["date"]).date()
        tdate = datetime.fromisoformat(today).date()
        days_old = (tdate - mdate).days
        score += max(0, 5 - days_old * 0.05)  # fades over 100 days
    except Exception:
        pass

    return score


def search_meetings(question: str, top_k: int = 5) -> list:
    """
    Return the top_k most relevant meetings for the question.
    Pure local computation — no LLM, no cost.
    """
    from datetime import date
    today = date.today().isoformat()
    query_terms = _tokenize(question)

    if not query_terms:
        # No meaningful query terms — just return the most recent
        return get_meetings()[:top_k]

    scored = []
    for m in get_meetings():
        s = score_meeting(m, question, query_terms, today)
        scored.append((s, m))

    scored.sort(key=lambda x: x[0], reverse=True)

    # Keep only meetings with actual relevance (score > 0)
    top = [m for s, m in scored if s > 0][:top_k]

    # Fallback: if nothing matched, return the most recent 3
    if not top:
        top = get_meetings()[:3]

    return top


def meetings_to_context(meetings: list) -> str:
    """Convert a list of meeting dicts into a context string for the LLM."""
    import json
    if not meetings:
        return ""
    chunks = []
    for m in meetings:
        try:
            decisions = json.loads(m["decisions_json"] or "[]")
        except Exception:
            decisions = []
        try:
            people = json.loads(m["people_json"] or "[]")
        except Exception:
            people = []
        decision_str = "; ".join(
            d.get("decision", "") if isinstance(d, dict) else str(d)
            for d in decisions
        )
        chunks.append(
            f"MEETING: {m['title']} (date: {m['date']})\n"
            f"Summary: {m['summary']}\n"
            f"Decisions: {decision_str}\n"
            f"People: {', '.join(people)}"
        )
    return "\n\n---\n\n".join(chunks)
def init_settings_table():
    with _conn() as c:
        c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """)



def get_setting(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
def delete_meeting(mid: int):
    """Delete a meeting and all its tasks."""
    with _conn() as c:
        c.execute("DELETE FROM tasks WHERE meeting_id=?", (mid,))
        c.execute("DELETE FROM meetings WHERE id=?", (mid,))


def delete_all_meetings():
    """Nuclear option — wipes everything."""
    with _conn() as c:
        c.execute("DELETE FROM tasks")
        c.execute("DELETE FROM meetings")
def find_similar_tasks(new_task: str, owner: str, threshold: float = 0.6) -> list:
    """
    Find open tasks by the same owner with high word overlap.
    Returns a list of dicts with the existing task + similarity score.
    """
    import re

    def tokens(s):
        return set(re.findall(r"[a-z0-9]+", (s or "").lower())) - {
            "the", "a", "an", "is", "to", "for", "of", "and", "on", "in", "by", "at"
        }

    new_tokens = tokens(new_task)
    if not new_tokens:
        return []

    similar = []
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM tasks WHERE owner=? AND status != 'done'",
            (owner,),
        ).fetchall()

    for row in rows:
        existing_tokens = tokens(row["task"])
        if not existing_tokens:
            continue
        overlap = len(new_tokens & existing_tokens)
        union = len(new_tokens | existing_tokens)
        score = overlap / union if union else 0
        if score >= threshold:
            similar.append({
                "id": row["id"],
                "task": row["task"],
                "deadline": row["deadline"],
                "status": row["status"],
                "similarity": round(score, 2),
            })

    similar.sort(key=lambda x: x["similarity"], reverse=True)
    return similar