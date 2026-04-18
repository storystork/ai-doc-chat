#import os
#import re
#import time
#import threading
#import mimetypes
#import shutil
#from datetime import datetime, timezone
#from typing import Any, Dict, List, Optional
#
#import streamlit as st
#from dotenv import load_dotenv
#from streamlit_webrtc import WebRtcMode, webrtc_streamer
#
#from ai_pipeline import (
#    answer_with_rag,
#    ingest_document,
#    preview_document_text,
#    sha256_file,
#    summarize_chat,
#)
#from auth import login as auth_login
#from auth import signup as auth_signup
#from database import Database
#from payments import (
#    FREE_QUERIES_PER_DAY,
#    FREE_UPLOADS_PER_DAY,
#    create_checkout_session,
#    handle_payment_success,
#)
#from utils.pdf_export import export_chat_to_pdf_bytes
#from utils.voice import AudioBufferProcessor, transcribe_wav_bytes
#
#
#load_dotenv()
#
#PROJECT_TITLE = "AI Personal Knowledge Base – Chat with Your Documents"
#
#
#def _safe_filename(name: str) -> str:
#    name = name.strip()
#    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
#    return name[:180] if len(name) > 180 else name
#
#
#def _utc_date_key() -> str:
#    return datetime.now(timezone.utc).date().isoformat()
#
#
#def _typing_animation(placeholder, stop_event: threading.Event) -> None:
#    i = 0
#    while not stop_event.is_set():
#        dots = "." * (i % 4)
#        placeholder.markdown(f"**AI is typing**{dots}")
#        i += 1
#        time.sleep(0.35)
#
#
#def _apply_theme(dark_mode: bool) -> None:
#    if dark_mode:
#        st.markdown(
#            """
#            <style>
#            :root { --bg: #0b1220; --card: #111b2e; --text: #e6edf7; --muted: #9aa7bd; --border: rgba(255,255,255,.08); }
#            .stApp { background: var(--bg); color: var(--text); }
#            section[data-testid="stSidebar"] { background: #0a0f1a; }
#            div[data-testid="stMarkdownContainer"] { color: var(--text); }
#            .card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 14px; }
#            </style>
#            """,
#            unsafe_allow_html=True,
#        )
#    else:
#        st.markdown(
#            """
#            <style>
#            .card { background: #ffffff; border: 1px solid rgba(0,0,0,.08); border-radius: 14px; padding: 14px; }
#            </style>
#            """,
#            unsafe_allow_html=True,
#        )
#
#
#def _get_env(name: str, default: str = "") -> str:
#    return os.getenv(name, default).strip()
#
#
#def _create_or_get_default_chat(db: Database, user_id: int) -> int:
#    sessions = db.list_chat_sessions(user_id=user_id, limit=1)
#    if sessions:
#        return sessions[0]["id"]
#    return db.create_chat_session(user_id=user_id, title="New chat")
#
#
#def main():
#    st.set_page_config(page_title=PROJECT_TITLE, page_icon=":robot:", layout="wide")
#
#    base_dir = os.path.dirname(os.path.abspath(__file__))
#
#    dark_mode = st.sidebar.checkbox("Dark mode", value=True)
#    _apply_theme(dark_mode)
#
#    # Initialize database
#    db = Database(db_path=os.path.join(base_dir, "data", "app.db"))
#
#    # Streamlit session state
#    if "user_id" not in st.session_state:
#        st.session_state.user_id = None
#    if "active_chat_id" not in st.session_state:
#        st.session_state.active_chat_id = None
#    if "llm_provider" not in st.session_state:
#        st.session_state.llm_provider = _get_env("LLM_PROVIDER", "openai") or "openai"
#    if "embeddings_provider" not in st.session_state:
#        # Allow users to set embeddings provider independently later
#        st.session_state.embeddings_provider = None
#
#    # Handle Stripe success redirect
#    payment_status = st.query_params.get("payment")
#    if payment_status == "success":
#        session_id = st.query_params.get("session_id")
#        if session_id:
#            try:
#                ok = handle_payment_success(db=db, session_id=session_id)
#                if ok:
#                    st.success("Payment successful. Your plan has been upgraded.")
#                    st.rerun()
#                else:
#                    st.info("Payment completed (verification pending/failed). Try again on next refresh.")
#            except Exception as e:
#                st.warning(f"Payment verification skipped/failed: {e}")
#
#    if st.session_state.user_id is None:
#        st.markdown(f"## {PROJECT_TITLE}")
#        st.markdown(
#            """
#            <div class="card">
#            Upload your documents and ask questions with Retrieval-Augmented Generation (RAG).
#            </div>
#            """,
#            unsafe_allow_html=True,
#        )
#
#        auth_mode = st.tabs(["Login", "Sign Up"])
#        with auth_mode[0]:
#            st.subheader("Login")
#            email = st.text_input("Email", key="login_email")
#            password = st.text_input("Password", type="password", key="login_password")
#            if st.button("Login", type="primary", key="login_button"):
#                ok, user, msg = auth_login(db=db, email=email, password=password)
#                if ok:
#                    st.session_state.user_id = int(user["id"])
#                    st.success("Logged in.")
#                    st.session_state.active_chat_id = _create_or_get_default_chat(db, st.session_state.user_id)
#                    st.rerun()
#                else:
#                    st.error(msg or "Login failed.")
#
#        with auth_mode[1]:
#            st.subheader("Create account")
#            email = st.text_input("Email", key="signup_email")
#            password = st.text_input("Password", type="password", key="signup_password")
#            if st.button("Sign Up", key="signup_button"):
#                ok, msg = auth_signup(db=db, email=email, password=password)
#                if ok:
#                    st.success(msg)
#                    st.info("Now login to continue.")
#                else:
#                    st.error(msg)
#        return
#
#    user_id: int = int(st.session_state.user_id)
#    user = db.get_user_by_id(user_id)
#    if not user:
#        st.session_state.user_id = None
#        st.rerun()
#
#    # Sidebar auth + navigation
#    st.sidebar.markdown("---")
#    st.sidebar.markdown(f"Logged in as: `{user['email']}`")
#    plan = user.get("plan", "free")
#    st.sidebar.markdown(f"Plan: **{plan}**")
#    if st.sidebar.button("Logout"):
#        st.session_state.user_id = None
#        st.session_state.active_chat_id = None
#        st.rerun()
#
#    page = st.sidebar.radio(
#        "Navigation",
#        ["Home", "Upload Documents", "Chat Interface", "History", "Profile / Settings"],
#        index=0,
#    )
#
#    persist_base_dir = os.path.join(base_dir, "vectorstore")
#    upload_base_dir = os.path.join(base_dir, "data", "uploads")
#    user_upload_dir = os.path.join(upload_base_dir, str(user_id))
#    os.makedirs(user_upload_dir, exist_ok=True)
#
#    # ---------------- Home ----------------
#    if page == "Home":
#        stats = db.get_dashboard_stats(user_id=user_id)
#        todays_queries = db.count_today_queries(user_id=user_id)
#        todays_uploads = db.count_today_uploads(user_id=user_id)
#
#        st.markdown("## Dashboard")
#        st.markdown(
#            f"""
#            <div class="card">
#              <b>Today</b><br/>
#              Queries: <b>{todays_queries}</b> / {FREE_QUERIES_PER_DAY if plan=='free' else '∞'}<br/>
#              Uploads: <b>{todays_uploads}</b> / {FREE_UPLOADS_PER_DAY if plan=='free' else '∞'}<br/>
#            </div>
#            """,
#            unsafe_allow_html=True,
#        )
#        st.markdown(
#            """
#            <div class="card">
#              <b>Your knowledge</b><br/>
#              Documents uploaded (total): <b>{total_docs}</b><br/>
#              Use "Upload Documents" to add content, then "Chat Interface" to query it.
#            </div>
#            """.replace("{total_docs}", str(stats["total_docs"])),
#            unsafe_allow_html=True,
#        )
#
#        if plan == "free":
#            st.subheader("Upgrade for unlimited queries")
#            col1, col2 = st.columns([2, 1])
#            with col1:
#                if st.button("Upgrade to Paid (Stripe checkout)", type="primary"):
#                    try:
#                        url = create_checkout_session(user_id=user_id)
#                        st.info("Redirecting to Stripe Checkout...")
#                        st.link_button("Open Checkout", url, use_container_width=True)
#                    except Exception as e:
#                        st.error(f"Unable to start checkout: {e}")
#            with col2:
#                st.caption("You can set Stripe keys in `.env`.")
#
#        st.divider()
#
#    # ---------------- Upload ----------------
#    elif page == "Upload Documents":
#        st.markdown("## Upload Documents")
#        st.caption("Supported formats: PDF, DOCX, TXT")
#
#        todays_uploads = db.count_today_uploads(user_id=user_id)
#        if plan == "free" and todays_uploads >= FREE_UPLOADS_PER_DAY:
#            st.error("Free plan upload limit reached for today. Upgrade to upload more.")
#            st.stop()
#
#        uploaded_files = st.file_uploader(
#            "Choose files",
#            type=["pdf", "docx", "txt"],
#            accept_multiple_files=True,
#        )
#
#        if uploaded_files:
#            st.info(f"Processing {len(uploaded_files)} file(s)...")
#            for f in uploaded_files:
#                safe_name = _safe_filename(f.name)
#                incoming_path = os.path.join(user_upload_dir, f"incoming_{int(time.time())}_{safe_name}")
#                with open(incoming_path, "wb") as out:
#                    out.write(f.getbuffer())
#
#                try:
#                    doc_hash = sha256_file(incoming_path)
#                    final_path = os.path.join(user_upload_dir, f"{doc_hash}__{safe_name}")
#                    if incoming_path != final_path:
#                        os.replace(incoming_path, final_path)
#                    else:
#                        final_path = incoming_path
#
#                    with st.spinner(f"Ingesting: {f.name}"):
#                        result = ingest_document(
#                            db=db,
#                            user_id=user_id,
#                            file_path=final_path,
#                            persist_base_dir=persist_base_dir,
#                            embeddings=None,
#                            llm_provider=st.session_state.llm_provider,
#                        )
#
#                    if result.get("status") == "cached":
#                        st.success(f"Cached embeddings for: {f.name}")
#                    else:
#                        st.success(f"Ingested: {f.name} ({result.get('chunk_count')} chunks)")
#                except Exception as e:
#                    st.error(f"Failed processing {f.name}: {e}")
#
#        st.divider()
#        st.subheader("Your documents")
#        docs = db.list_documents(user_id=user_id)
#        if not docs:
#            st.caption("No documents yet.")
#        for d in docs:
#            doc_hash = d["doc_hash"]
#            st.markdown(
#                f"""
#                <div class="card">
#                  <b>{d['file_name']}</b><br/>
#                  Type: {d.get('file_mime') or 'unknown'}<br/>
#                  Chunks: {d.get('chunk_count') or 0}<br/>
#                  Doc hash: `{doc_hash[:10]}...`
#                </div>
#                """,
#                unsafe_allow_html=True,
#            )
#            del_col1, view_col, del_col2 = st.columns([4, 1, 1])
#            with view_col:
#                if st.button("View", key=f"view_{doc_hash}"):
#                    file_path = None
#                    for name in os.listdir(user_upload_dir):
#                        if name.startswith(f"{doc_hash}__"):
#                            file_path = os.path.join(user_upload_dir, name)
#                            break
#                    if file_path and os.path.exists(file_path):
#                        preview = preview_document_text(file_path)
#                        st.info(preview)
#                    else:
#                        st.warning("File not found on disk.")
#
#            with del_col2:
#                if st.button("Delete", key=f"del_{doc_hash}"):
#                    # Minimal delete: remove SQL record + delete uploaded file.
#                    try:
#                        db.delete_document(user_id=user_id, doc_hash=doc_hash)
#                        # Delete file(s) that match prefix
#                        for name in os.listdir(user_upload_dir):
#                            if name.startswith(f"{doc_hash}__"):
#                                os.remove(os.path.join(user_upload_dir, name))
#
#                        # Rebuild vectorstore to ensure the bot doesn't retrieve deleted chunks.
#                        vectorstore_dir = os.path.join(persist_base_dir, str(user_id))
#                        shutil.rmtree(vectorstore_dir, ignore_errors=True)
#
#                        remaining_docs = db.list_documents(user_id=user_id)
#                        if remaining_docs:
#                            with st.spinner("Rebuilding vector index..."):
#                                for rd in remaining_docs:
#                                    rd_hash = rd["doc_hash"]
#                                    file_path = None
#                                    for name in os.listdir(user_upload_dir):
#                                        if name.startswith(f"{rd_hash}__"):
#                                            file_path = os.path.join(user_upload_dir, name)
#                                            break
#                                    if file_path and os.path.exists(file_path):
#                                        ingest_document(
#                                            db=db,
#                                            user_id=user_id,
#                                            file_path=file_path,
#                                            persist_base_dir=persist_base_dir,
#                                            embeddings=None,
#                                            llm_provider=st.session_state.llm_provider,
#                                            force_reingest=True,
#                                        )
#                        st.success("Document deleted and vector index rebuilt.")
#                        st.rerun()
#                    except Exception as e:
#                        st.error(f"Delete failed: {e}")
#
#    # ---------------- Chat ----------------
#    elif page == "Chat Interface":
#        st.markdown("## Chat Interface")
#
#        # Build chat session selection / creation
#        left, right = st.columns([1, 3])
#        with left:
#            st.subheader("Chats")
#            sessions = db.list_chat_sessions(user_id=user_id, limit=50)
#            chat_titles = {s["id"]: s["title"] for s in sessions}
#
#            if st.session_state.active_chat_id is None and sessions:
#                st.session_state.active_chat_id = sessions[0]["id"]
#
#            active_id = st.session_state.active_chat_id
#            selected = st.selectbox(
#                "Select session",
#                options=[s["id"] for s in sessions],
#                format_func=lambda cid: chat_titles.get(cid, "Chat"),
#                index=0 if active_id in chat_titles else 0,
#            ) if sessions else None
#
#            if selected is not None:
#                st.session_state.active_chat_id = int(selected)
#
#            if st.button("New chat"):
#                title = f"Chat {len(sessions) + 1}"
#                st.session_state.active_chat_id = db.create_chat_session(user_id=user_id, title=title)
#                st.rerun()
#
#        with right:
#            chat_id = st.session_state.active_chat_id
#            if chat_id is None:
#                st.caption("Create or select a chat session.")
#                st.stop()
#
#            messages = db.get_chat_messages(chat_session_id=chat_id)
#            chat_title = "Chat"
#            for s in sessions:
#                if int(s["id"]) == int(chat_id):
#                    chat_title = s.get("title") or "Chat"
#                    break
#
#            top_left, top_right = st.columns([2, 1])
#            with top_left:
#                if messages:
#                    pdf_bytes = export_chat_to_pdf_bytes(chat_title=chat_title, messages=messages)
#                    st.download_button(
#                        "Download chat as PDF",
#                        data=pdf_bytes,
#                        file_name=f"{_safe_filename(chat_title)}.pdf",
#                        mime="application/pdf",
#                        use_container_width=True,
#                    )
#            with top_right:
#                if st.button("Summarize chat", use_container_width=True):
#                    openai_api_key = _get_env("OPENAI_API_KEY", "")
#                    try:
#                        with st.spinner("Summarizing..."):
#                            summary = summarize_chat(
#                                messages=messages,
#                                llm_provider=st.session_state.llm_provider,
#                                openai_api_key=openai_api_key,
#                            )
#                        db.save_chat_message(
#                            chat_session_id=chat_id,
#                            role="assistant",
#                            content=summary,
#                            metadata={"type": "summary"},
#                        )
#                        st.success("Summary added to chat.")
#                        st.rerun()
#                    except Exception as e:
#                        st.error(f"Summarization failed: {e}")
#
#            for m in messages:
#                with st.chat_message(m["role"]):
#                    st.write(m["content"])
#                    if m["role"] == "assistant" and m.get("metadata"):
#                        md = m["metadata"] or {}
#                        sources = md.get("sources") or []
#                        if sources:
#                            st.caption("Sources: " + ", ".join(sources[:5]))
#                        if "sentiment" in md:
#                            sent = md["sentiment"]
#                            if isinstance(sent, dict) and sent.get("label"):
#                                st.caption(f"Query sentiment: {sent['label']}")
#
#            # -------- Prompt input (text + optional voice) --------
#            prompt_key = f"prompt_text_{chat_id}"
#            clear_key = f"{prompt_key}__clear"
#
#            # Clear the prompt *before* creating widgets that use `prompt_key`.
#            if st.session_state.get(clear_key):
#                st.session_state[prompt_key] = ""
#                st.session_state[clear_key] = False
#
#            if prompt_key not in st.session_state:
#                st.session_state[prompt_key] = ""
#
#            openai_api_key = _get_env("OPENAI_API_KEY", "")
#            with st.expander("Voice input (optional)", expanded=False):
#                if not openai_api_key:
#                    st.warning("Voice transcription requires `OPENAI_API_KEY`. Add it in your `.env` file.")
#                else:
#                    webrtc_ctx = webrtc_streamer(
#                        key=f"voice_{chat_id}",
#                        mode=WebRtcMode.SENDRECV,
#                        media_stream_constraints={"audio": True, "video": False},
#                        audio_processor_factory=AudioBufferProcessor,
#                    )
#
#                    if st.button("Transcribe voice", key=f"transcribe_{chat_id}"):
#                        try:
#                            processor = getattr(webrtc_ctx, "audio_processor", None)
#                            if not processor:
#                                st.warning("No audio recorded yet. Click and speak, then try again.")
#                            else:
#                                wav_bytes = processor.to_wav_bytes(max_seconds=15)
#                                transcript = transcribe_wav_bytes(wav_bytes, openai_api_key=openai_api_key).text
#                                if transcript.strip():
#                                    st.session_state[prompt_key] = transcript.strip()
#                                    st.success("Transcript inserted into the prompt box.")
#                                    processor.reset()
#                                else:
#                                    st.warning("Could not transcribe audio. Try again.")
#                        except Exception as e:
#                            st.error(f"Voice transcription failed: {e}")
#
#            prompt_text = st.text_area(
#                "Ask a question about your documents",
#                value=st.session_state.get(prompt_key, ""),
#                key=prompt_key,
#                height=90,
#                placeholder="Type your question or record voice..."
#            )
#
#            send_clicked = st.button("Send", type="primary", use_container_width=True, disabled=not prompt_text.strip())
#            if send_clicked:
#                user_prompt = prompt_text.strip()
#                # Clear on next run to avoid mutating widget-backed state after widget creation.
#                st.session_state[clear_key] = True
#
#                # Usage limit check
#                todays_queries = db.count_today_queries(user_id=user_id)
#                if plan == "free" and todays_queries >= FREE_QUERIES_PER_DAY:
#                    st.error("Daily query limit reached. Upgrade to Paid to continue.")
#                    st.info("Go to Profile / Settings to upgrade.")
#                    st.stop()
#
#                db.save_chat_message(chat_session_id=chat_id, role="user", content=user_prompt)
#                db.log_query(user_id=user_id, model=st.session_state.llm_provider)
#
#                with st.chat_message("assistant"):
#                    placeholder = st.empty()
#                    stop_event = threading.Event()
#                    thread = threading.Thread(target=_typing_animation, args=(placeholder, stop_event))
#                    thread.start()
#
#                    try:
#                        with st.spinner("Retrieving and generating..."):
#                            result = answer_with_rag(
#                                db=db,
#                                user_id=user_id,
#                                query=user_prompt,
#                                persist_base_dir=persist_base_dir,
#                                embeddings=None,
#                                llm_provider=st.session_state.llm_provider,
#                                openai_api_key=openai_api_key,
#                                top_k=5,
#                            )
#                        stop_event.set()
#                        thread.join(timeout=1.0)
#
#                        placeholder.empty()
#                        st.write(result["answer"])
#
#                        meta = {
#                            "sources": result.get("sources", []),
#                            "sentiment": result.get("sentiment"),
#                        }
#                        db.save_chat_message(
#                            chat_session_id=chat_id,
#                            role="assistant",
#                            content=result["answer"],
#                            metadata=meta,
#                        )
#                        st.caption("Tip: Add more documents for better answers.")
#                        st.rerun()
#                    except Exception as e:
#                        stop_event.set()
#                        thread.join(timeout=1.0)
#                        placeholder.empty()
#                        st.error(f"Failed to answer: {e}")
#
#    # ---------------- History ----------------
#    elif page == "History":
#        st.markdown("## History & Search")
#        sessions = db.list_chat_sessions(user_id=user_id, limit=50)
#        if not sessions:
#            st.caption("No history yet.")
#            st.stop()
#
#        query = st.text_input("Search chats (title or message text)")
#        if query.strip():
#            filtered = db.search_chat_sessions(user_id=user_id, query=query, limit=50)
#        else:
#            filtered = sessions
#
#        for s in filtered:
#            if st.button(f'{s["title"]}', key=f"hist_{s['id']}"):
#                st.session_state.active_chat_id = s["id"]
#                st.rerun()
#        st.caption("Select a chat to view it in the Chat Interface tab.")
#
#    # ---------------- Profile ----------------
#    elif page == "Profile / Settings":
#        st.markdown("## Profile / Settings")
#        st.write(f"Email: {user['email']}")
#        st.write(f"Plan: {plan}")
#
#        st.subheader("LLM provider")
#        st.session_state.llm_provider = st.selectbox(
#            "Model backend",
#            options=["openai", "ollama"],
#            index=0 if st.session_state.llm_provider == "openai" else 1,
#        )
#        if st.session_state.llm_provider == "ollama":
#            st.caption("Ensure Ollama is running and set `OLLAMA_BASE_URL` if not default.")
#
#        st.divider()
#        if plan == "free":
#            st.subheader("Upgrade")
#            if st.button("Checkout for Paid plan", type="primary"):
#                try:
#                    url = create_checkout_session(user_id=user_id)
#                    st.link_button("Open Stripe Checkout", url, use_container_width=True)
#                except Exception as e:
#                    st.error(f"Checkout failed: {e}")
#        else:
#            st.success("You are on the paid plan.")
#
#
#if __name__ == "__main__":
#    main()
#
#


