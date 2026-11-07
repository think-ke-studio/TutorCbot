from fastapi import FastAPI, HTTPException, Request,UploadFile, File
from contextlib import asynccontextmanager
from app.config import settings
from app.database import init_db
import app.models
from app.session import router as session_router
import os
from pydantic import BaseModel
import traceback
import shutil
from app.evaluation_service import ExerciseEvaluator
from app.rag_service import query_knowledge_base 
from app.tutor_service import TutorService
from dotenv import load_dotenv
load_dotenv()
import wave
class EvaluationRequest(BaseModel):
    exercise_id: str
    student_answer: str
class ChatRequest(BaseModel):
    message: str

@asynccontextmanager
async def lifespan(app: FastAPI):
    print(" Starting Server: Warming up embedding model and ChromaDB...")
    try:
        query_knowledge_base("Warm up query", k=1)
        
        print(" Initializing Exercise Evaluator...")
        # This is the crucial line that makes the endpoint work
        # use fake evaluation data in the exercise.json file
        app.state.evaluator = ExerciseEvaluator(json_path="data/evaluations/exercises.json") 
        
        print(" Startup Complete: Knowledge base and Evaluator are online!")
    except Exception as e:
        print(f" CRITICAL WARM-UP ERROR: {str(e)}")
        # Print the full error traceback so we can see why it failed
        import traceback
        traceback.print_exc()
        app.state.evaluator = None
        
    yield
    
    # Free up memory when the server shuts down
    app.state.evaluator = None

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan
)

app.include_router(session_router, prefix="/session", tags=["Session"])

@app.get("/health")
async def health_check():
    return {"status": "online", "mode": "offline-edge-ready"}

tutor_service = TutorService()

from typing import Optional, List

# Define the exact schema the spec requires
class SessionMessageRequest(BaseModel):
    learner_id: str
    text: Optional[str] = None
    audio: Optional[str] = None
    lang: str = "sw"

# Update your endpoint to use the new schema
@app.post("/api/chat/message")
async def handle_student_chat(payload: SessionMessageRequest):
    """
    Main conversational tutor endpoint. Takes student text, 
    retrieves curriculum context, and prepares the scaffolded response.
    """
    try:
        # Pass the extracted text to your tutor service
        result = tutor_service.generate_response(
            student_message=payload.text, 
            learner_id=payload.learner_id, 
        )
        return result
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

tutor = TutorService()
@app.post("/api/chat/voice")
async def chat_with_voice(file: UploadFile = File(...)):
    """
    Receives voice recording bytes, validates size & WAV format,
    transcribes via Groq Whisper, queries the RAG tutor, 
    and returns the strict contract response.
    """
    temp_audio_path = f"temp_{file.filename or 'input.wav'}"
    
    try:
        # FILE SIZE LIMIT (Max 5MB)
        MAX_SIZE_BYTES = 5 * 1024 * 1024
        file_size = 0
        
        with open(temp_audio_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                file_size += len(chunk)
                if file_size > MAX_SIZE_BYTES:
                    # Clean up the partial file before crashing
                    os.remove(temp_audio_path)
                    raise HTTPException(status_code=413, detail="Audio file too large. Maximum size is 5MB.")
                buffer.write(chunk)
                
        # WAV FILE VALIDATION & SAMPLE RATE CHECK
        try:
            with wave.open(temp_audio_path, 'rb') as wav_file:
                # Check if it's a standard sample rate
                if wav_file.getframerate() not in [16000, 44100, 48000]:
                    print(f"Warning: Unusual sample rate detected ({wav_file.getframerate()}Hz). Groq API will attempt to auto-resample.")
        except wave.Error:
            # If wave.open fails, it means the file is corrupt or not a real audio file
            os.remove(temp_audio_path)
            return {"status": "error", "message": "Invalid or corrupted WAV file."}
            
        # TRANSCRIBE AUDIO
        transcribed_text = tutor.transcribe_audio(temp_audio_path)
        
        if not transcribed_text or "Error" in transcribed_text:
            return {"status": "error", "message": "Failed to transcribe audio."}
            
        # If the text is empty or Whisper hallucinates our hidden prompt due to silence
        if len(transcribed_text.strip()) < 2 or "Huu ni mfumo wa elimu" in transcribed_text:
            return {
                "status": "success",
                "transcribed_query": "[Sauti haikusikika / No speech detected]",
                "reply_text": "Samahani, sikusikia sauti yoyote. Tafadhali bonyeza maikrofoni na uongee tena.",
                "error_flags": [],
                "retrieved_context_used": []
            }
            
        # GET RAG RESPONSE
        response_data = tutor.generate_response(transcribed_text)
        
        return {
            "status": "success",
            "transcribed_query": transcribed_text,
            "reply_text": response_data.get("reply_text", "Samahani, hakuna jibu."),
            "error_flags": response_data.get("error_flags", []),
            "retrieved_context_used": response_data.get("retrieved_context_used", [])
        }
        
    finally:
        # Clean up temporary audio file
        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)

#  the evaluation endpoint
@app.post("/api/evaluate")
async def evaluate_student_answer(request: Request, payload: EvaluationRequest):
    # Retrieve the pre-loaded evaluator from the app state
    evaluator = request.app.state.evaluator
    
    if not evaluator:
        raise HTTPException(status_code=500, detail="Evaluator service is offline.")
        
    result = evaluator.evaluate_answer(payload.exercise_id, payload.student_answer)
    
    if result.get("status") == "error":
        raise HTTPException(status_code=404, detail=result.get("message"))
        
    return result

@app.post("/api/chat/retrieval")
async def retrieve_context(payload: ChatRequest):
    context = query_knowledge_base(payload.message, k=2)
    
    return {
        "query": payload.message, 
        "retrieved_context": context
    }


# run using uvicorn app.main:app --reload --port 8042