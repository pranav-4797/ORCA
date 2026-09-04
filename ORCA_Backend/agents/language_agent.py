"""
Language / Intent Agent

First node of the graph (PS component #1). Detects the language the user
wrote in -- with emphasis on Indian regional languages -- so every
downstream response can be delivered in the same language, and normalizes
the query for the Planning Agent.

The structured output is a forced tool call; on LLM unavailability it
falls back to a Unicode-script heuristic that still catches the major
Indic scripts without any model call.
"""

from __future__ import annotations

import time

import llm_client
from models import AgentTrace, DataSource

SUPPORTED_LANGUAGES = [
    "en", "hi", "mr", "ta", "te", "bn", "ml", "kn", "gu", "or",
    "kok", "tcy",
    "kfr", "byr", "mvv", "ncr", "adm",
]

# Script-range heuristic fallback: first significant codepoint per script.
_SCRIPT_RANGES = [
    ("bn", (0x0980, 0x09FF)),  # Bengali (also covers Assamese)
    ("gu", (0x0A80, 0x0AFF)),
    ("or", (0x0B00, 0x0B7F)),
    ("ta", (0x0B80, 0x0BFF)),
    ("te", (0x0C00, 0x0C7F)),
    ("kn", (0x0C80, 0x0CFF)),
    ("ml", (0x0D00, 0x0D7F)),
    ("hi", (0x0900, 0x097F)),  # Devanagari -> default Hindi (mr, kok checked via LLM)
    ("tcy", (0x0C80, 0x0CFF)),  # Tulu (uses Kannada script range)
]


def _detect_by_script(text: str) -> str:
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        for code, (lo, hi) in _SCRIPT_RANGES:
            if lo <= cp <= hi:
                counts[code] = counts.get(code, 0) + 1
                break
    lang = max(counts, key=counts.get) if counts else "en"
    # Devanagari is shared by Hindi, Marathi and Konkani — disambiguate with vocabulary
    if lang == "hi":
        low = text.lower()
        # Marathi distinctive Devanagari words (not in Hindi)
        mr_markers = ["मध्ये", "आहे", "काय", "साठी", "आणि", "होते", "होता", "निर्णय"]
        kok_markers = ["आसा", "कितें", "कोसेम"]
        if any(m in low for m in kok_markers):
            return "kok"
        if any(m in low for m in mr_markers):
            return "mr"
        # If contains Marathi city name in Devanagari but no Hindi markers, keep hi as fallback
    return lang