import os
import re
import time
import threading
import mimetypes
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import streamlit as st
from dotenv import load_dotenv

from ai_pipeline import (
    answer_with_rag,
    ingest_document,
    preview_document_text,
    sha256_file,
    summarize_chat,
)
from auth import login as auth_login
from auth import signup as auth_signup
from auth import get_google_auth_url, exchange_google_code, google_auth_or_signup
from database import Database
from payments import (
    FREE_QUERIES_PER_DAY,
    FREE_UPLOADS_PER_DAY,
    create_checkout_session,
    handle_payment_success,
)
from utils.pdf_export import export_chat_to_pdf_bytes

try:
    from streamlit_webrtc import WebRtcMode, webrtc_streamer
    from utils.voice import AudioBufferProcessor, transcribe_wav_bytes
    VOICE_AVAILABLE = True
except Exception:
    VOICE_AVAILABLE = False

load_dotenv()

PROJECT_TITLE = "DocMind AI"
NAV_PAGES = ["Home", "Upload", "Chat", "History", "Settings"]


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name)
    return name[:180]


def _get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _create_or_get_default_chat(db: Database, user_id: int) -> int:
    sessions = db.list_chat_sessions(user_id=user_id, limit=1)
    if sessions:
        return sessions[0]["id"]
    return db.create_chat_session(user_id=user_id, title="New chat")


