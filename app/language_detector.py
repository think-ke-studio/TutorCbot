import logging
from langdetect import detect, detect_langs, LangDetectException

logger = logging.getLogger(__name__)

class LanguageDetector:
    @staticmethod
    def detect_language(text: str) -> str:
        """
        Detects the primary language of the given text.
        Returns the ISO 639-1 language code (e.g., 'sw' or 'en').
        """
        if not text or len(text.strip()) < 3:
            return "unknown"
            
        try:
            # langdetect identifies Swahili as 'sw' and English as 'en'
            primary_lang = detect(text)
            return primary_lang
        except LangDetectException as e:
            logger.error(f"Language detection failed: {e}")
            return "unknown"