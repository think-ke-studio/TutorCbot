from app.language_detector import LanguageDetector

class LanguageValidator:
    SUPPORTED_LANGUAGES = {"sw": "Kiswahili", "en": "English"}

    @staticmethod
    def validate_and_enforce(text: str, enforce_swahili: bool = False) -> dict:
        """
        Validates the text language. If enforce_swahili is True, it flags non-Swahili inputs.
        """
        lang_code = LanguageDetector.detect_language(text)
        
        is_supported = lang_code in LanguageValidator.SUPPORTED_LANGUAGES
        
        if enforce_swahili and lang_code != "sw":
            return {
                "is_valid": False,
                "detected_lang": lang_code,
                "error": "Tafadhali uliza swali lako kwa Kiswahili."
            }
            
        return {
            "is_valid": is_supported,
            "detected_lang": lang_code,
            "error": None if is_supported else "Language not supported"
        }