def _typing_animation(placeholder, stop_event: threading.Event) -> None:
    frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    i = 0
    while not stop_event.is_set():
        placeholder.markdown(f"<span style='color:#60a5fa;font-size:1.1rem'>{frames[i % len(frames)]} Thinking…</span>", unsafe_allow_html=True)
        i += 1
        time.sleep(0.1)


# ─────────────────────────────────────────────
#  Global Dark Theme CSS
# ─────────────────────────────────────────────

DARK_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Reset & Base ── */
*, *::before, *::after { box-sizing: border-box; }

:root {
  --bg:          #080c14;
  --surface:     #0d1424;
  --surface-2:   #111d30;
  --surface-3:   #162035;
  --border:      rgba(96,165,250,0.12);
  --border-2:    rgba(96,165,250,0.22);
  --accent:      #3b82f6;
  --accent-2:    #60a5fa;
  --accent-glow: rgba(59,130,246,0.25);
  --text:        #e2e8f4;
  --text-muted:  #7b8db0;
  --text-dim:    #4a5568;
  --success:     #10b981;
  --warning:     #f59e0b;
  --danger:      #ef4444;
  --radius:      10px;
  --radius-lg:   16px;
  --shadow:      0 4px 24px rgba(0,0,0,0.5);
  --font:        'Inter', sans-serif;
  --mono:        'JetBrains Mono', monospace;
}

/* ── Full app background ── */
html, body, .stApp {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: var(--font) !important;
}

/* ── Hide Streamlit chrome ── */
#MainMenu, footer, header,
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] { display: none !important; }

/* ── Kill default sidebar ── */
section[data-testid="stSidebar"] { display: none !important; }

/* ── Main content padding ── */
.main .block-container {
  padding: 80px 28px 40px !important;
  max-width: 1200px !important;
  margin: 0 auto !important;
}

