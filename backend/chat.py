"""LLM answer-generation layer for the SLT-MOBITEL AI Assistant.

Sends the RAG context, conversation history, and user question to Gemini
via LangChain's ChatGoogleGenerativeAI interface.
Configured for Gemini 3.5 Flash Lite with low latency, connection pooling,
reasoning controls, multi-turn message structuring, and candidate model fallback.
"""

from __future__ import annotations

import logging
from typing import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from config import Settings
from prompt import SYSTEM_PROMPT, VOICE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)

_FALLBACK = (
    "I'm sorry, I could not retrieve a verified answer at this moment. "
    "Please call SLT-MOBITEL customer care on 1212 for immediate assistance."
)

_MAX_RETRIES = 2

# Models to attempt in order if the primary model hits a 429 quota exhaustion or rate limit
_CANDIDATE_FALLBACK_MODELS = (
    "gemini-3.5-flash",
)

# Process-level cache for ChatGoogleGenerativeAI instances to pool connections and avoid per-request setup
_llm_cache: dict[tuple, ChatGoogleGenerativeAI] = {}


def _is_quota_or_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is caused by a 429 quota exhaustion or rate limit."""
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return (
        "resourceexhausted" in name
        or "429" in msg
        or "quota" in msg
        or "rate limit" in msg
        or "ratelimit" in name
    )


def _parse_history_to_messages(history: str) -> list[BaseMessage]:
    """Parse a conversation history string into HumanMessage and AIMessage objects."""
    if not history or not history.strip():
        return []

    messages: list[BaseMessage] = []
    lines = history.strip().splitlines()
    current_role: str | None = None
    current_content: list[str] = []

    for line in lines:
        stripped = line.strip()
        lower_line = stripped.lower()

        if lower_line.startswith(("user:", "human:", "customer:")):
            if current_role and current_content:
                text = "\n".join(current_content).strip()
                if text:
                    messages.append(HumanMessage(content=text) if current_role == "user" else AIMessage(content=text))
            current_role = "user"
            current_content = [stripped.split(":", 1)[1].strip()]
        elif lower_line.startswith(("assistant:", "ai:", "model:", "agent:")):
            if current_role and current_content:
                text = "\n".join(current_content).strip()
                if text:
                    messages.append(HumanMessage(content=text) if current_role == "user" else AIMessage(content=text))
            current_role = "assistant"
            current_content = [stripped.split(":", 1)[1].strip()]
        else:
            if current_role is not None:
                current_content.append(line)
            else:
                current_role = "user"
                current_content.append(line)

    if current_role and current_content:
        text = "\n".join(current_content).strip()
        if text:
            messages.append(HumanMessage(content=text) if current_role == "user" else AIMessage(content=text))

    return messages


def _build_messages(context: str, history: str, message: str, channel: str = "text") -> list[BaseMessage]:
    """Return a structured chat message list for LangChain and Gemini 3.5.

    Places the verified knowledge and grounding rules in the SystemMessage,
    followed by multi-turn conversation history turns as proper HumanMessage /
    AIMessage objects, and concludes with the customer's current question.
    """
    template = VOICE_SYSTEM_PROMPT if channel == "voice" else SYSTEM_PROMPT
    system_text = template.format(context=context)

    messages: list[BaseMessage] = [SystemMessage(content=system_text)]

    if history:
        history_turns = _parse_history_to_messages(history)
        if history_turns:
            messages.extend(history_turns)
        else:
            # Fallback if history had unusual unstructured formatting
            messages.append(HumanMessage(content=f"Previous conversation notes:\n{history}"))

    messages.append(HumanMessage(content=message))
    return messages


def _extract_text(content) -> str:
    """Safely extract a string from various content shapes Gemini can return."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                parts.append(part.get("text", ""))
            elif isinstance(part, str):
                parts.append(part)
            else:
                parts.append(str(part))
        return "".join(parts).strip()
    return str(content).strip()


