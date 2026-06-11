from langchain_google_genai import ChatGoogleGenerativeAI
from app.core.config import get_settings

settings = get_settings()

def get_llm(streaming: bool = True) -> ChatGoogleGenerativeAI:
    """Initialize and return the Gemini Chat LLM."""
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        streaming=streaming,
    )
