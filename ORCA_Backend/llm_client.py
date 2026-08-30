"""
LLM client wrapper for ORCA.

Single place where every agent's LLM calls go through. Uses an
OpenAI-compatible chat API (default: Groq's free tier, model
llama-3.3-70b-versatile) so the provider can be swapped via env vars
without touching any agent code.

Configuration (loaded from .env if present):
    GROQ_API_KEY   -- required for LLM calls (free key: console.groq.com)
    LLM_BASE_URL   -- optional, defaults to Groq's OpenAI-compatible endpoint
    LLM_MODEL      -- optional, defaults to llama-3.3-70b-versatile

Design guarantees:
    - Structured calls use FORCED tool calling (tool_choice pinned to the
      one tool), so the model must return arguments matching the JSON
      schema -- no string parsing of free-form output.
    - Every call retries exactly once on failure (API error or unparseable
      response).
    - If no API key is configured, `LLMUnavailableError` is raised so
      callers can fall back to their deterministic path gracefully.
"""

from __future__ import annotations

import io
import json
import os
import time
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "").strip()
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1").strip()
# NOTE: llama-3.3-70b-versatile was decommissioned by Groq -- calls 404 and every
# agent silently degrades to its deterministic template. Default now matches
# .env.example. Override with LLM_MODEL in .env.
LLM_MODEL: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b").strip()
# Hosted speech-to-text on the same Groq account (no extra key needed).
STT_MODEL: str = os.getenv("STT_MODEL", "whisper-large-v3-turbo").strip()
# Timeouts & token budgets — tuned for latency (env-overridable)
LLM_TIMEOUT_S: float = float(os.getenv("LLM_TIMEOUT_S", "12").strip() or 12)
LLM_TIMEOUT_FAST_S: float = float(os.getenv("LLM_TIMEOUT_FAST_S", "7").strip() or 7)
LLM_MAX_TOKENS_ROUTING: int = int(os.getenv("LLM_MAX_TOKENS_ROUTING", "400").strip() or 400)
LLM_MAX_TOKENS_RESPONSE: int = int(os.getenv("LLM_MAX_TOKENS_RESPONSE", "350").strip() or 350)

_client: Optional[OpenAI] = None


class LLMUnavailableError(Exception):
    """Raised when no API key is configured or the call failed after retry."""


def is_available() -> bool:
    """True when an API key is configured and LLM calls can be attempted."""
    return bool(GROQ_API_KEY)


def _get_client(timeout: float | None = None) -> OpenAI:
    global _client
    if not GROQ_API_KEY:
        raise LLMUnavailableError(
            "GROQ_API_KEY is not set. Get a free key at https://console.groq.com/keys "
            "and put it in your .env file (see .env.example)."
        )
    # Re-create client if requested timeout differs (cheap vs default)
    # Keep simple: use provided timeout if given, else default; cache per timeout bucket
    effective = timeout if timeout is not None else LLM_TIMEOUT_S
    if _client is None or getattr(_client, "_orca_timeout", None) != effective:
        _client = OpenAI(api_key=GROQ_API_KEY, base_url=LLM_BASE_URL, timeout=effective)
        _client._orca_timeout = effective  # type: ignore
    return _client


def _call_with_retry(fn, *, attempts: int = 2, delay_s: float = 0.8):
    """Retry-once wrapper: on failure wait briefly and try once more."""
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except LLMUnavailableError:
            raise  # never retry a missing-key error
        except Exception as exc:  # network, rate limit, parse errors, ...
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay_s)
    raise LLMUnavailableError(f"LLM call failed after {attempts} attempt(s): {last_error}")


def complete(system_prompt: str, user_prompt: str, *, temperature: float = 0.3,
             max_tokens: int = 400, timeout: float | None = None,
             attempts: int = 2) -> str:
    """Free-form text completion with retry-once. Use attempts=1 + low timeout for fast fallback."""
    client = _get_client(timeout=timeout)

    def _do() -> str:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        choice = response.choices[0]
        if choice.finish_reason == "length":
            # Reasoning models can silently burn budget on hidden thinking
            # tokens; a truncated answer is a failed answer -- retry once.
            raise ValueError("completion truncated (hit max_tokens)")
        content = choice.message.content
        if not content or not content.strip():
            raise ValueError("empty completion")
        return content.strip()

    return _call_with_retry(_do, attempts=attempts)


def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "speech.webm",
    mime_type: str = "audio/webm",
) -> str:
    """Speech-to-text via Groq's hosted Whisper (same key, same base URL).

    Used by POST /query/voice so fishermen can ask by speaking. Raises
    LLMUnavailableError when no key is configured or the call fails.
    """
    client = _get_client()

    def _do() -> str:
        bio = io.BytesIO(audio_bytes)
        bio.name = filename or f"speech{'' if '.' in (filename or '') else '.webm'}"
        result = client.audio.transcriptions.create(
            model=STT_MODEL,
            file=bio,
        )
        text = (getattr(result, "text", "") or "").strip()
        if not text:
            raise ValueError("empty transcription")
        return text

    return _call_with_retry(_do)


def complete_structured(    system_prompt: str,
    user_prompt: str,
    *,
    tool_name: str,
    tool_description: str,
    schema: dict[str, Any],
    temperature: float = 0.1,
    max_tokens: int = 700,
    timeout: float | None = None,
    attempts: int = 2,
) -> dict[str, Any]:
    """Forced-tool-call completion that returns schema-shaped arguments.

    The model is forced to call `tool_name`; its arguments are parsed as
    JSON and returned as a dict. Retries once on API or parse failure.
    For fast routing use max_tokens=300-400, timeout=7, attempts=1 so fallback is instant.
    """
    client = _get_client(timeout=timeout)

    def _do() -> dict[str, Any]:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            tools=[{
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_description,
                    "parameters": schema,
                },
            }],
            tool_choice={"type": "function", "function": {"name": tool_name}},
            temperature=temperature,
            max_tokens=max_tokens,
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            raise ValueError("model did not return a tool call")
        raw_args = tool_calls[0].function.arguments
        args = json.loads(raw_args)
        if not isinstance(args, dict):
            raise ValueError("tool arguments were not a JSON object")
        return args

    return _call_with_retry(_do, attempts=attempts)