def _get_llm_client(
    model_name: str,
    temperature: float,
    api_key: str,
    top_p: float = 0.95,
    max_output_tokens: int | None = 1024,
    thinking_level: str | None = "low",
    timeout: float = 30.0,
) -> ChatGoogleGenerativeAI:
    """Retrieve or create a cached ChatGoogleGenerativeAI instance for connection reuse."""
    cache_key = (model_name, temperature, top_p, max_output_tokens, thinking_level, api_key, timeout)
    cached = _llm_cache.get(cache_key)
    if cached is not None:
        return cached

    model_kwargs: dict[str, str] = {}
    if thinking_level and ("3." in model_name or "3-" in model_name or "3" in model_name):
        model_kwargs["thinking_level"] = thinking_level

    llm = ChatGoogleGenerativeAI(
        model=model_name,
        temperature=temperature,
        top_p=top_p,
        google_api_key=api_key,
        max_output_tokens=max_output_tokens,
        max_retries=1,
        timeout=timeout,
        model_kwargs=model_kwargs if model_kwargs else None,
    )

    if len(_llm_cache) >= 16:
        _llm_cache.pop(next(iter(_llm_cache)))
    _llm_cache[cache_key] = llm
    return llm


def generate_answer(settings: Settings, context: str, history: str, message: str, channel: str = "text") -> str:
    """Invoke Gemini and return the grounded answer text.

    Uses Gemini 3.5 Flash Lite with connection pooling, multi-turn history structuring,
    and automatic fallback to candidate models if quota or rate limits occur.
    """
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not configured")

    messages = _build_messages(context, history, message, channel=channel)

    # Voice channel prefers slightly lower temperature and concise tokens
    default_temp = getattr(settings, "gemini_temperature", 0.2)
    temperature = 0.2 if channel == "voice" else default_temp
    top_p = getattr(settings, "gemini_top_p", 0.95)
    max_tokens = getattr(settings, "gemini_max_output_tokens", 1024)
    thinking_level = getattr(settings, "gemini_thinking_level", "low")
    timeout = getattr(settings, "gemini_request_timeout", 30.0)

    # Build ordered list of candidate models without duplicates
    models_to_try: list[str] = [settings.gemini_model]
    for fallback_model in _CANDIDATE_FALLBACK_MODELS:
        if fallback_model not in models_to_try:
            models_to_try.append(fallback_model)

    last_error: Exception | None = None

    for model_name in models_to_try:
        try:
            llm = _get_llm_client(
                model_name=model_name,
                temperature=temperature,
                api_key=settings.google_api_key,
                top_p=top_p,
                max_output_tokens=max_tokens,
                thinking_level=thinking_level,
                timeout=timeout,
            )

            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    response = llm.invoke(messages)
                    text = _extract_text(response.content)
                    if text:
                        return text

                    logger.warning(
                        "Gemini model '%s' returned an empty response on attempt %d/%d.",
                        model_name,
                        attempt,
                        _MAX_RETRIES,
                    )
                except Exception as exc:
                    last_error = exc
                    if _is_quota_or_rate_limit_error(exc):
                        logger.warning(
                            "Gemini model '%s' quota exceeded or rate-limited (%s). Switching to fallback model...",
                            model_name,
                            exc,
                        )
                        break  # Break out of attempts loop to try the next candidate model

                    err_str = str(exc)
                    if "model output" in err_str or "output text" in err_str:
                        logger.warning(
                            "Gemini model '%s' output error on attempt %d/%d: %s",
                            model_name,
                            attempt,
                            _MAX_RETRIES,
                            exc,
                        )
                    elif "invalid argument" in err_str.lower() and "thinking" in err_str.lower():
                        # If a fallback model does not support thinking_level, retry without model_kwargs
                        logger.warning(
                            "Gemini model '%s' rejected thinking parameter (%s). Retrying without model_kwargs...",
                            model_name,
                            exc,
                        )
                        fallback_llm = ChatGoogleGenerativeAI(
                            model=model_name,
                            temperature=temperature,
                            google_api_key=settings.google_api_key,
                            max_retries=1,
                            timeout=timeout,
                        )
                        fallback_response = fallback_llm.invoke(messages)
                        fallback_text = _extract_text(fallback_response.content)
                        if fallback_text:
                            return fallback_text
                    else:
                        raise

        except Exception as exc:
            last_error = exc
            if _is_quota_or_rate_limit_error(exc):
                logger.warning(
                    "Gemini model '%s' quota exhausted (%s). Trying next available model...",
                    model_name,
                    exc,
                )
                continue
            raise

    # If all models hit quota or failed
    if last_error and _is_quota_or_rate_limit_error(last_error):
        logger.error(
            "All Gemini candidate models exceeded quota or rate limits. Returning customer helpline fallback answer: %s",
            last_error,
        )
        return _FALLBACK

    logger.error(
        "Gemini returned no usable output after trying models %s. Returning fallback.",
        models_to_try,
    )
    return _FALLBACK
