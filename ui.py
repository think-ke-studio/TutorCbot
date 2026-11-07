import os
import streamlit as st
import requests

# FastAPI Backend URL
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8042")
FASTAPI_TEXT_URL = f"{BACKEND_URL.rstrip('/')}/api/chat/message"
FASTAPI_VOICE_URL = f"{BACKEND_URL.rstrip('/')}/api/chat/voice"

st.set_page_config(
    page_title="Swahili & English Educational Tutor",
    page_icon="🎓",
    layout="centered"
)

# App Header
st.title("🎓 Mwalimu Msaidizi (AI Tutor)")
st.caption("Bilingual Swahili & English CBC Curriculum Assistant (Optimized for Edge)")

# Sidebar for Input Mode Selection
input_mode = st.sidebar.radio("Chagua Njia ya Kuwasiliana / Input Mode:", ["Andika Ujumbe (Text)", "🎤 Ongea na Sauti (Voice)"])

# Initialize Chat History in Streamlit Session State
if "messages" not in st.session_state:
    st.session_state.messages = []
if "recorder_key" not in st.session_state:
    st.session_state.recorder_key = 0

# Display prior chat messages on re-run
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if "audio" in message and message["audio"]:
            st.audio(message["audio"])
        
        # Display Error Flags if they exist in the history
        if "error_flags" in message and message["error_flags"]:
            for flag in message["error_flags"]:
                if flag.get("error") != "Out of domain query": # Ignore fallback flags in UI
                    st.error(f"**Grammar Note:** {flag.get('error')} (Rule: {flag.get('rule_id')})")

        if "context" in message and message["context"]:
            with st.expander("View Curriculum Grounding Source"):
                for idx, doc in enumerate(message["context"]):
                    st.markdown(f"**Source {idx+1}:** {doc['metadata'].get('topic_title')} ({doc['metadata'].get('source_file')})")
                    st.text(doc['content'][:300] + "...")

active_query = None
audio_bytes = None

# --- VOICE INPUT MODE (Main Panel) ---
if input_mode == "🎤 Ongea na Sauti (Voice)":
    st.markdown("---")
    st.subheader("🎙️ Voice Recording Studio")
    st.info("Bofya kitufe cha maikrofoni kuanza, kisha bofya kitufe cha mraba kusimamisha. (Click mic to start, square to stop).")
    
    # Native Streamlit Audio Input - Requires manual click to start and stop
    audio_value = st.audio_input(
        "Nasa Sauti (Record Voice Question)", 
        key=f"voice_recorder_{st.session_state.recorder_key}"
    )
    
    if audio_value is not None:
        audio_bytes = audio_value.getvalue()
        active_query = "[Voice Message Sent by Student]"

# --- TEXT INPUT MODE ---
else:
    active_query = st.chat_input("Uliza swali lako hapa / Type your question here...")

# Process Student Query (whether Text or Voice)
if active_query:
    
    # Append and display student message
    msg_payload = {"role": "user", "content": active_query}
    if audio_bytes:
        msg_payload["audio"] = audio_bytes
        
    st.session_state.messages.append(msg_payload)
    
    with st.chat_message("user"):
        if audio_bytes:
            st.markdown("🎙️ *[Voice Audio Prompt]*")
            st.audio(audio_bytes)
        else:
            st.markdown(active_query)

    # Query FastAPI Backend
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        retrieved_context = []
        error_flags = []

        try:
            if audio_bytes:
                message_placeholder.markdown("Transcribing audio with Groq Whisper & querying RAG tutor...")
                files = {"file": ("voice_query.wav", audio_bytes, "audio/wav")}
                response = requests.post(FASTAPI_VOICE_URL, files=files)
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        transcribed = data.get("transcribed_query", "")
                        base_reply = data.get("reply_text", "Samahani, hakuna jibu lililopatikana.")
                        
                        # --- FIX: Combine transcription and reply into one permanent string ---
                        full_response = f"**Ulichosema (Transcribed):** *{transcribed}*\n\n---\n\n{base_reply}"
                        
                        error_flags = data.get("error_flags", [])
                        retrieved_context = data.get("retrieved_context_used", [])
                        
                        message_placeholder.markdown(full_response)
                    else:
                        full_response = "Samahani, usindikaji wa sauti umeshindikana."
                        message_placeholder.markdown(full_response)
                else:
                    full_response = f"Server Error ({response.status_code})"
                    message_placeholder.markdown(full_response)
            else:
                # Updated payload schema to match the Explicit Contract
                payload = {
                    "learner_id": "test_student_1",
                    "text": active_query,
                    "lang": "auto"
                }
                # Fallback to legacy payload format if the backend hasn't updated its Pydantic model yet
                # payload = {"message": active_query} 
                
                response = requests.post(FASTAPI_TEXT_URL, json=payload)
                
                if response.status_code == 200:
                    data = response.json()
                    # Updated to handle the new explicit JSON contract
                    full_response = data.get("reply_text", data.get("tutor_response", "Samahani, hakuna jibu lililopatikana."))
                    error_flags = data.get("error_flags", [])
                    retrieved_context = data.get("retrieved_context_used", [])
                    message_placeholder.markdown(full_response)
                else:
                    full_response = f" Server Error ({response.status_code})"
                    message_placeholder.markdown(full_response)
                
        except requests.exceptions.RequestException as e:
            full_response = f" Connection Error: Is FastAPI running? Details: {e}"
            message_placeholder.markdown(full_response)

        # Display newly extracted error flags
        if error_flags:
            for flag in error_flags:
                if flag.get("error") != "Out of domain query":
                    st.error(f"**Grammar Note:** {flag.get('error')} (Rule: {flag.get('rule_id')})")

        # Save Assistant Response and Context to Session State
        st.session_state.messages.append({
            "role": "assistant", 
            "content": full_response,
            "context": retrieved_context,
            "error_flags": error_flags
        })
        
        # Display grounding sources if available
        if retrieved_context:
            with st.expander("View Curriculum Grounding Source"):
                for idx, doc in enumerate(retrieved_context):
                    st.markdown(f"**Source {idx+1}:** {doc['metadata'].get('topic_title')} ({doc['metadata'].get('source_file')})")
                    st.text(doc['content'][:300] + "...")

        if audio_bytes:
            st.session_state.recorder_key += 1
            st.rerun()

