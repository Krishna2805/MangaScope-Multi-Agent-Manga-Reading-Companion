"""
MangaScope — Streamlit UI.

One page, top to bottom. Input form → staged agent execution → result cards.
Each agent shows a live status update during execution via st.status.
Fallback agent_status renders a warning badge instead of a blank section.
"""

import streamlit as st
import html
from coordinator import run as coordinator_run

# Helper to escape HTML characters safely inside f-strings using unsafe_allow_html=True
def esc(val) -> str:
    if val is None:
        return ""
    return html.escape(str(val))


# ── Page Config ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MangaScope 🎌",
    page_icon="🎌",
    layout="centered",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    /* Global */
    .stApp {
        font-family: 'Inter', sans-serif;
    }

    /* Header */
    .main-header {
        text-align: center;
        padding: 1.5rem 0 0.5rem 0;
    }
    .main-header h1 {
        font-size: 2.8rem;
        font-weight: 800;
        background: linear-gradient(135deg, #667eea 0%, #f093fb 50%, #f5576c 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin-bottom: 0.2rem;
    }
    .main-header p {
        color: #888;
        font-size: 1.05rem;
        font-weight: 400;
    }

    /* Result cards */
    .result-card {
        background: linear-gradient(145deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid rgba(102, 126, 234, 0.25);
        border-radius: 16px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }
    .result-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 30px rgba(102, 126, 234, 0.15);
    }
    .result-card h3 {
        margin-top: 0;
        font-weight: 700;
        font-size: 1.15rem;
    }
    .result-card .card-value {
        font-size: 1.6rem;
        font-weight: 700;
        color: #667eea;
    }
    .result-card .card-label {
        font-size: 0.85rem;
        color: #aaa;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .result-card .card-note {
        font-size: 0.92rem;
        color: #ccc;
        margin-top: 0.5rem;
        font-style: italic;
    }

    /* Fallback warning */
    .fallback-badge {
        background: rgba(255, 193, 7, 0.12);
        border: 1px solid rgba(255, 193, 7, 0.35);
        border-radius: 12px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        color: #ffc107;
        font-size: 0.95rem;
    }
    .fallback-badge .badge-icon {
        font-size: 1.1rem;
        margin-right: 0.4rem;
    }

    /* Stat pills */
    .stat-row {
        display: flex;
        gap: 1rem;
        flex-wrap: wrap;
        margin-top: 0.75rem;
    }
    .stat-pill {
        background: rgba(102, 126, 234, 0.1);
        border: 1px solid rgba(102, 126, 234, 0.2);
        border-radius: 8px;
        padding: 0.4rem 0.85rem;
        font-size: 0.88rem;
        color: #b8c4ff;
    }

    /* Confidence badges */
    .confidence-high {
        color: #4caf50;
        font-weight: 600;
    }
    .confidence-low {
        color: #ff9800;
        font-weight: 600;
    }
    .confidence-unknown {
        color: #f44336;
        font-weight: 600;
    }

    /* Priority badges */
    .priority-high {
        background: rgba(244, 67, 54, 0.15);
        border: 1px solid rgba(244, 67, 54, 0.3);
        color: #f44336;
        border-radius: 6px;
        padding: 0.2rem 0.6rem;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
    }
    .priority-up-to-date {
        background: rgba(76, 175, 80, 0.15);
        border: 1px solid rgba(76, 175, 80, 0.3);
        color: #4caf50;
        border-radius: 6px;
        padding: 0.2rem 0.6rem;
        font-size: 0.8rem;
        font-weight: 600;
        text-transform: uppercase;
    }

    /* Memory note */
    .memory-note {
        background: rgba(102, 126, 234, 0.08);
        border-left: 3px solid #667eea;
        border-radius: 0 8px 8px 0;
        padding: 0.75rem 1rem;
        margin-top: 1rem;
        font-size: 0.9rem;
        color: #b8c4ff;
    }

    /* Footer */
    .footer {
        text-align: center;
        color: #666;
        font-size: 0.8rem;
        margin-top: 2rem;
        padding-bottom: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Header ───────────────────────────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <h1>MangaScope 🎌</h1>
    <p>Your multi-agent manga reading companion</p>
</div>
""", unsafe_allow_html=True)

st.divider()

# ── Input Form ───────────────────────────────────────────────────────────────

col1, col2 = st.columns(2)
with col1:
    username = st.text_input(
        "AniList Username",
        placeholder="e.g. lelouch2805",
        help="Your AniList username (alphanumeric + underscores)",
    )
with col2:
    series_name = st.text_input(
        "Manga Series",
        placeholder="e.g. One Piece",
        help="The manga series you want to check",
    )

# Initialize session state for report and memory note if not present
if "report" not in st.session_state:
    st.session_state.report = None
if "memory_note" not in st.session_state:
    st.session_state.memory_note = ""

run_button = st.button("🚀 Run Agent", use_container_width=True, type="primary")

st.divider()

# ── Agent Execution ──────────────────────────────────────────────────────────

if run_button:
    if not username or not series_name:
        st.error("Please enter both your AniList username and a manga series name.")
    else:
        # Clear previous state on new run
        st.session_state.report = None
        st.session_state.memory_note = ""

        # Staged rendering — each agent step is visible
        agent_statuses = {}

        with st.status("🔍 Running MangaScope analysis...", expanded=True) as status:
            step_containers = {
                "progress": st.empty(),
                "tracker": st.empty(),
                "recommendation": st.empty(),
                "community": st.empty(),
            }

            step_labels = {
                "progress": "📖 Progress Agent",
                "tracker": "📺 Adaptation Tracker",
                "recommendation": "🗺️ Recommendation Agent",
                "community": "💬 Community Agent",
            }

            # Initialize all steps as pending
            for key, container in step_containers.items():
                container.markdown(f"{step_labels[key]}: ⏳ Pending...")

            def on_step(step_name: str, msg: str):
                """Callback from coordinator to update UI per-agent."""
                if step_name in step_containers:
                    if msg.startswith("Done") or msg.startswith("Skipped"):
                        step_containers[step_name].markdown(
                            f"{step_labels[step_name]}: ✅ {msg}"
                        )
                    else:
                        step_containers[step_name].markdown(
                            f"{step_labels[step_name]}: ⏳ {msg}"
                        )

            # Run the coordinator (fetch_community=False by default to avoid spoilers/save API calls)
            result = coordinator_run(username, series_name, on_step=on_step, fetch_community=False)

            if result.validation_error:
                status.update(label="❌ Validation failed", state="error")
                st.error(result.validation_error)
            elif result.report is None:
                status.update(label="❌ Analysis failed", state="error")
                st.error("An unexpected error occurred. Please try again.")
            else:
                status.update(label="✅ Analysis complete!", state="complete")
                st.session_state.report = result.report
                st.session_state.memory_note = result.memory_note

# ── Render Results ───────────────────────────────────────────────────────────

if st.session_state.report:
    report = st.session_state.report
    memory_note = st.session_state.memory_note

    st.markdown(f"### Results for **{esc(report.series)}** — *{esc(report.username)}*")

    # Memory note
    if memory_note:
        st.markdown(
            f'<div class="memory-note">ℹ️ {esc(memory_note)}</div>',
            unsafe_allow_html=True,
        )

    st.markdown("")  # spacer

    # ── Progress Card ────────────────────────────────────────────
    if report.progress.agent_status == "success":
        st.markdown(f"""
<div class="result-card">
    <h3>📖 Your Progress</h3>
    <div class="stat-row">
        <div class="stat-pill">Status: <strong>{esc(report.progress.status)}</strong></div>
        <div class="stat-pill">Chapters Read: <strong>{esc(report.progress.chapters_read)}</strong></div>
        <div class="stat-pill">Volumes Read: <strong>{esc(report.progress.volumes_read)}</strong></div>
        {"<div class='stat-pill'>Score: <strong>" + str(report.progress.user_score) + "/10</strong></div>" if report.progress.user_score else ""}
    </div>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
<div class="fallback-badge">
    <span class="badge-icon">⚠️</span>
    <strong>Progress Agent:</strong> {esc(report.progress.message or "Could not retrieve reading progress from AniList.")}
</div>
""", unsafe_allow_html=True)

    # ── Adaptation Card ──────────────────────────────────────────
    if report.adaptation.agent_status == "success":
        conf_class = f"confidence-{report.adaptation.confidence}"
        st.markdown(f"""
<div class="result-card">
    <h3>📺 Anime Adaptation</h3>
    <div class="stat-row">
        <div class="stat-pill">Anime: <strong>{esc(report.adaptation.anime_status)}</strong></div>
        {"<div class='stat-pill'>Episodes Aired: <strong>" + str(report.adaptation.anime_episodes_aired) + "</strong></div>" if report.adaptation.anime_episodes_aired else ""}
        {"<div class='stat-pill'>Safe Resume: <strong>Chapter " + str(report.adaptation.safe_resume_chapter) + "</strong></div>" if report.adaptation.safe_resume_chapter else ""}
        <div class="stat-pill">Confidence: <span class="{conf_class}">{esc(report.adaptation.confidence.upper())}</span></div>
    </div>
    <div class="card-note">{esc(report.adaptation.note)}</div>
</div>
""", unsafe_allow_html=True)

        # Add dynamic mapping lifecycle verification button if confidence is low
        if report.adaptation.confidence == "low":
            col_btn, _ = st.columns([1, 2])
            with col_btn:
                btn_key = f"verify_{report.series.lower().replace(' ', '_')}"
                if st.button("🔒 Verify & Lock Mapping", key=btn_key, use_container_width=True):
                    from agents import tracker_agent
                    success = tracker_agent.register_verified_mapping(
                        series_name=report.series,
                        mapping_data={
                            "anime_status": report.adaptation.anime_status,
                            "anime_episodes_aired": report.adaptation.anime_episodes_aired,
                            "manga_chapter_equivalent": report.adaptation.manga_chapter_equivalent,
                            "safe_resume_chapter": report.adaptation.safe_resume_chapter,
                            "confidence": "high",
                            "note": f"{report.adaptation.note.replace('[Chapter mapping estimated via web search. Verify before reading to avoid spoilers.]', '').strip()} (User Verified)",
                        }
                    )
                    if success:
                        st.success("Mapping locked successfully! Refresh or search again to see updated status.")
                        st.rerun()
                    else:
                        st.error("Failed to save mapping to verified mappings list.")
    else:
        st.markdown(f"""
<div class="fallback-badge">
    <span class="badge-icon">⚠️</span>
    <strong>Adaptation Tracker:</strong> {esc(report.adaptation.message or "Could not determine anime-to-manga chapter mapping.")}
</div>
""", unsafe_allow_html=True)

    # ── Recommendation Card ──────────────────────────────────────
    if report.recommendation.agent_status == "success":
        priority = report.recommendation.reading_priority
        priority_class = "priority-up-to-date" if priority == "up_to_date" else "priority-high"
        priority_label = "UP TO DATE" if priority == "up_to_date" else priority.upper()

        arc_info = ""
        if report.recommendation.next_arc:
            chapter_range = f"Ch. {report.recommendation.start_chapter}"
            if report.recommendation.end_chapter:
                chapter_range += f" → {report.recommendation.end_chapter}"
            else:
                chapter_range += " → ongoing"
            
            remaining_pill = ""
            if report.recommendation.estimated_chapters_remaining is not None:
                remaining_pill = f'<div class="stat-pill">~{report.recommendation.estimated_chapters_remaining} chapters remaining</div>'
            
            arc_info = (
                f'<div class="card-value" style="font-size: 1.3rem; margin-top: 0.5rem;">{esc(report.recommendation.next_arc)}</div>'
                f'<div class="stat-row">'
                f'<div class="stat-pill">{chapter_range}</div>'
                f'{remaining_pill}'
                f'</div>'
            )

        st.markdown(f"""
<div class="result-card">
    <h3>🗺️ What to Read Next <span class="{priority_class}">{priority_label}</span></h3>
    {arc_info}
    <div class="card-note">{esc(report.recommendation.description)}</div>
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
<div class="fallback-badge">
    <span class="badge-icon">⚠️</span>
    <strong>Recommendation Agent:</strong> {esc(report.recommendation.message or "Could not generate reading recommendation.")}
</div>
""", unsafe_allow_html=True)

    # ── Community Card ───────────────────────────────────────────
    if report.community_context.agent_status == "success":
        st.markdown(f"""
<div class="result-card">
    <h3>💬 Community Buzz</h3>
    <div style="font-size: 1rem; color: #ddd; margin-top: 0.5rem; line-height: 1.6;">
        {esc(report.community_context.top_discussion_summary)}
    </div>
    <div style="margin-top: 0.5rem; font-size: 0.78rem; color: #888;">Source: {esc(report.community_context.source)}</div>
</div>
""", unsafe_allow_html=True)
    elif report.community_context.agent_status == "skipped":
        st.markdown(f"""
<div class="result-card" style="border: 1px dashed rgba(102, 126, 234, 0.45);">
    <h3>💬 Community Buzz</h3>
    <div style="font-size: 0.95rem; color: #aaa; margin-top: 0.5rem; font-style: italic; margin-bottom: 1rem;">
        ⚠️ Community discussion summaries may contain major manga spoilers. Fetch only if you want to see them.
    </div>
</div>
""", unsafe_allow_html=True)
        
        # On-demand community fetch button (Search Grounded)
        col_c_btn, _ = st.columns([1, 1])
        with col_c_btn:
            if st.button("💬 Fetch Community Buzz", key="fetch_community_buzz_on_demand", use_container_width=True):
                with st.spinner("💬 Fetching recent community discussions..."):
                    from agents import community_agent
                    comm_res = community_agent.run(report.series)
                    st.session_state.report.community_context = comm_res
                    
                    # Update memory.json with final state
                    try:
                        from memory import save_memory
                        save_memory(
                            username=report.username,
                            series=report.series,
                            chapters_read=report.progress.chapters_read,
                            recommendation_given=report.recommendation.next_arc,
                        )
                    except Exception:
                        pass
                    st.rerun()
    else:
        st.markdown(f"""
<div class="fallback-badge">
    <span class="badge-icon">⚠️</span>
    <strong>Community Agent:</strong> {esc(report.community_context.message or "Could not retrieve community discussion.")}
</div>
""", unsafe_allow_html=True)

    # ── Footer ──────────────────────────────────────────────────
    st.markdown(f"""
<div class="footer">
    Generated at {esc(report.generated_at)} · MangaScope v1.0
</div>
""", unsafe_allow_html=True)