/* ══════════════════════════════════════
   TOP NAVBAR
══════════════════════════════════════ */
.navbar {
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: 9999;
  height: 60px;
  background: rgba(8,12,20,0.92);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 28px;
  gap: 0;
}
.navbar-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--accent-2);
  letter-spacing: -0.02em;
  white-space: nowrap;
  margin-right: 40px;
}
.navbar-brand svg { flex-shrink: 0; }
.navbar-links {
  display: flex;
  align-items: center;
  gap: 2px;
  flex: 1;
}
.nav-btn {
  background: transparent;
  border: none;
  color: var(--text-muted);
  font-family: var(--font);
  font-size: 0.875rem;
  font-weight: 500;
  padding: 6px 14px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.15s ease;
  white-space: nowrap;
}
.nav-btn:hover { background: var(--surface-2); color: var(--text); }
.nav-btn.active { background: var(--accent-glow); color: var(--accent-2); }
.navbar-right {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}
.user-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 40px;
  padding: 5px 14px 5px 8px;
  font-size: 0.8rem;
  color: var(--text-muted);
}
.user-avatar {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  display: flex; align-items: center; justify-content: center;
  font-size: 0.7rem; font-weight: 700; color: white;
}
.plan-badge {
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 0.7rem;
  font-weight: 600;
  background: var(--accent-glow);
  color: var(--accent-2);
  border: 1px solid var(--border-2);
}
.plan-badge.paid {
  background: rgba(16,185,129,0.15);
  color: #34d399;
  border-color: rgba(16,185,129,0.3);
}

/* ══════════════════════════════════════
   CARDS
══════════════════════════════════════ */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 22px;
  margin-bottom: 16px;
  transition: border-color 0.2s;
}
.card:hover { border-color: var(--border-2); }
.card-sm {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 16px;
  margin-bottom: 12px;
}
.card-title {
  font-size: 0.7rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 4px;
}
.card-value {
  font-size: 2rem;
  font-weight: 700;
  color: var(--text);
  line-height: 1;
}
.card-sub {
  font-size: 0.78rem;
  color: var(--text-muted);
  margin-top: 4px;
}

/* ══════════════════════════════════════
   STAT GRID
══════════════════════════════════════ */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 14px;
  margin-bottom: 24px;
}

/* ══════════════════════════════════════
   PROGRESS BAR
══════════════════════════════════════ */
.progress-wrap { margin-top: 6px; }
.progress-label {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-bottom: 4px;
}
.progress-track {
  height: 4px;
  background: var(--surface-3);
  border-radius: 4px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-2));
  border-radius: 4px;
  transition: width 0.4s ease;
}

/* ══════════════════════════════════════
   SECTION HEADERS
══════════════════════════════════════ */
.section-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 20px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.section-title {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--text);
  margin: 0;
}
.section-icon {
  width: 32px; height: 32px;
  border-radius: 8px;
  background: var(--accent-glow);
  display: flex; align-items: center; justify-content: center;
  font-size: 1rem;
}