class LanguageAgent:
    name = "LanguageAgent"

    def run(self, raw_query: str) -> tuple[dict, AgentTrace]:
        """Returns {"language": code, "normalized_query": text} + trace."""
        start = time.perf_counter()

        # Pre-detect romanized coastal language for ASCII queries (matters for
        # both the fast-path and for correcting an LLM mis-classification that
        # returns "en" for romanized Hindi/Marathi etc.).
        roman_hint: str | None = None
        if raw_query.isascii():
            try:
                from orchestrator.state import _detect_romanized_language
                roman_hint = _detect_romanized_language(raw_query)
            except Exception:
                roman_hint = None

        # Latency fast path: pure-ASCII English queries can skip the LLM.
        # Romanized Indic is also ASCII but must NOT be fast-pathed as English.
        if raw_query.isascii() and roman_hint is None:
            result = {
                "language": "en",
                "normalized_query": raw_query.strip(),
                "mode": "fast-path",
            }
            duration_ms = (time.perf_counter() - start) * 1000
            trace = AgentTrace(
                agent_name=self.name,
                action="Detected language 'en' [mode=fast-path, ASCII heuristic]",
                result_summary=(
                    f"Normalized query ready for planning "
                    f"({len(result['normalized_query'])} chars); LLM call skipped."
                ),
                data_sources=[],
                duration_ms=duration_ms,
            )
            return result, trace

        # Romanized detected + LLM unavailable -> answer directly in that language
        if roman_hint and not llm_client.is_available():
            result = {
                "language": roman_hint,
                "normalized_query": raw_query.strip(),
                "mode": "rules-romanized",
            }
            duration_ms = (time.perf_counter() - start) * 1000
            trace = AgentTrace(
                agent_name=self.name,
                action=f"Detected language '{roman_hint}' [mode=rules-romanized, romanized heuristic]",
                result_summary=(
                    f"Romanized {roman_hint} detected ({len(result['normalized_query'])} chars); LLM unavailable — using heuristic."
                ),
                data_sources=[],
                duration_ms=duration_ms,
            )
            return result, trace
        # Otherwise (non-ASCII native script, or romanized with LLM available) fall through to LLM

        try:
            args = llm_client.complete_structured(
                system_prompt=(
                    "You are the Language/Intent Agent of ORCA, a marine-safety "
                    "assistant for Indian coastal users. Detect the language of the "
                    "user's query and normalize it to English for internal "
                    "processing WITHOUT changing its meaning. Supported languages: "
                    f"{', '.join(SUPPORTED_LANGUAGES)}.\n\n"
                    "IMPORTANT: Below are distinctive markers and examples for "
                    "each non-standard language. Use these to disambiguate.\n\n"
                    "  - kfr: Kutchi, spoken in Kutch region of Gujarat. Distinctive "
                    "markers: words like 'chhe' (is), 'mane' (I/me), 'khoij' (where), "
                    "'kem' (how), 'bhani' (will come). Phonetically: retroflex 'r', "
                    "words often end in vowel '-o' or '-i'. SAMPLE: \"chhe mane "
                    "khoij?\" (where am I going?). NOT Hindi: Hindi uses \"क्या\", "
                    "\"मैं\", \"कहाँ\", \"कैसे\". NOT English: Kutchi uses native "
                    "Indic script words like 'chhe', 'mane', 'khoij'.\n"
                    "  - byr: Beary, spoken by Muslim community in coastal Karnataka. "
                    "Distinctive markers: words like 'nannu' (I), 'evvarike' (who), "
                    "'ente' (my), 'bare' (come), 'hogtay' (going). Phonetically: "
                    "soft 'b', 'g' sounds; Malayalam-influenced verb endings like "
                    "'-tay', '-en'. SAMPLE: \"nannu ente bare hogtay?\" (am I coming?). "
                    "NOT Kannada: Kannada uses 'nanenu', 'yavudu', 'nanna'. Beary "
                    "uses Malayalam-influenced forms like 'nannu', 'ente'.\n"
                    "  - mvv: Malvani, dialect of Konkani/Marathi spoken in Konkan "
                    "coastal Maharashtra/Goa. Distinctive markers: words like "
                    "'khella' (play), 'zali' (sit), 'poytay' (gone), 'bando' (stop), "
                    "'mi' (I/me). Phonetically: nasalized vowels, soft consonant "
                    "clusters. SAMPLE: \"mi khella zali poytay?\" (I went to play?). "
                    "NOT Hindi: Hindi uses 'मैं', 'खेल', 'बैठा', 'गया'. Malvani "
                    "uses native Marathi/Konkani forms like 'mi', 'khella', 'zali'.\n"
                    "  - ncr: Nicobarese, spoken in the Nicobar Islands (umbrella code "
                    "for multiple dialects).\n"
                    "  - adm: Andamanese, spoken in the Andaman Islands (umbrella code "
                    "for the language family).\n\n"
                    "Few-shot examples — match these patterns precisely:\n"
                    "  Example 1: \"chhe mane khoij?\" → kfr (Kutchi)\n"
                    "  Example 2: \"nannu ente bare hogtay\" → byr (Beary)\n"
                    "  Example 3: \"mi khella zali poytay\" → mvv (Malvani)\n"
                    "If the query mixes languages, pick the dominant one."
                ),
                user_prompt=f'USER QUERY: "{raw_query}"',
                tool_name="detect_language",
                tool_description=(
                    "Detect the query's language and produce an English-normalized "
                    "copy of the same question."
                ),
                schema={
                    "type": "object",
                    "properties": {
                        "language": {
                            "type": "string",
                            "enum": SUPPORTED_LANGUAGES,
                            "description": "BCP-47-ish code of the detected language.",
                        },
                        "normalized_query": {
                            "type": "string",
                            "description": (
                                "The user's question translated/normalized into "
                                "English, preserving location and time references."
                            ),
                        },
                    },
                    "required": ["language", "normalized_query"],
                },
                temperature=0.0,
            )
            result = {
                "language": str(args.get("language", "en")),
                "normalized_query": str(args.get("normalized_query", raw_query)).strip(),
                "mode": "llm",
            }
            # Romanized heuristic correction: LLM occasionally returns "en"
            # for romanized Hindi/Marathi/Gujarati etc. that our keyword table
            # catches reliably. Prefer the heuristic when LLM says English but
            # roman hint is a strong coastal language.
            if result["language"] == "en" and roman_hint and roman_hint != "en":
                result["language"] = roman_hint
                result["mode"] = "llm+romanized-fix"
        except llm_client.LLMUnavailableError:
            # Script fallback already catches native scripts; also honour romanized
            if roman_hint:
                result = {
                    "language": roman_hint,
                    "normalized_query": raw_query,
                    "mode": "rules-romanized",
                }
            else:
                result = {
                    "language": _detect_by_script(raw_query),
                    "normalized_query": raw_query,
                    "mode": "rules",
                }

        duration_ms = (time.perf_counter() - start) * 1000
        trace = AgentTrace(
            agent_name=self.name,
            action=(
                f"Detected language '{result['language']}' [mode={result['mode']}]"
            ),
            result_summary=(
                f"Normalized query ready for planning ({len(result['normalized_query'])} chars)."
            ),
            data_sources=[],
            duration_ms=duration_ms,
        )
        return result, trace


# Re-exported for orchestrator convenience.
SOURCES_NONE: list[DataSource] = []
