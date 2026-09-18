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


def save_meeting(title, date, summary, decisions, people):
    import json
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO meetings(title,date,summary,decisions_json,people_json) VALUES (?,?,?,?,?)",
            (title, date, summary, json.dumps(decisions), json.dumps(people)),
        )
        return cur.lastrowid


def save_tasks(meeting_id, items):
    with _conn() as c:
        for it in items:
            # LLMs sometimes return strings instead of dicts — normalize
            if isinstance(it, str):
                it = {"task": it, "owner": "UNASSIGNED",
                      "deadline": None, "priority": "medium",
                      "source_quote": ""}
            elif not isinstance(it, dict):
                continue  # skip anything unparseable

            c.execute(
                """INSERT INTO tasks(meeting_id,task,owner,deadline,priority,source_quote)
                   VALUES (?,?,?,?,?,?)""",
                (
                    meeting_id,
                    it.get("task") or "",
                    it.get("owner") or "UNASSIGNED",
                    it.get("deadline"),
                    it.get("priority") or "medium",
                    it.get("source_quote") or "",
                ),
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