/* ══════════════════════════════════════
   DOC CARDS
══════════════════════════════════════ */
.doc-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 18px;
  margin-bottom: 10px;
  display: flex;
  align-items: flex-start;
  gap: 14px;
  transition: border-color 0.2s, transform 0.15s;
}
.doc-card:hover { border-color: var(--border-2); transform: translateY(-1px); }
.doc-icon {
  width: 40px; height: 40px; flex-shrink: 0;
  border-radius: 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  display: flex; align-items: center; justify-content: center;
  font-size: 1.2rem;
}
.doc-info { flex: 1; min-width: 0; }
.doc-name {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.doc-meta {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-top: 3px;
}
.doc-hash {
  font-family: var(--mono);
  font-size: 0.68rem;
  color: var(--text-dim);
  margin-top: 2px;
}

/* ══════════════════════════════════════
   CHAT MESSAGES
══════════════════════════════════════ */
.chat-wrap {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 520px;
  overflow-y: auto;
  padding: 4px 0 12px;
  scrollbar-width: thin;
  scrollbar-color: var(--surface-3) transparent;
}
.chat-wrap::-webkit-scrollbar { width: 5px; }
.chat-wrap::-webkit-scrollbar-thumb { background: var(--surface-3); border-radius: 4px; }
.msg-row { display: flex; gap: 10px; align-items: flex-start; }
.msg-row.user { flex-direction: row-reverse; }
.msg-avatar {
  width: 30px; height: 30px; flex-shrink: 0;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 0.75rem; font-weight: 700;
}
.msg-avatar.ai { background: linear-gradient(135deg, #3b82f6, #06b6d4); }
.msg-avatar.user { background: linear-gradient(135deg, #8b5cf6, #ec4899); }
.msg-bubble {
  max-width: 75%;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 0.88rem;
  line-height: 1.6;
}
.msg-bubble.ai {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text);
  border-top-left-radius: 4px;
}
.msg-bubble.user {
  background: var(--accent);
  color: white;
  border-top-right-radius: 4px;
}
.msg-sources {
  font-size: 0.7rem;
  color: var(--text-muted);
  margin-top: 6px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}
.msg-sentiment {
  font-size: 0.68rem;
  color: var(--text-dim);
  margin-top: 3px;
}

/* ══════════════════════════════════════
   HISTORY ITEMS
══════════════════════════════════════ */
.hist-item {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 16px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.15s;
}
.hist-item:hover { border-color: var(--border-2); background: var(--surface-2); }
.hist-title { font-size: 0.88rem; font-weight: 600; color: var(--text); }
.hist-date { font-size: 0.72rem; color: var(--text-muted); margin-top: 3px; }

/* ══════════════════════════════════════
   UPGRADE BANNER
══════════════════════════════════════ */
.upgrade-banner {
  background: linear-gradient(135deg, rgba(59,130,246,0.12), rgba(139,92,246,0.12));
  border: 1px solid rgba(59,130,246,0.3);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}
.upgrade-text h3 { font-size: 1rem; font-weight: 700; color: var(--text); margin: 0 0 4px; }
.upgrade-text p { font-size: 0.82rem; color: var(--text-muted); margin: 0; }

/* ══════════════════════════════════════
   SETTINGS
══════════════════════════════════════ */
.settings-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 0;
  border-bottom: 1px solid var(--border);
}
.settings-label { font-size: 0.88rem; font-weight: 500; color: var(--text); }
.settings-desc { font-size: 0.75rem; color: var(--text-muted); margin-top: 2px; }

/* ══════════════════════════════════════
   AUTH PANEL
══════════════════════════════════════ */
.auth-wrap {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}
.auth-card {
  width: 100%;
  max-width: 420px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 36px 32px;
  box-shadow: var(--shadow);
}
.auth-logo {
  text-align: center;
  margin-bottom: 28px;
}
.auth-logo-icon {
  width: 52px; height: 52px;
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  border-radius: 14px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  margin-bottom: 12px;
}
.auth-logo h1 {
  font-size: 1.5rem;
  font-weight: 800;
  color: var(--text);
  margin: 0 0 4px;
}
.auth-logo p { font-size: 0.82rem; color: var(--text-muted); margin: 0; }
.auth-tabs {
  display: flex;
  background: var(--surface-2);
  border-radius: var(--radius);
  padding: 3px;
  margin-bottom: 24px;
}
.auth-tab {
  flex: 1; text-align: center;
  padding: 7px;
  border-radius: 7px;
  font-size: 0.85rem;
  font-weight: 500;
  cursor: pointer;
  color: var(--text-muted);
  border: none;
  background: transparent;
  transition: all 0.15s;
}
.auth-tab.active { background: var(--surface-3); color: var(--text); }

/* ══════════════════════════════════════
   STREAMLIT OVERRIDES
══════════════════════════════════════ */
/* Inputs */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea {
  background: var(--surface-2) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  color: var(--text) !important;
  font-family: var(--font) !important;
  font-size: 0.88rem !important;
  padding: 10px 14px !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
  border-color: var(--accent) !important;
  box-shadow: 0 0 0 3px var(--accent-glow) !important;
}
/* Labels */
.stTextInput label, .stTextArea label,
.stSelectbox label, .stFileUploader label {
  color: var(--text-muted) !important;
  font-size: 0.78rem !important;
  font-weight: 500 !important;
  letter-spacing: 0.04em !important;
  text-transform: uppercase !important;
}
/* Primary button */
.stButton > button[kind="primary"],
.stButton > button[data-testid*="primary"] {
  background: var(--accent) !important;
  color: white !important;
  border: none !important;
  border-radius: var(--radius) !important;
  font-family: var(--font) !important;
  font-weight: 600 !important;
  font-size: 0.875rem !important;
  padding: 10px 20px !important;
  transition: all 0.15s !important;
  box-shadow: 0 2px 12px rgba(59,130,246,0.35) !important;
}
.stButton > button[kind="primary"]:hover {
  background: #2563eb !important;
  box-shadow: 0 4px 20px rgba(59,130,246,0.5) !important;
  transform: translateY(-1px) !important;
}
/* Secondary button */
.stButton > button[kind="secondary"],
.stButton > button:not([kind="primary"]) {
  background: var(--surface-2) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  font-family: var(--font) !important;
  font-weight: 500 !important;
  font-size: 0.85rem !important;
  transition: all 0.15s !important;
}
.stButton > button:not([kind="primary"]):hover {
  border-color: var(--border-2) !important;
  background: var(--surface-3) !important;
}
/* Selectbox */
.stSelectbox > div > div {
  background: var(--surface-2) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  color: var(--text) !important;
}
/* Tabs */
.stTabs [data-baseweb="tab-list"] {
  background: var(--surface-2) !important;
  border-radius: var(--radius) !important;
  padding: 3px !important;
  border: none !important;
  gap: 2px !important;
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  color: var(--text-muted) !important;
  border-radius: 7px !important;
  font-size: 0.85rem !important;
  font-weight: 500 !important;
}
.stTabs [aria-selected="true"] {
  background: var(--surface-3) !important;
  color: var(--text) !important;
}
.stTabs [data-baseweb="tab-border"] { display: none !important; }
/* Alerts */
.stSuccess, .stError, .stWarning, .stInfo { border-radius: var(--radius) !important; }
.stSuccess > div { background: rgba(16,185,129,0.12) !important; border: 1px solid rgba(16,185,129,0.3) !important; color: #6ee7b7 !important; }
.stError > div { background: rgba(239,68,68,0.1) !important; border: 1px solid rgba(239,68,68,0.3) !important; color: #fca5a5 !important; }
.stWarning > div { background: rgba(245,158,11,0.1) !important; border: 1px solid rgba(245,158,11,0.3) !important; color: #fcd34d !important; }
.stInfo > div { background: rgba(59,130,246,0.1) !important; border: 1px solid rgba(59,130,246,0.25) !important; color: #93c5fd !important; }
/* Divider */
hr { border-color: var(--border) !important; margin: 20px 0 !important; }
/* Spinner */
.stSpinner { color: var(--accent) !important; }
/* Chat messages */
[data-testid="stChatMessage"] {
  background: transparent !important;
  border: none !important;
}
/* File uploader */
[data-testid="stFileUploader"] {
  background: var(--surface-2) !important;
  border: 1px dashed var(--border-2) !important;
  border-radius: var(--radius-lg) !important;
}
[data-testid="stFileUploader"]:hover { border-color: var(--accent) !important; }
/* Download button */
.stDownloadButton > button {
  background: var(--surface-2) !important;
  color: var(--text) !important;
  border: 1px solid var(--border) !important;
  border-radius: var(--radius) !important;
  font-size: 0.85rem !important;
}
/* Columns gap */
[data-testid="column"] { padding: 0 8px !important; }
/* Subheader */
.stMarkdown h2, .stMarkdown h3 { color: var(--text) !important; font-weight: 700 !important; }
h1, h2, h3, h4 { color: var(--text) !important; font-family: var(--font) !important; }
p, li { color: var(--text) !important; font-family: var(--font) !important; }

/* ── Responsive ── */
@media (max-width: 768px) {
  .main .block-container { padding: 72px 14px 32px !important; }
  .navbar { padding: 0 14px; }
  .navbar-brand { margin-right: 16px; }
  .user-pill span.email { display: none; }
  .stats-grid { grid-template-columns: 1fr 1fr; }
  .upgrade-banner { flex-direction: column; align-items: flex-start; }
  .msg-bubble { max-width: 90%; }
}
@media (max-width: 480px) {
  .navbar-links .nav-btn { padding: 6px 9px; font-size: 0.8rem; }
  .stats-grid { grid-template-columns: 1fr; }
}
</style>
#"""
#
#
def _inject_css():
    # Inject the global theme styles once per run.
    st.markdown(DARK_CSS, unsafe_allow_html=True)
#
#
#def _navbar(email: str, plan: str, current_page: str):
#    initials = email[0].upper() if email else "U"
#    plan_cls = "paid" if plan == "paid" else ""
#
#    links_html = ""
#    for p in NAV_PAGES:
#        active_cls = "active" if p == current_page else ""
#        links_html += f'<button class="nav-btn {active_cls}" onclick="window.location.#href=\'?page={p}\'">{p}</button>'

#    navbar_html = f"""
#    <div class="navbar">
#      <div class="navbar-brand">
#        <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
#          <rect width="22" height="22" rx="6" fill="#3b82f6"/>
#          <path d="M6 7h10M6 11h7M6 15h8" stroke="white" stroke-width="1.8" #stroke-linecap="round"/>
#        </svg>
#        {PROJECT_TITLE}
#      </div>
#      <div class="navbar-links">{links_html}</div>
#      <div class="navbar-right">
#        <div class="user-pill">
#          <div class="user-avatar">{initials}</div>
#          <span class="email">{email}</span>
#          <span class="plan-badge {plan_cls}">{plan.upper()}</span>
#        </div>
#      </div>
#    </div>
#    """
#    st.markdown(navbar_html, unsafe_allow_html=True)

def _navbar(email: str, plan: str, current_page: str):
    initials = email[0].upper() if email else "U"
    plan_cls = "paid" if plan == "paid" else ""

    cols = st.columns([1, 5, 2])

    with cols[0]:
        st.markdown(f"**{PROJECT_TITLE}**")

    with cols[1]:
        nav_cols = st.columns(len(NAV_PAGES))
        for i, p in enumerate(NAV_PAGES):
            if nav_cols[i].button(p, key=f"nav_top_{p}"):
                st.session_state.page = p
                st.query_params["page"] = p
                st.rerun()

    with cols[2]:
        st.markdown(f"""
        <div class="user-pill">
          <div class="user-avatar">{initials}</div>
          <span class="email">{email}</span>
          <span class="plan-badge {plan_cls}">{plan.upper()}</span>
        </div>
        """, unsafe_allow_html=True)


def _navbar_auth():
    navbar_html = f"""
    <div class="navbar">
      <div class="navbar-brand">
        <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
          <rect width="22" height="22" rx="6" fill="#3b82f6"/>
          <path d="M6 7h10M6 11h7M6 15h8" stroke="white" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        {PROJECT_TITLE}
      </div>
    </div>
    """
    st.markdown(navbar_html, unsafe_allow_html=True)


def _section_header(icon: str, title: str):
    st.markdown(f"""
    <div class="section-header">
      <div class="section-icon">{icon}</div>
      <h2 class="section-title">{title}</h2>
    </div>
    """, unsafe_allow_html=True)


def _stat_card(title: str, value: str, sub: str = ""):
    st.markdown(f"""
    <div class="card-sm">
      <div class="card-title">{title}</div>
      <div class="card-value">{value}</div>
      {'<div class="card-sub">' + sub + '</div>' if sub else ''}
    </div>
    """, unsafe_allow_html=True)


def _progress_bar(label: str, current: int, limit: int):
    pct = min(100, int(current / max(limit, 1) * 100))
    color = "#ef4444" if pct >= 90 else "#f59e0b" if pct >= 70 else "#3b82f6"
    st.markdown(f"""
    <div class="progress-wrap">
      <div class="progress-label"><span>{label}</span><span>{current} / {limit}</span></div>
      <div class="progress-track">
        <div class="progress-fill" style="width:{pct}%;background:{color}"></div>
      </div>
    </div>
    """, unsafe_allow_html=True)


def _doc_icon(mime: Optional[str]) -> str:
    if mime and "pdf" in mime: return "📄"
    if mime and "word" in mime: return "📝"
    return "📃"


# ─────────────────────────────────────────────
#  Page: Auth
# ─────────────────────────────────────────────

def _google_redirect_uri() -> str:
    """Return the OAuth redirect URI. Reads GOOGLE_REDIRECT_URI from env,
    falls back to the Streamlit app's own URL at /?google_callback=1."""
    uri = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
    if uri:
        return uri
    # Auto-detect from Streamlit's request headers when available
    try:
        ctx = st.context  # type: ignore[attr-defined]
        host = ctx.headers.get("host", "localhost:8501")
        scheme = "https" if "streamlit.app" in host else "http"
        return f"{scheme}://{host}/?google_callback=1"
    except Exception:
        return "http://localhost:8501/?google_callback=1"


def page_auth(db: Database):
    _navbar_auth()
    st.markdown("""
    <div style="height:80px"></div>
    <div style="text-align:center;margin-bottom:8px">
      <div style="display:inline-flex;align-items:center;gap:10px;background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.25);border-radius:40px;padding:6px 16px;font-size:0.8rem;color:#60a5fa;margin-bottom:20px">
        ✦ AI-Powered Document Intelligence
      </div>
    </div>
    <h1 style="text-align:center;font-size:2.4rem;font-weight:800;color:#e2e8f4;letter-spacing:-0.03em;margin-bottom:8px">
      Chat with your documents
    </h1>
    <p style="text-align:center;color:#7b8db0;font-size:1rem;margin-bottom:40px">
      Upload PDFs, DOCX, or TXT files and query them with AI using RAG
    </p>
    """, unsafe_allow_html=True)

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        # ── Google Sign-In button (shown only when client ID is configured) ──
        google_client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        if google_client_id:
            try:
                redirect_uri = _google_redirect_uri()
                google_url = get_google_auth_url(redirect_uri)
                st.markdown(
                    f"""
                    <a href="{google_url}" style="text-decoration:none">
                      <div style="display:flex;align-items:center;justify-content:center;gap:12px;
                                  background:#ffffff;color:#1f1f1f;border:1px solid #dadce0;
                                  border-radius:8px;padding:10px 16px;font-size:0.95rem;
                                  font-weight:500;cursor:pointer;margin-bottom:4px;
                                  transition:box-shadow .2s">
                        <svg width="20" height="20" viewBox="0 0 48 48">
                          <path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 3.2l6.7-6.7C35.8 2.5 30.2 0 24 0 14.6 0 6.6 5.4 2.6 13.3l7.8 6.1C12.3 13 17.7 9.5 24 9.5z"/>
                          <path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v8.5h12.4c-.5 2.8-2.1 5.2-4.5 6.8l7 5.4c4.1-3.8 6.5-9.4 6.5-16.2z"/>
                          <path fill="#FBBC05" d="M10.4 28.6A14.6 14.6 0 0 1 9.5 24c0-1.6.3-3.1.8-4.6l-7.8-6.1A23.9 23.9 0 0 0 0 24c0 3.8.9 7.4 2.6 10.6l7.8-6z"/>
                          <path fill="#34A853" d="M24 48c6.2 0 11.4-2 15.2-5.5l-7-5.4c-2 1.4-4.6 2.2-8.2 2.2-6.3 0-11.6-4.2-13.6-9.9l-7.8 6C6.5 42.6 14.6 48 24 48z"/>
                        </svg>
                        Continue with Google
                      </div>
                    </a>
                    """,
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.warning(f"Google auth unavailable: {e}")

            st.markdown(
                """
                <div style="display:flex;align-items:center;gap:10px;margin:16px 0">
                  <div style="flex:1;height:1px;background:rgba(255,255,255,.1)"></div>
                  <span style="color:#4a5568;font-size:0.8rem">or</span>
                  <div style="flex:1;height:1px;background:rgba(255,255,255,.1)"></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # ── Email / password tabs ──
        tab1, tab2 = st.tabs(["Sign In", "Create Account"])

        with tab1:
            email = st.text_input("Email address", key="login_email", placeholder="you@example.com")
            password = st.text_input("Password", type="password", key="login_password", placeholder="••••••••")
            if st.button("Sign In", type="primary", use_container_width=True, key="login_button"):
                if email and password:
                    ok, user, msg = auth_login(db=db, email=email, password=password)
                    if ok:
                        st.session_state.user_id = int(user["id"])
                        st.session_state.active_chat_id = _create_or_get_default_chat(db, st.session_state.user_id)
                        st.rerun()
                    else:
                        st.error(msg or "Invalid credentials.")
                else:
                    st.warning("Please enter your email and password.")

        with tab2:
            email = st.text_input("Email address", key="signup_email", placeholder="you@example.com")
            password = st.text_input("Password", type="password", key="signup_password", placeholder="Min 8 chars, 1 letter, 1 number")
            if st.button("Create Account", type="primary", use_container_width=True, key="signup_button"):
                if email and password:
                    ok, msg = auth_signup(db=db, email=email, password=password)
                    if ok:
                        st.success("Account created! Sign in to get started.")
                    else:
                        st.error(msg)
                else:
                    st.warning("Please fill in all fields.")

    st.markdown("""
    <div style="display:flex;justify-content:center;gap:40px;margin-top:48px">
      <div style="text-align:center">
        <div style="font-size:1.5rem;margin-bottom:6px">🔒</div>
        <div style="font-size:0.78rem;color:#7b8db0;font-weight:500">Secure &amp; Private</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:1.5rem;margin-bottom:6px">⚡</div>
        <div style="font-size:0.78rem;color:#7b8db0;font-weight:500">Fast Retrieval</div>
      </div>
      <div style="text-align:center">
        <div style="font-size:1.5rem;margin-bottom:6px">🤖</div>
        <div style="font-size:0.78rem;color:#7b8db0;font-weight:500">GPT-4o / Ollama</div>
      </div>
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  Page: Home (Dashboard)
# ─────────────────────────────────────────────

def page_home(db: Database, user: Dict, plan: str, user_id: int):
    stats = db.get_dashboard_stats(user_id=user_id)
    todays_queries = db.count_today_queries(user_id=user_id)
    todays_uploads = db.count_today_uploads(user_id=user_id)
    q_limit = FREE_QUERIES_PER_DAY if plan == "free" else "∞"
    u_limit = FREE_UPLOADS_PER_DAY if plan == "free" else "∞"

    _section_header("🏠", "Dashboard")

    # Stats
    st.markdown('<div class="stats-grid">', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _stat_card("Total Documents", str(stats["total_docs"]), "in your knowledge base")
    with c2:
        _stat_card("Queries Today", str(todays_queries), f"of {q_limit} used")
    with c3:
        _stat_card("Uploads Today", str(todays_uploads), f"of {u_limit} used")
    with c4:
        _stat_card("Plan", plan.upper(), "current tier")
    st.markdown('</div>', unsafe_allow_html=True)

    # Usage progress
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.85rem;font-weight:600;color:#e2e8f4;margin-bottom:12px">Daily Usage</div>', unsafe_allow_html=True)
    if plan == "free":
        _progress_bar("Queries", todays_queries, FREE_QUERIES_PER_DAY)
        st.markdown("<br>", unsafe_allow_html=True)
        _progress_bar("Uploads", todays_uploads, FREE_UPLOADS_PER_DAY)
    else:
        st.markdown('<p style="color:#34d399;font-size:0.85rem">✓ Unlimited queries and uploads on your paid plan.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Upgrade banner (free only)
    if plan == "free":
        st.markdown("""
        <div class="upgrade-banner">
          <div class="upgrade-text">
            <h3>Upgrade to Paid</h3>
            <p>Remove daily limits and unlock unlimited queries, uploads, and priority support.</p>
          </div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("⚡ Upgrade Now", type="primary", key="home_upgrade"):
            try:
                url = create_checkout_session(user_id=user_id)
                st.markdown(f'<a href="{url}" target="_blank" style="color:#60a5fa">Open Stripe Checkout →</a>', unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Checkout unavailable: {e}")

    # Quick actions
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.85rem;font-weight:600;color:#e2e8f4;margin-bottom:12px">Quick Start</div>', unsafe_allow_html=True)
    st.markdown("""
    <ol style="color:#7b8db0;font-size:0.85rem;line-height:2;margin:0;padding-left:20px">
      <li>Go to <b style="color:#e2e8f4">Upload</b> and add your PDF, DOCX, or TXT files</li>
      <li>Open <b style="color:#e2e8f4">Chat</b> and ask questions about your documents</li>
      <li>Browse past conversations in <b style="color:#e2e8f4">History</b></li>
    </ol>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ─────────────────────────────────────────────
#  Page: Upload
# ─────────────────────────────────────────────

def page_upload(db: Database, user: Dict, plan: str, user_id: int,
                user_upload_dir: str, persist_base_dir: str):
    _section_header("📤", "Upload Documents")

    todays_uploads = db.count_today_uploads(user_id=user_id)
    if plan == "free" and todays_uploads >= FREE_UPLOADS_PER_DAY:
        st.error(f"Daily upload limit ({FREE_UPLOADS_PER_DAY}) reached. Upgrade to continue.")
        st.stop()

    st.markdown(f'<p style="color:#7b8db0;font-size:0.85rem;margin-bottom:16px">Supported: PDF, DOCX, TXT · Today: {todays_uploads}/{FREE_UPLOADS_PER_DAY if plan=="free" else "∞"} uploads</p>', unsafe_allow_html=True)

    uploaded_files = st.file_uploader(
        "Drop files here or click to browse",
        type=["pdf", "docx", "txt"],
        accept_multiple_files=True,
        label_visibility="collapsed"
    )

    if uploaded_files:
        for f in uploaded_files:
            safe_name = _safe_filename(f.name)
            incoming_path = os.path.join(user_upload_dir, f"incoming_{int(time.time())}_{safe_name}")
            with open(incoming_path, "wb") as out:
                out.write(f.getbuffer())
            try:
                doc_hash = sha256_file(incoming_path)
                final_path = os.path.join(user_upload_dir, f"{doc_hash}__{safe_name}")
                if incoming_path != final_path:
                    os.replace(incoming_path, final_path)
                else:
                    final_path = incoming_path

                with st.spinner(f"Ingesting {f.name}…"):
                    result = ingest_document(
                        db=db, user_id=user_id, file_path=final_path,
                        persist_base_dir=persist_base_dir,
                        embeddings=None,
                        llm_provider=st.session_state.llm_provider,
                    )

                if result.get("status") == "cached":
                    st.info(f"Already indexed: {f.name}")
                else:
                    st.success(f"✓ Ingested {f.name} — {result.get('chunk_count')} chunks created")
            except Exception as e:
                st.error(f"Failed: {f.name} — {e}")

    st.divider()
    _section_header("📁", "Your Documents")

    docs = db.list_documents(user_id=user_id)
    if not docs:
        st.markdown('<div class="card" style="text-align:center;padding:36px"><p style="color:#4a5568;font-size:0.9rem">No documents yet. Upload your first file above.</p></div>', unsafe_allow_html=True)
        return

    for d in docs:
        doc_hash = d["doc_hash"]
        mime = d.get("file_mime") or ""
        icon = _doc_icon(mime)
        chunks = d.get("chunk_count") or 0
        created = d.get("created_at", "")[:10]

        st.markdown(f"""
        <div class="doc-card">
          <div class="doc-icon">{icon}</div>
          <div class="doc-info">
            <div class="doc-name">{d['file_name']}</div>
            <div class="doc-meta">{mime or "unknown type"} · {chunks} chunks · {created}</div>
            <div class="doc-hash">{doc_hash[:12]}…</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

        v_col, d_col, _ = st.columns([1, 1, 5])
        with v_col:
            if st.button("Preview", key=f"view_{doc_hash}", use_container_width=True):
                file_path = None
                for name in os.listdir(user_upload_dir):
                    if name.startswith(f"{doc_hash}__"):
                        file_path = os.path.join(user_upload_dir, name)
                        break
                if file_path and os.path.exists(file_path):
                    st.info(preview_document_text(file_path))
                else:
                    st.warning("File not found on disk.")
        with d_col:
            if st.button("Delete", key=f"del_{doc_hash}", use_container_width=True):
                try:
                    db.delete_document(user_id=user_id, doc_hash=doc_hash)
                    for name in os.listdir(user_upload_dir):
                        if name.startswith(f"{doc_hash}__"):
                            os.remove(os.path.join(user_upload_dir, name))
                    vectorstore_dir = os.path.join(persist_base_dir, str(user_id))
                    shutil.rmtree(vectorstore_dir, ignore_errors=True)
                    remaining_docs = db.list_documents(user_id=user_id)
                    if remaining_docs:
                        with st.spinner("Rebuilding vector index…"):
                            for rd in remaining_docs:
                                rd_hash = rd["doc_hash"]
                                fp = None
                                for name in os.listdir(user_upload_dir):
                                    if name.startswith(f"{rd_hash}__"):
                                        fp = os.path.join(user_upload_dir, name)
                                        break
                                if fp and os.path.exists(fp):
                                    ingest_document(
                                        db=db, user_id=user_id, file_path=fp,
                                        persist_base_dir=persist_base_dir,
                                        embeddings=None,
                                        llm_provider=st.session_state.llm_provider,
                                        force_reingest=True,
                                    )
                    st.success("Document deleted and index rebuilt.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")


# ─────────────────────────────────────────────
#  Page: Chat
# ─────────────────────────────────────────────

def page_chat(db: Database, user: Dict, plan: str, user_id: int, persist_base_dir: str):
    _section_header("💬", "Chat Interface")

    left, right = st.columns([1, 3])

    with left:
        st.markdown('<div class="card-sm">', unsafe_allow_html=True)
        sessions = db.list_chat_sessions(user_id=user_id, limit=50)
        chat_titles = {s["id"]: s["title"] for s in sessions}

        if st.session_state.active_chat_id is None and sessions:
            st.session_state.active_chat_id = sessions[0]["id"]

        active_id = st.session_state.active_chat_id
        if sessions:
            selected = st.selectbox(
                "Session",
                options=[s["id"] for s in sessions],
                format_func=lambda cid: chat_titles.get(cid, "Chat"),
                index=0,
                label_visibility="collapsed",
            )
            if selected is not None:
                st.session_state.active_chat_id = int(selected)

        if st.button("+ New Chat", use_container_width=True):
            title = f"Chat {len(sessions) + 1}"
            st.session_state.active_chat_id = db.create_chat_session(user_id=user_id, title=title)
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    with right:
        chat_id = st.session_state.active_chat_id
        if chat_id is None:
            st.markdown('<div class="card" style="text-align:center;padding:40px"><p style="color:#4a5568">Create a new chat to get started.</p></div>', unsafe_allow_html=True)
            return

        sessions = db.list_chat_sessions(user_id=user_id, limit=50)
        messages = db.get_chat_messages(chat_session_id=chat_id)
        chat_title = next((s["title"] for s in sessions if int(s["id"]) == int(chat_id)), "Chat")

        # Chat actions
        act_left, act_right = st.columns(2)
        with act_left:
            if messages:
                try:
                    pdf_bytes = export_chat_to_pdf_bytes(chat_title=chat_title, messages=messages)
                    st.download_button("⬇ Export PDF", data=pdf_bytes,
                                       file_name=f"{_safe_filename(chat_title)}.pdf",
                                       mime="application/pdf", use_container_width=True)
                except Exception:
                    pass
        with act_right:
            if st.button("✦ Summarize", use_container_width=True, key="summarize_btn"):
                openai_api_key = _get_env("OPENAI_API_KEY")
                try:
                    with st.spinner("Summarizing…"):
                        summary = summarize_chat(
                            messages=messages,
                            llm_provider=st.session_state.llm_provider,
                            openai_api_key=openai_api_key,
                        )
                    db.save_chat_message(chat_session_id=chat_id, role="assistant",
                                         content=summary, metadata={"type": "summary"})
                    st.success("Summary added.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Summarization failed: {e}")

        # Messages
        st.markdown('<div class="card" style="padding:16px">', unsafe_allow_html=True)
        if not messages:
            st.markdown('<p style="color:#4a5568;text-align:center;padding:24px 0;font-size:0.88rem">No messages yet. Ask your first question below.</p>', unsafe_allow_html=True)
        else:
            for m in messages:
                role = m["role"]
                content = m["content"]
                is_user = role == "user"
                avatar_cls = "user" if is_user else "ai"
                bubble_cls = "user" if is_user else "ai"
                avatar_char = "U" if is_user else "AI"

                meta_html = ""
                if not is_user and m.get("metadata"):
                    md = m["metadata"] or {}
                    srcs = md.get("sources", [])
                    sent = md.get("sentiment", {})
                    if srcs:
                        meta_html += f'<div class="msg-sources">📎 {", ".join(srcs[:4])}</div>'
                    if isinstance(sent, dict) and sent.get("label"):
                        meta_html += f'<div class="msg-sentiment">Sentiment: {sent["label"]}</div>'

                st.markdown(f"""
                <div class="msg-row {'user' if is_user else ''}">
                  <div class="msg-avatar {avatar_cls}">{avatar_char}</div>
                  <div class="msg-bubble {bubble_cls}">{content}{meta_html}</div>
                </div>
                """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Input
        prompt_key = f"prompt_text_{chat_id}"
        clear_key = f"{prompt_key}__clear"
        if st.session_state.get(clear_key):
            st.session_state[prompt_key] = ""
            st.session_state[clear_key] = False
        if prompt_key not in st.session_state:
            st.session_state[prompt_key] = ""

        # Voice input (optional)
        if VOICE_AVAILABLE:
            openai_api_key = _get_env("OPENAI_API_KEY")
            with st.expander("🎙 Voice input", expanded=False):
                if not openai_api_key:
                    st.warning("Voice transcription requires OPENAI_API_KEY.")
                else:
                    webrtc_ctx = webrtc_streamer(
                        key=f"voice_{chat_id}",
                        mode=WebRtcMode.SENDRECV,
                        media_stream_constraints={"audio": True, "video": False},
                        audio_processor_factory=AudioBufferProcessor,
                    )
                    if st.button("Transcribe", key=f"transcribe_{chat_id}"):
                        try:
                            processor = getattr(webrtc_ctx, "audio_processor", None)
                            if not processor:
                                st.warning("No audio recorded yet.")
                            else:
                                wav_bytes = processor.to_wav_bytes(max_seconds=15)
                                transcript = transcribe_wav_bytes(wav_bytes, openai_api_key=openai_api_key).text
                                if transcript.strip():
                                    st.session_state[prompt_key] = transcript.strip()
                                    st.rerun()
                                else:
                                    st.warning("Could not transcribe.")
                        except Exception as e:
                            st.error(f"Voice error: {e}")

        prompt_text = st.text_area(
            "Ask a question",
            value=st.session_state.get(prompt_key, ""),
            key=prompt_key,
            height=90,
            placeholder="Type your question about your documents…",
            label_visibility="collapsed",
        )

        if st.button("Send →", type="primary", use_container_width=True, disabled=not (prompt_text or "").strip()):
            user_prompt = prompt_text.strip()
            st.session_state[clear_key] = True

            todays_queries = db.count_today_queries(user_id=user_id)
            if plan == "free" and todays_queries >= FREE_QUERIES_PER_DAY:
                st.error(f"Daily query limit ({FREE_QUERIES_PER_DAY}) reached. Upgrade to continue.")
                st.stop()

            db.save_chat_message(chat_session_id=chat_id, role="user", content=user_prompt)
            db.log_query(user_id=user_id, model=st.session_state.llm_provider)

            placeholder = st.empty()
            stop_event = threading.Event()
            thread = threading.Thread(target=_typing_animation, args=(placeholder, stop_event))
            thread.start()

            try:
                with st.spinner(""):
                    result = answer_with_rag(
                        db=db, user_id=user_id, query=user_prompt,
                        persist_base_dir=persist_base_dir,
                        embeddings=None,
                        llm_provider=st.session_state.llm_provider,
                        openai_api_key=_get_env("OPENAI_API_KEY"),
                        top_k=5,
                    )
                stop_event.set(); thread.join(timeout=1.0)
                placeholder.empty()

                meta = {"sources": result.get("sources", []), "sentiment": result.get("sentiment")}
                db.save_chat_message(chat_session_id=chat_id, role="assistant",
                                     content=result["answer"], metadata=meta)
                st.rerun()
            except Exception as e:
                stop_event.set(); thread.join(timeout=1.0)
                placeholder.empty()
                st.error(f"Error: {e}")


# ─────────────────────────────────────────────
#  Page: History
# ─────────────────────────────────────────────

def page_history(db: Database, user_id: int):
    _section_header("📋", "Chat History")

    query = st.text_input("Search chats", placeholder="Search by title or message…", label_visibility="collapsed")
    sessions = db.search_chat_sessions(user_id=user_id, query=query, limit=50) if query.strip() \
               else db.list_chat_sessions(user_id=user_id, limit=50)

    if not sessions:
        st.markdown('<div class="card" style="text-align:center;padding:36px"><p style="color:#4a5568">No history yet. Start a chat first.</p></div>', unsafe_allow_html=True)
        return

    for s in sessions:
        date_str = s.get("created_at", "")[:10]
        st.markdown(f"""
        <div class="hist-item">
          <div class="hist-title">💬 {s['title']}</div>
          <div class="hist-date">{date_str}</div>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Open", key=f"hist_{s['id']}", use_container_width=False):
            st.session_state.active_chat_id = s["id"]
            st.session_state.page = "Chat"
            st.rerun()


# ─────────────────────────────────────────────
#  Page: Settings
# ─────────────────────────────────────────────

def page_settings(db: Database, user: Dict, plan: str, user_id: int):
    _section_header("⚙️", "Settings")

    # Profile
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.85rem;font-weight:600;color:#e2e8f4;margin-bottom:14px">Account</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="settings-row">
      <div><div class="settings-label">Email</div></div>
      <div style="font-size:0.85rem;color:#60a5fa;font-family:var(--mono)">{user['email']}</div>
    </div>
    <div class="settings-row">
      <div><div class="settings-label">Plan</div></div>
      <span class="plan-badge {'paid' if plan=='paid' else ''}">{plan.upper()}</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # LLM provider
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.85rem;font-weight:600;color:#e2e8f4;margin-bottom:14px">AI Model</div>', unsafe_allow_html=True)
    st.session_state.llm_provider = st.selectbox(
        "Backend",
        options=["openai", "ollama"],
        index=0 if st.session_state.llm_provider == "openai" else 1,
        label_visibility="collapsed",
    )
    if st.session_state.llm_provider == "ollama":
        st.info("Ensure Ollama is running. Set `OLLAMA_BASE_URL` in `.env` if not using the default.")
    else:
        st.markdown('<p style="font-size:0.8rem;color:#7b8db0">Using GPT-4o-mini. Set <code>OPENAI_API_KEY</code> in your <code>.env</code> file.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Upgrade / billing
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div style="font-size:0.85rem;font-weight:600;color:#e2e8f4;margin-bottom:14px">Billing</div>', unsafe_allow_html=True)
    if plan == "free":
        st.markdown("""
        <p style="font-size:0.85rem;color:#7b8db0;margin-bottom:14px">
          Upgrade to unlock unlimited queries, uploads, and priority support.
        </p>
        """, unsafe_allow_html=True)
        if st.button("⚡ Upgrade to Paid", type="primary", key="settings_upgrade"):
            try:
                url = create_checkout_session(user_id=user_id)
                st.markdown(f'<a href="{url}" target="_blank" style="color:#60a5fa;font-size:0.9rem">Open Stripe Checkout →</a>', unsafe_allow_html=True)
            except Exception as e:
                st.error(f"Checkout unavailable: {e}")
    else:
        st.markdown('<p style="color:#34d399;font-size:0.85rem">✓ You are on the paid plan — unlimited access enabled.</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    st.divider()
    if st.button("Sign Out", key="logout_btn"):
        st.session_state.user_id = None
        st.session_state.active_chat_id = None
        st.session_state.page = "Home"
        st.rerun()


# ─────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────

def main():
    st.set_page_config(
        page_title=PROJECT_TITLE,
        page_icon="📄",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    _inject_css()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    db = Database(db_path=os.path.join(base_dir, "data", "app.db"))

    # Session state defaults
    defaults = {
        "user_id": None,
        "active_chat_id": None,
        "page": "Home",
        "llm_provider": _get_env("LLM_PROVIDER", "openai") or "openai",
        "embeddings_provider": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Handle Stripe redirect
    payment_status = st.query_params.get("payment")
    if payment_status == "success":
        session_id = st.query_params.get("session_id")
        if session_id:
            try:
                ok = handle_payment_success(db=db, session_id=session_id)
                if ok:
                    st.success("Payment successful. Plan upgraded!")
                    st.rerun()
            except Exception as e:
                st.warning(f"Payment verification: {e}")

    # ── Handle Google OAuth callback ──────────────────────────────────────
    google_code = st.query_params.get("code")
    is_google_callback = st.query_params.get("google_callback") == "1" or (
        google_code and st.query_params.get("scope", "")  # Google always sends scope
    )
    if google_code and is_google_callback and st.session_state.user_id is None:
        try:
            redirect_uri = _google_redirect_uri()
            google_user = exchange_google_code(code=google_code, redirect_uri=redirect_uri)
            ok, user, msg = google_auth_or_signup(db=db, google_user=google_user)
            if ok and user:
                st.session_state.user_id = int(user["id"])
                st.session_state.active_chat_id = _create_or_get_default_chat(db, st.session_state.user_id)
                # Clear OAuth params from URL so a refresh doesn't re-trigger
                st.query_params.clear()
                st.rerun()
            else:
                st.error(f"Google sign-in failed: {msg}")
        except Exception as e:
            st.error(f"Google sign-in error: {e}")

    # Not authenticated
    if st.session_state.user_id is None:
        page_auth(db)
        return

    # Resolve user
    user_id: int = int(st.session_state.user_id)
    user = db.get_user_by_id(user_id)
    if not user:
        st.session_state.user_id = None
        st.rerun()
        return
    plan = user.get("plan", "free")

    # Page routing via query params (navbar links) or session state
    qp_page = st.query_params.get("page", "")
    if qp_page in NAV_PAGES:
        st.session_state.page = qp_page

    current_page = st.session_state.get("page", "Home")

    # Navbar
    _navbar(email=user["email"], plan=plan, current_page=current_page)

    # Sidebar nav (hidden visually — use buttons for page switching)
    with st.sidebar:
        for p in NAV_PAGES:
            if st.button(p, key=f"nav_{p}"):
                st.session_state.page = p
                st.rerun()
        st.divider()
        if st.button("Sign Out", key="sidebar_logout"):
            st.session_state.user_id = None
            st.session_state.active_chat_id = None
            st.rerun()

    # Paths
    persist_base_dir = os.path.join(base_dir, "vectorstore")
    upload_base_dir = os.path.join(base_dir, "data", "uploads")
    user_upload_dir = os.path.join(upload_base_dir, str(user_id))
    os.makedirs(user_upload_dir, exist_ok=True)

    # Render page
    if current_page == "Home":
        page_home(db, user, plan, user_id)
    elif current_page == "Upload":
        page_upload(db, user, plan, user_id, user_upload_dir, persist_base_dir)
    elif current_page == "Chat":
        page_chat(db, user, plan, user_id, persist_base_dir)
    elif current_page == "History":
        page_history(db, user_id)
    elif current_page == "Settings":
        page_settings(db, user, plan, user_id)


if __name__ == "__main__":
    main()
