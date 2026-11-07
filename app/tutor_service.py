import os
import logging
import json
import uuid
from dotenv import load_dotenv
from groq import Groq
from app.rag_service import query_knowledge_base
import time
from app.language_validator import LanguageValidator

# Load environment variables from the .env file
load_dotenv()

logger = logging.getLogger(__name__)

class TutorService:
    def __init__(self, llm_client=None):
        # Fetch the API key from environment variables (.env)
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.warning(" GROQ_API_KEY not found in environment variables or .env file.")
      
        self.client = Groq(api_key=api_key) if api_key else None
        self.model_name = "openai/gpt-oss-20b" # Ensure this Groq model supports JSON mode 

    def generate_response(self, student_message: str, learner_id: str = "default_learner", session_id: str = None, preferred_language: str = "auto") -> dict:
        """
        Orchestrates bilingual RAG retrieval, extracts morphological error flags, 
        logs learner state, and returns the Explicit Contract schema.
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        validation = LanguageValidator.validate_and_enforce(student_message, enforce_swahili=False)
        
        if not validation["is_valid"]:
            error_msg = validation["error"]
            fallback_errors = [{"error": "Unsupported language detected", "rule_id": "LANG-001"}]
            self._emit_session_log(session_id, learner_id, fallback_errors)
            
            return {
                "reply_text": error_msg,
                "reply_audio": None,
                "error_flags": fallback_errors
            }

        if not self.client:
            return {
                "reply_text": "Samahani, ufunguo wa Groq API haupatikani kwenye mfumo.",
                "reply_audio": None,
                "error_flags": []
            }

        # Retrieve the top 2 precise micro-chunks 
        retrieved_docs = query_knowledge_base(student_message, k=2)
        
        #  STRICT KB GUARDRAIL
        if not retrieved_docs or len(retrieved_docs) == 0:
            fallback_errors = [{"error": "Out of domain query", "rule_id": "KB-NULL"}]
            self._emit_session_log(session_id, learner_id, fallback_errors)
            
            return {
                "reply_text": "Samahani, sikupata taarifa hii kwenye nyaraka za mtaala. Tafadhali uliza swali linalohusu mtaala. / I couldn't find this information in the curriculum documents.",
                "reply_audio": None,
                "error_flags": fallback_errors
            }
        
        # Format context with explicit Rule IDs 
        context_text = "\n\n".join([
            f"Rule ID: {doc.get('metadata', {}).get('rule_id', 'NO_RULE_ID')} | Content: {doc['content']}" 
            for doc in retrieved_docs
        ])
        
      
       #  Core JSON prompt
        system_prompt = f"""You are Mwalimu Msaidizi, an expert bilingual CBC Curriculum AI Tutor.
Your job has TWO distinct parts:
1. EDUCATE: Answer the student's actual question in detail using ONLY the information in the 'Curriculum Context'.
2. CORRECT GRAMMAR: Analyze the student's input text for grammatical or morphological errors based ONLY on the provided Rule IDs.

Curriculum Context (Grammar Rule KB):
{context_text}

Student Message: {student_message}

You MUST output ONLY a valid JSON object matching exactly this schema. 
CRITICAL RULES:
- No writing in bold
- DO NOT wrap the output in markdown code blocks (```json).
- DO NOT include any conversational preamble.
- Start your response immediately with the opening bracket {{.
- NEVER bold the entire paragraph.

{{
  "reply_text": "Provide ONLY the full educational answer using normal, unbolded text. DO NOT write any footnotes or grammar notes here.",
  "error_flags": [
    {{"error": "Describe grammatical error here if any, otherwise leave array empty", "rule_id": "the explicit Rule ID"}}
  ]
}}"""

        # Generate response via Groq API enforcing JSON output
        try:
            chat_completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": system_prompt}],
                temperature=0.1, 
                response_format={"type": "json_object"}
            )
            llm_output = json.loads(chat_completion.choices[0].message.content)
            reply_text = llm_output.get("reply_text", "Error parsing response.")
            error_flags = llm_output.get("error_flags", [])
            # Extract VALID rule IDs from the documents retrieved
            valid_rule_ids = {
                doc.get('metadata', {}).get('rule_id') 
                for doc in retrieved_docs 
                if doc.get('metadata', {}).get('rule_id')
            }
            
            # Filter the LLM's flags to only include real rules that exist in the context
            validated_error_flags = [
                flag for flag in error_flags 
                if flag.get("rule_id") in valid_rule_ids
            ]
            
            # Replace the raw LLM output with our validated list
            error_flags = validated_error_flags

        except Exception as e:
            logger.error(f"Groq API call failed: {e}")
            reply_text = f"Samahani, kumesitawi tatizo la kiufundi: {str(e)}"
            error_flags = []

        # EMIT SESSION LOG FOR TEACHER ASSIST 
        self._emit_session_log(session_id, learner_id, error_flags)

        # Return the exact Explicit Contract schema
        return {
            "reply_text": reply_text,
            "reply_audio": None, 
            "error_flags": error_flags,
            "retrieved_context_used": retrieved_docs
        }

    def _emit_session_log(self, session_id: str, learner_id: str, errors: list):
        """
        Helper method to log the minimum viable data schema for the Learner Profile Store.
        """
        session_log = {
            "session_id": session_id,
            "learner_id": learner_id,
            "errors": errors,
            "difficulty_level": "intermediate", # Hardcoded for now; can be calculated dynamically
            "synced": False
        }
        # This log will be ingested by your backend monitoring or database for the Teacher Assist dashboard
        logger.info(f"LEARNER_SESSION_EVENT: {json.dumps(session_log)}")

    def generate_response_stream(self, student_message: str, preferred_language: str = "auto"):
        """
        Streams the Groq API response. Note: Streaming pure JSON chunks requires a specialized 
        frontend parser. This streams the text portion conceptually.
        """
        if not self.client:
            yield "Samahani, ufunguo wa Groq API haupatikani kwenye faili la .env."
            return

        retrieved_docs = query_knowledge_base(student_message, k=2)
        
        if not retrieved_docs or len(retrieved_docs) == 0:
            yield "Samahani, sikupata taarifa hii kwenye nyaraka za mtaala."
            return

        context_text = "\n\n".join([doc["content"] for doc in retrieved_docs])
        
        system_prompt = f"""You are an encouraging and supportive bilingual educational tutor.
Answer using ONLY the provided curriculum context.

Curriculum Context:
{context_text}

Student Message: {student_message}
"""
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": system_prompt}],
                stream=True,
            )
            for chunk in stream:
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        except Exception as e:
            logger.error(f"Groq streaming failed: {e}")
            yield f"Samahani, kumesitawi tatizo la kiufundi: {str(e)}"

    def transcribe_audio(self, audio_file_path: str) -> str:
        """
        Transcribes recorded student audio using Groq's whisper-large-v3-turbo model.
        """
        if not self.client:
            return "Samahani, Groq client haipatikani."
            
        try:
            with open(audio_file_path, "rb") as file:
                transcription = self.client.audio.transcriptions.create(
                    file=(audio_file_path, file.read()),
                    model="whisper-large-v3-turbo",
                    language="sw",
                    prompt="Huu ni mfumo wa elimu wa Kenya. Maswali yanahusu ufahamu, ufupisho, hotuba, uandishi wa barua, insha, ripoti, fasihi simulizi, fasihi andishi na masomo ya Kiswahili na Kiingereza."
                )
            return transcription.text
        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            return f"Error in transcription: {str(e)}"