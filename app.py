from datetime import date
import streamlit as st
from core.extractor import extract, draft_followup, ask_meetings
from core.llm import transcribe_audio
from audiorecorder import audiorecorder
from core import db
if "recordings" not in st.session_state:
    st.session_state["recordings"] = []
if "rec_counter" not in st.session_state:
    st.session_state["rec_counter"] = 0

# ---------- Setup ----------
st.set_page_config(
    page_title="MeetingMind — AI Co-worker",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

db.init_db()

# ---------- Custom CSS (the Bolt look) ----------
st.markdown("""
<style>
    /* Base */
    .stApp { background: #f8fafc; }
    section[data-testid="stSidebar"] {
        background: #ffffff;
        border-right: 1px solid #e5e7eb;
    }
    section[data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }

    # Kill Streamlit branding (keep the sidebar toggle working)
    #MainMenu, footer {visibility: hidden;}
    header[data-testid="stHeader"] { background: transparent; }

    /* Typography */
    h1, h2, h3 { color: #0f172a; font-weight: 700; letter-spacing: -0.02em; }
    .subtitle { color: #64748b; font-size: 0.95rem; margin-top: -0.5rem; }

    /* KPI card */
    .kpi-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 12px;
        padding: 20px;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03);
    }
    .kpi-label { color: #64748b; font-size: 0.85rem; font-weight: 500; }
    .kpi-value { color: #0f172a; font-size: 2rem; font-weight: 700; margin-top: 4px; }
    .kpi-sub   { color: #94a3b8; font-size: 0.78rem; margin-top: 2px; }

    /* Meeting card */
    .meet-card {
        background:#ffffff; border:1px solid #e5e7eb; border-radius:12px;
        padding:16px 20px; margin-bottom:10px;
    }
    .meet-title { font-weight:600; color:#0f172a; font-size:1.02rem; }
    .meet-meta  { color:#94a3b8; font-size:0.8rem; margin-top:4px; }
    .meet-sum   { color:#475569; font-size:0.88rem; margin-top:8px; }

    /* Task card */
    .task-card {
        background:#ffffff; border:1px solid #e5e7eb; border-radius:10px;
        padding:14px 16px; margin-bottom:10px;
    }
    .pill {
        display:inline-block; padding:2px 10px; border-radius:999px;
        font-size:0.72rem; font-weight:600; text-transform:uppercase;
    }
    .pill-high   { background:#fee2e2; color:#b91c1c; }
    .pill-medium { background:#fef3c7; color:#b45309; }
    .pill-low    { background:#dcfce7; color:#15803d; }

    /* Primary button */
    .stButton > button {
        border-radius: 8px;
        font-weight: 600;
    }

    /* Sidebar logo */
    .logo-row { display:flex; align-items:center; gap:10px; padding:6px 4px 16px 4px; }
    .logo-badge {
        width:38px; height:38px; border-radius:10px;
        background:#2563eb; color:#fff; display:flex; align-items:center;
        justify-content:center; font-weight:700; font-size:1.1rem;
    }
    .logo-name { font-weight:700; color:#0f172a; font-size:1.05rem; line-height:1; }
    .logo-sub  { color:#94a3b8; font-size:0.75rem; }
</style>
""", unsafe_allow_html=True)

# ---------- Sidebar ----------
with st.sidebar:
    st.markdown("""
        <div class="logo-row">
            <div class="logo-badge">🧠</div>
            <div>
                <div class="logo-name">MeetingMind</div>
                <div class="logo-sub">AI Co-worker</div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    page = st.radio(
        "Navigation",
        ["🏠  Dashboard", "➕  New Meeting", "📄  Meetings", "✅  Action Items", "💬  Ask"],
        label_visibility="collapsed",
    )
# ---------- Helpers ----------
def kpi_card(label, value, sub=""):
    return f"""
    <div class="kpi-card">
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        <div class="kpi-sub">{sub}</div>
    </div>
    """


def priority_pill(p):
    p = (p or "medium").lower()
    return f'<span class="pill pill-{p}">{p}</span>'


# =========================================================
# DASHBOARD
# =========================================================
if page.endswith("Dashboard"):
    s = db.stats()

    st.markdown("## Welcome back 👋")
    st.markdown('<div class="subtitle">Here\'s what your AI co-worker found across your meetings.</div>', unsafe_allow_html=True)
  


    # ---- Overdue alert banner ----
    overdue = db.overdue_tasks()
    if overdue:
        owners = {}
        for t in overdue:
            name = t["owner"] or "Unassigned"
            owners[name] = owners.get(name, 0) + 1
        owner_summary = ", ".join(f"{k} ({v})" for k, v in owners.items())
        st.error(f"⚠️ **{len(overdue)} overdue task(s)** — {owner_summary}")

    st.write("")
    
    

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(kpi_card("Total Meetings", s["meetings"]), unsafe_allow_html=True)
    c2.markdown(kpi_card("Pending Tasks", s["pending"], f"{s['in_progress']} in progress"), unsafe_allow_html=True)
    c3.markdown(kpi_card("High Priority", s["high"], "Needs attention"), unsafe_allow_html=True)
    c4.markdown(kpi_card("Completion Rate", f"{s['completion_rate']}%", f"{s['done']} completed"), unsafe_allow_html=True)

    st.write("")
    st.write("")

    left, right = st.columns([2, 1])

    with left:
        st.markdown("### Recent Meetings")
        meetings = db.get_meetings()[:5]
        if not meetings:
            st.info("No meetings yet. Click **➕ New Meeting** to add one.")
        for m in meetings:
            st.markdown(f"""
            <div class="meet-card">
                <div class="meet-title">{m['title']}</div>
                <div class="meet-meta">📅 {m['date']}</div>
                <div class="meet-sum">{(m['summary'] or '')[:180]}…</div>
            </div>
            """, unsafe_allow_html=True)

    with right:
        st.markdown("### Priority Actions")
        high = [t for t in db.get_tasks() if (t["priority"] or "").lower() == "high" and t["status"] != "done"]
        if not high:
            st.success("All clear — no high-priority tasks pending.")
        for t in high[:5]:
            st.markdown(f"""
            <div class="task-card">
                {priority_pill(t['priority'])}
                <div style="margin-top:8px;color:#0f172a;font-weight:500;">{t['task']}</div>
                <div style="color:#64748b;font-size:0.8rem;margin-top:6px;">👤 {t['owner'] or 'Unassigned'}</div>
            </div>
            """, unsafe_allow_html=True)

# =========================================================
# NEW MEETING
# =========================================================
elif page.endswith("New Meeting"):
    st.markdown("## ➕ Add Meeting Notes")
    st.markdown('<div class="subtitle">Paste a transcript. The AI extracts decisions, action items, owners, and deadlines.</div>', unsafe_allow_html=True)
    st.write("")

    samples = {
        "Weekly Product Sync": "Priya: Let's lock the Q4 roadmap today. Rahul: Agreed, but we need the design review done first. Priya: Rahul, can you schedule it by Wednesday? Rahul: Yes. Meera: I'll draft the pricing doc by Friday. Priya: Also we decided to deprioritize the mobile revamp for now. Everyone agreed.",
        "Engineering Standup": "Alex: Morning team. I finished the database migration yesterday. Emma: Nice. I'm working on the Redis caching layer, should be done by Thursday. Chris: Blocked on the API key rotation, need DevOps help. Alex: I'll ping DevOps today. Emma: Also we decided to switch to GitHub Actions for CI. Chris: I can set up the initial workflow by end of week.",
        "Client Kickoff": "Client: We want to launch by end of quarter. PM: Understood. We'll need the brand assets by next Monday. Client: I'll send them. PM: Sarah will own the wireframes, deadline is two weeks from now. Sarah: Confirmed. Dev lead: We'll need API access to the client's CRM. Client: I'll arrange that by Friday.",
    }

    st.markdown("**Try a sample:**")
    cols = st.columns(len(samples))
    for i, (name, text) in enumerate(samples.items()):
        if cols[i].button(name, use_container_width=True):
            st.session_state["transcript"] = text
            st.session_state["title"] = name

    st.write("")
    st.markdown("**🎙️ Audio input**")
    audio_tab1, audio_tab2 = st.tabs(["📁 Upload file", "🎤 Record live"])

    # ----- Tab 1: Upload -----
    with audio_tab1:
        audio_file = st.file_uploader(
            "Drag your meeting recording here",
            type=["mp3", "wav", "m4a", "webm", "mp4", "ogg"],
            label_visibility="collapsed",
        )
        if audio_file is not None:
            col_a, col_b = st.columns([1, 3])
            with col_a:
                if st.button("📁 Transcribe upload", key="transcribe_upload"):
                    with st.spinner("Transcribing with Whisper…"):
                        try:
                            text = transcribe_audio(audio_file.getvalue(), audio_file.name)
                            st.session_state["transcript"] = text
                            st.success(f"✅ Transcribed {len(text)} characters.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Transcription failed: {e}")
            with col_b:
                st.caption("Whisper will transcribe the audio into the transcript box below.")

    # ----- Tab 2: Record live -----
    with audio_tab2:
        st.caption("Click the recorder to start. Click stop when done. No time limit — record as long as you need.")

        wav_bytes = audiorecorder(
            start_prompt="🔴 Start recording",
            stop_prompt="⏹️ Stop",
            pause_prompt="⏸️ Paused",
            show_visualizer=True,
            key="live_recorder",
        )

        # audiorecorder returns an AudioSegment-like object; check it's non-empty
        if wav_bytes and len(wav_bytes) > 0:
            audio_bytes = wav_bytes.export(format="wav").read()
            current_sig = hash(audio_bytes)

            if current_sig != st.session_state.get("last_audio_id"):
                st.session_state["rec_counter"] += 1
                st.session_state["recordings"].append({
                    "id": st.session_state["rec_counter"],
                    "name": f"Recording {st.session_state['rec_counter']}",
                    "bytes": audio_bytes,
                })
                st.session_state["last_audio_id"] = current_sig
                st.rerun()

        # ---- List existing recordings ----
        recs = st.session_state["recordings"]

        if recs:
            st.markdown(f"**🎧 {len(recs)} recording(s)**")

            for rec in recs:
                with st.container():
                    c1, c2, c3 = st.columns([3, 1, 1])

                    with c1:
                        st.audio(rec["bytes"], format="audio/wav")
                        st.caption(f"{rec['name']} · {len(rec['bytes'])//1024} KB")

                    with c2:
                        if st.button("🎤 Transcribe", key=f"trans_{rec['id']}"):
                            with st.spinner(f"Transcribing {rec['name']}…"):
                                try:
                                    text = transcribe_audio(rec["bytes"], f"{rec['name']}.wav")
                                    existing = st.session_state.get("transcript", "")
                                    separator = "\n\n" if existing.strip() else ""
                                    st.session_state["transcript"] = existing + separator + text
                                    st.success(f"✅ {rec['name']} transcribed.")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Transcription failed: {e}")

                    with c3:
                        if st.button("🗑️ Delete", key=f"del_{rec['id']}"):
                            st.session_state["recordings"] = [
                                r for r in recs if r["id"] != rec["id"]
                            ]
                            st.rerun()

            st.markdown("---")
            b1, b2, b3 = st.columns([1, 1, 2])

            with b1:
                if st.button("🎤 Transcribe all", key="transcribe_all"):
                    with st.spinner("Transcribing all recordings…"):
                        try:
                            combined = []
                            for rec in recs:
                                t = transcribe_audio(rec["bytes"], f"{rec['name']}.wav")
                                combined.append(f"[{rec['name']}]\n{t}")
                            st.session_state["transcript"] = "\n\n".join(combined)
                            st.success(f"✅ Transcribed {len(recs)} recordings.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Transcription failed: {e}")

            with b2:
                if st.button("🗑️ Delete all", key="delete_all"):
                    st.session_state["recordings"] = []
                    st.session_state["last_audio_id"] = None
                    st.rerun()

            with b3:
                st.caption("Transcribe adds text to the box below. Delete clears it.")
        else:
            st.info("No recordings yet. Click **Start recording** above.")

    st.markdown("---")
    title = st.text_input("Meeting title", value=st.session_state.get("title", ""), placeholder="e.g., Weekly Product Sync")
    mdate = st.date_input("Meeting date", value=date.today())
    transcript = st.text_area(
        "Meeting transcript",
        value=st.session_state.get("transcript", ""),
        height=280,
        placeholder="Paste your meeting transcript here…",
    )

    if st.button("🚀 Analyze Meeting", type="primary"):
        if not transcript.strip():
            st.warning("Please paste a transcript first.")
        elif not title.strip():
            st.warning("Please give the meeting a title.")
        else:
            with st.spinner("Analyzing with Groq…"):
                try:
                    result = extract(transcript, mdate.isoformat())
                except Exception as e:
                    st.error(f"Groq error: {e}")
                    st.stop()

            mid = db.save_meeting(
                title, mdate.isoformat(),
                result.get("summary", ""),
                result.get("decisions", []),
                result.get("people", []),
            )
            db.save_tasks(mid, result.get("action_items", []))

            st.session_state["last_result"] = result
            st.session_state.pop("last_email", None)
            st.rerun()
    # ---- Results render here — OUTSIDE the button block ----
    result = st.session_state.get("last_result")
    if result:
        st.success("✅ Meeting analyzed and saved!")

        st.markdown("### 📝 Summary")
        st.markdown(result.get("summary", ""))

        st.markdown("### ✅ Decisions")
        for d in result.get("decisions", []):
            st.markdown(f"- **{d.get('decision','')}**  \n  _{d.get('quote','')}_")

        st.markdown("### 📌 Action Items")
        items = result.get("action_items", [])
        if items:
            for item in items:
                # Normalize: string → dict
                if isinstance(item, str):
                    item = {"task": item, "owner": "UNASSIGNED",
                            "deadline": None, "priority": "medium",
                            "source_quote": ""}
                elif not isinstance(item, dict):
                    continue

                st.markdown(
                    f"**{item.get('task') or ''}**  \n"
                    f"👤 {item.get('owner') or 'UNASSIGNED'} · "
                    f"📅 {item.get('deadline') or '—'} · "
                    f"🎯 {item.get('priority') or 'medium'}"
                )
                if item.get("source_quote"):
                    st.caption(f"_{item['source_quote']}_")
                st.divider()
        else:
            st.write("_None found._")

        st.markdown("### 👥 People")
        st.write(", ".join(result.get("people", [])) or "_None detected._")

        st.markdown("---")

        if st.button("📧 Draft Follow-up Email", key="draft_email"):
            with st.spinner("Drafting email…"):
                try:
                    email = draft_followup({
                        "summary": result.get("summary", ""),
                        "decisions": result.get("decisions", []),
                        "action_items": result.get("action_items", []),
                        "people": result.get("people", []),
                    })
                    st.session_state["last_email"] = email
                except Exception as e:
                    st.error(f"Email draft failed: {e}")

        if st.session_state.get("last_email"):
            st.markdown("### 📧 Follow-up Email")
            st.text_area(
                "Copy this:",
                st.session_state["last_email"],
                height=320,
                key="email_box",
            )

# =========================================================
# MEETINGS LIST
# =========================================================
elif page.endswith("Meetings"):
    st.markdown("## 📄 All Meetings")
    meetings = db.get_meetings()

    search = st.text_input("Search meetings by title or summary", "")
    if search:
        meetings = [m for m in meetings
                    if search.lower() in (m["title"] or "").lower()
                    or search.lower() in (m["summary"] or "").lower()]

    st.caption(f"{len(meetings)} meeting(s)")
    st.write("")

    for m in meetings:
        st.markdown(f"""
        <div class="meet-card">
            <div class="meet-title">{m['title']}</div>
            <div class="meet-meta">📅 {m['date']}</div>
            <div class="meet-sum">{(m['summary'] or '')[:280]}…</div>
        </div>
        """, unsafe_allow_html=True)

# =========================================================
# ACTION ITEMS / KANBAN
# =========================================================
elif page.endswith("Action Items"):
    st.markdown("## ✅ Task Board")
    tasks = db.get_tasks()
    st.caption(f"{len(tasks)} task(s) total")

    col1, col2, col3 = st.columns(3)
    columns = {
        "pending":     ("🕐 Pending",     col1),
        "in_progress": ("⚙️ In Progress", col2),
        "done":        ("✅ Completed",    col3),
    }

    for status, (label, col) in columns.items():
        with col:
            subset = [t for t in tasks if t["status"] == status]
            st.markdown(f"### {label}  ·  {len(subset)}")

            for t in subset:
                with st.container():
                    st.markdown(f"""
                    <div class="task-card">
                        {priority_pill(t['priority'])}
                        <div style="margin-top:8px;color:#0f172a;font-weight:500;">{t['task']}</div>
                        <div style="color:#64748b;font-size:0.8rem;margin-top:6px;">
                            👤 {t['owner'] or 'Unassigned'} &nbsp;·&nbsp; 📅 {t['deadline'] or '—'}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

                    new_status = st.selectbox(
                        "Move to",
                        ["pending", "in_progress", "done"],
                        index=["pending", "in_progress", "done"].index(t["status"]),
                        key=f"move_{t['id']}",
                        label_visibility="collapsed",
                    )
                    if new_status != t["status"]:
                        db.update_task_status(t["id"], new_status)
                        st.rerun()
elif page.endswith("Ask"):
    st.markdown("## 💬 Ask Your Meetings")
    st.markdown('<div class="subtitle">Ask anything about past meetings. The AI answers with citations.</div>', unsafe_allow_html=True)

    context = db.all_meetings_text()

    if not context:
        st.info("No meetings yet. Add one first, then come back and ask questions.")
    else:
        st.caption(f"Searching across {len(db.get_meetings())} meetings.")

        question = st.text_input(
            "Your question",
            placeholder="e.g., What did we decide about the database?",
        )

        if st.button("Ask", type="primary") and question.strip():
            with st.spinner("Searching meetings…"):
                try:
                    answer = ask_meetings(question, context)
                    st.session_state["last_answer"] = {
                        "q": question,
                        "a": answer,
                    }
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

        if st.session_state.get("last_answer"):
            item = st.session_state["last_answer"]
            st.markdown("---")
            st.markdown(f"**Q: {item['q']}**")
            st.markdown(f"**A:** {item['a']}")                        
