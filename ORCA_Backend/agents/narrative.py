"""
Narrative composer — the anti-template answer writer.

Every ORCA answer used to be assembled from the SAME markdown scaffolding:
a "### <emoji> VERDICT" heading, a "### Marine Conditions — <place>" heading,
a "| Parameter | Value |" table and a closing summary line. Different questions
produced structurally identical replies, which reads as machine-filled boiler-
plate rather than an advisory written by an expert.

This module replaces that scaffolding with ONE LLM pass that writes the whole
answer as flowing prose: numbers woven into sentences, the "why it matters"
explained, and a clear operational call. Structural variation is enforced two
ways — a rotating style directive (different opening hook / layout each call)
and a warmer temperature — so two answers never look alike.

Hard guarantees preserved from the template path:
  * NO fabrication — only the live fields the caller passes are exposed, and
    the result is rejected if it fails to quote any of them.
  * Safety floor — UNSAFE/EXTREME/CRITICAL must open with a do-not-go sentence.
  * Full localization — the whole narrative is written in the user's language.
  * Never fatal — returns None on any failure so the caller keeps its
    deterministic template answer.
"""

from __future__ import annotations

import logging
import os
import random
import re

import llm_client

_log = logging.getLogger("orca.narrative")

_LANGUAGE_NAMES = {
    "en": "English", "hi": "Hindi", "mr": "Marathi", "ta": "Tamil",
    "te": "Telugu", "bn": "Bengali", "ml": "Malayalam", "kn": "Kannada",
    "gu": "Gujarati", "or": "Odia", "pa": "Punjabi",
    "kok": "Konkani", "tcy": "Tulu", "kfr": "Kutchi", "byr": "Beary",
    "mvv": "Malvani", "ncr": "Nicobarese", "adm": "Andamanese",
}

_DANGER_VERDICTS = ("UNSAFE", "EXTREME", "CRITICAL")


def is_enabled() -> bool:
    """Narrative mode is on by default; ORCA_NARRATIVE=0 restores templates."""
    return os.getenv("ORCA_NARRATIVE", "1").strip().lower() not in ("0", "false", "no", "off")


# Canonical "is the user asking about FISHING?" vocabulary — native scripts plus
# common romanizations, so "can I fish here", "यहाँ मछली पकड़ सकता हूँ" and
# "machli pakadna safe hai" all resolve alike. Shared by the orchestrator's
# planner flag and the Response Agent so both paths agree.
FISHING_KEYWORDS = (
    "fish", "fishing",
    "मछली", "machli", "machhli", "macchli", "matsya",          # hi
    "मासे", "मासेमारी", "maasa", "maase", "maasemari",          # mr
    "மீன்", "meen", "meenpidi",                                 # ta
    "చేప", "chepa", "chepala",                                  # te
    "മീൻ", "മത്സ്യ",                                            # ml
    "ಮೀನು", "meenu",                                            # kn
    "માછલી", "માછીમારી",                                        # gu
    "মাছ", "machh", "mach",                                     # bn
)


def is_fishing_query(*texts: str) -> bool:
    """True when any supplied text mentions fishing in any supported language."""
    blob = " ".join(t or "" for t in texts).lower()
    return any(k in blob for k in FISHING_KEYWORDS)


# The anti-fabrication contract. Shared verbatim by every prose writer in this
# module (full answers and dashboard briefings) so honesty rules can never
# drift apart between the two.
_HARD_RULES = (
    "HARD RULES:\n"
    "- Use ONLY the live fields supplied below. NEVER invent or estimate a "
    "number, place, distance, catch report or forecast that is not given, and "
    "never restate a figure with a different value.\n"
    "- Quote every figure EXACTLY as supplied — do not round it, truncate it, "
    "drop a decimal or convert its unit. 28.49 km/h is '28.49 km/h', never "
    "'28 km/h' or '~28.5 km/h'. You may describe a bearing in words in addition "
    "to the exact degrees, but the degrees themselves stay unchanged.\n"
    "- If a field is absent, simply do not mention it. Do not say data is "
    "missing unless nothing at all was supplied.\n"
    "- If the safety verdict is UNSAFE, EXTREME or CRITICAL, your FIRST "
    "sentence must plainly tell them not to venture out.\n"
    "- Write the ENTIRE answer in the requested language, including the "
    "insight and the recommendation. Keep only proper nouns (INCOIS, SAMUDRA, "
    "OceanSat-2, place names) and unit symbols as they are.\n"
)


_SYSTEM_PROMPT = (
    "You are an expert marine advisory specialist and oceanographer writing for "
    "Indian coastal fishers and small-vessel skippers. You turn raw INCOIS live "
    "data — sea-surface temperature, wind and gusts, swell, surface current, "
    "chlorophyll, tides, potential-fishing-zone geometry and hazard verdicts — "
    "into a natural, fluid, actionable advisory.\n"
    "\n"
    "CRITICAL INSTRUCTION: You must strictly avoid a fixed, predictable "
    "template. No identical header blocks, no markdown tables, no "
    "'Parameter | Value' lists, no 'Verdict:' scaffolding, no bullet "
    "configurations, and no recycled opening phrase. Two answers to two "
    "different questions must not be structurally alike.\n"
    "\n"
    "Editorial rules:\n"
    "1. NARRATIVE FLUIDITY — write flowing, conversational yet authoritative "
    "prose. Vary sentence structure, the opening hook and the layout on every "
    "answer.\n"
    "2. NATURAL DATA INTEGRATION — weave the figures into your sentences with "
    "their units intact: 'with the sea holding near 28.3 °C' rather than "
    "'SST: 28.3°C'; 'a fishing ground sitting 21.7 km out on a 340° bearing' "
    "rather than 'Distance: 21.7 km'.\n"
    "3. VALUE-DRIVEN INSIGHT — say WHY the numbers matter. A cooling SST edge "
    "marks a thermal front where pelagics such as mackerel, sardine and tuna "
    "aggregate; a 28 km/h wind means a wet, slamming ride in an open boat; a "
    "1.2 m swell is workable but tiring over a long haul; a strong surface "
    "current means longer drift and harder net recovery.\n"
    "4. CONCISE ACTIONABILITY — one or two short paragraphs, readable on a "
    "phone. Answer the question that was actually asked first, then give the "
    "operational call (go, go with care, or stay in) and the one thing to keep "
    "watching. Keep coordinates, distance and bearing verbatim when supplied — "
    "that is what a skipper steers by.\n"
    "\n"
    + _HARD_RULES
    + "- Plain prose only: no headings, no tables, no bullet lists, no bold or "
    "italic markers, no emoji. One or two paragraphs, blank line between them."
)

# Rotating structural directives — the single biggest lever against the answers
# looking alike. One is picked at random per call and injected into the prompt.
_STYLE_VARIANTS = (
    "Open with the operational call inside the first six words, then justify it "
    "with the figures in one continuous paragraph.",
    "Open with a vivid one-sentence picture of what the sea is doing right now, "
    "then a short second paragraph carrying the recommendation.",
    "Lead with the single most decision-relevant figure woven into a sentence, "
    "build through what it implies, and land the recommendation last.",
    "Answer as a direct reply to the fisher, second person, conversational, in "
    "one tight paragraph with no preamble at all.",
    "Start with what stands out about this particular spot compared with an "
    "ordinary day, then give the practical call.",
    "Begin with the geometry — how far out and in what direction the fishing "
    "ground lies — then layer the sea conditions on top and close with the call.",
    "Frame it as a short briefing a skipper hears over the radio: situation "
    "first, then consequence, then instruction.",
)

_LENGTH_HINTS = (
    "Keep it under 70 words.",
    "Keep it under 100 words.",
    "Keep it to roughly 110 words across two short paragraphs.",
)

_INTENT_FOCUS = {
    "ocean_state": "The user asked about conditions — explain what the sea and "
                   "wind actually mean for working out of a small boat.",
    "safety_check": "The user asked whether it is safe — commit to a clear "
                    "answer and name the factor that decides it.",
    "hazard_alerts": "The user asked about warnings — lead with any active "
                     "bulletin and what it means for them today.",
    "pfz_lookup": "The user asked where the fish are — the ground's distance, "
                  "direction and why that water is productive carry the answer.",
    "geofence_check": "The user asked about boundaries — be exact about IMBL/MPA "
                      "proximity and what crossing it would mean.",
    "route_plan": "The user asked how to get somewhere — distance, what is "
                  "avoided, and the leg that needs attention.",
    "trend_analysis": "The user asked what changed over time — describe the "
                      "trend from the statistics given and the likely reason.",
    "zone_scan": "The user asked which areas are worth working — rank them and "
                 "say plainly which to avoid.",
}

_FISHING_FOCUS = (
    "THIS IS A FISHING-SUITABILITY QUESTION ('can I go fishing here?'). Weigh "
    "EVERYTHING together in your answer: how close the nearest potential fishing "
    "zone is (distance and direction) AND the wind/gusts, sea-surface "
    "temperature, swell and current. Recommend going only when the spot is "
    "reasonably close to a fishing zone AND the conditions are workable; "
    "otherwise advise care or staying in, and say which factor decided it. If no "
    "fishing zone was supplied, say so honestly instead of inventing one."
)


def _fmt_block(label: str, d: dict | None) -> str:
    if not d:
        return ""
    items = [f"{k}={v}" for k, v in d.items() if v is not None and str(v) != ""]
    return f"- {label}: " + "; ".join(items) if items else ""


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

# Words that make "do not go out" unmistakable, across the supported languages.
# Used to verify the model actually honoured a danger verdict.
_DANGER_WORDS = (
    "not", "avoid", "don't", "do not", "stay", "unsafe", "danger",
    "नहीं", "मत", "न ", "टाळ", "नका", "வேண்டாம்", "கூடாது",
    "వద్దు", "వెళ్లవద్దు", "അരുത്", "പോകരുത്", "ಬೇಡಿ", "ન ", "না",
    "যাবেন না",
)


def _honours_danger(text: str) -> bool:
    low = (text or "").lower()
    return any(w in low for w in _DANGER_WORDS)


def _numbers_in(d: dict | None) -> list[str]:
    """Every numeric token the caller exposed, as written."""
    out: list[str] = []
    for v in (d or {}).values():
        out.extend(_NUM_RE.findall(str(v)))
    return out


def _strip_markup(text: str) -> str:
    """Remove any scaffolding the model slipped in despite the prompt."""
    lines: list[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if not s:
            lines.append("")
            continue
        if s.startswith("|") or set(s) <= set("|-: "):
            continue  # table row / separator
        s = re.sub(r"^#{1,6}\s*", "", s)          # headings
        s = re.sub(r"^[-*•]\s+", "", s)           # bullets
        s = re.sub(r"^\d+[.)]\s+", "", s)         # numbered list
        s = s.replace("**", "").replace("__", "")
        lines.append(s)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out


def compose_narrative(
    user_query: str,
    intent: str,
    language: str = "en",
    verdict: str | None = None,
    ocean: dict | None = None,
    pfz: dict | None = None,
    hazard: dict | None = None,
    geospatial: dict | None = None,
    trend: dict | None = None,
    fishing_context: bool = False,
    timeout: float | None = None,
) -> str | None:
    """Write the whole answer as varied, AI-authored prose.

    Returns None when the LLM is unavailable, when the model failed to quote any
    of the live figures (anti-hallucination / anti-generic guard), or when a
    danger verdict was not honoured — the caller then keeps its deterministic
    template so an answer is always produced.
    """
    if not is_enabled() or not llm_client.is_available():
        return None

    blocks = [
        _fmt_block("Live ocean state", ocean),
        _fmt_block("Nearest potential fishing zone (PFZ)", pfz),
        _fmt_block("Hazard / safety assessment", hazard),
        _fmt_block("Boundaries / route", geospatial),
        _fmt_block("Long-term trend", trend),
    ]
    data_block = "\n".join(b for b in blocks if b)
    if not data_block:
        return None  # nothing live to narrate — let the template handle it

    lang_name = _LANGUAGE_NAMES.get((language or "en").lower(), "English")
    verdict_txt = str(verdict or "").upper()
    focus = _INTENT_FOCUS.get(intent, "")
    if fishing_context:
        focus = _FISHING_FOCUS
    style = random.choice(_STYLE_VARIANTS)
    length = random.choice(_LENGTH_HINTS)

    danger_note = ""
    if verdict_txt in _DANGER_VERDICTS:
        danger_note = (
            f"\nSAFETY OVERRIDE: the assessed verdict is {verdict_txt}. Your first "
            "sentence must tell them clearly not to venture out."
        )

    user_prompt = (
        f'THE FISHER ASKED: "{user_query}"\n'
        f"PRIMARY INTENT: {intent}\n"
        f"SAFETY VERDICT: {verdict_txt or 'not assessed'}\n"
        f"WRITE IN: {lang_name}\n"
        f"\nLIVE DATA AVAILABLE (use only these):\n{data_block}\n"
        f"\nFOCUS: {focus}\n"
        f"STRUCTURE FOR THIS ANSWER: {style} {length}"
        f"{danger_note}\n"
        "\nWrite the advisory now — prose only, no headings, no tables, no lists."
    )

    to = timeout if timeout is not None else float(
        os.getenv("ORCA_NARRATIVE_TIMEOUT_S", "8").strip() or 8
    )
    max_tok = int(os.getenv("ORCA_NARRATIVE_MAX_TOKENS", "1100").strip() or 1100)
    temp = float(os.getenv("ORCA_NARRATIVE_TEMPERATURE", "0.85").strip() or 0.85)
    try:
        raw = llm_client.complete(
            _SYSTEM_PROMPT, user_prompt,
            temperature=temp, max_tokens=max_tok, timeout=to, attempts=1,
        )
    except llm_client.LLMUnavailableError:
        return None
    except Exception as exc:  # narrative must never break a response
        _log.warning("compose_narrative failed (%s); caller keeps template", exc)
        return None

    text = _strip_markup(raw or "")
    if len(text) < 40:
        return None

    # Anti-generic guard: the answer must actually quote at least one live figure
    # we supplied, otherwise it is filler and the deterministic table is better.
    live_nums = _numbers_in(ocean) + _numbers_in(pfz)
    if live_nums and not any(n in text for n in live_nums):
        _log.info("narrative dropped — quoted none of the live figures")
        return None

    # Safety guard: a danger verdict must be unmistakable in the text.
    if verdict_txt in _DANGER_VERDICTS and not _honours_danger(text):
        _log.info("narrative dropped — danger verdict not honoured")
        return None

    return text


# ---------------------------------------------------------------------------
# "Before You Sail" dashboard briefing
# ---------------------------------------------------------------------------
# The dashboard needs three short pieces of localized prose: the briefing, one
# sentence explaining why the top card is on top, and one sentence explaining
# the readiness score. They are produced in a SINGLE forced-tool-call so the
# whole proactive dashboard costs exactly one LLM call, and they reuse the
# _HARD_RULES contract above so a briefing can never invent a figure either.

_BRIEFING_SYSTEM_PROMPT = (
    "You are ORCA's pre-departure briefing writer for Indian coastal fishers "
    "and small-vessel skippers. You are NOT answering a question — nobody "
    "asked anything. You are the first thing the fisher sees when they open "
    "the app, so you tell them what today's live INCOIS data means for going "
    "out, before they have to ask.\n"
    "\n"
    "Write like an experienced skipper briefing a friend on the jetty: "
    "concrete, calm, practical. Lead with the decision (go, go carefully, or "
    "stay in), support it with the figures that decide it, and close with the "
    "one thing to watch. No greetings, no 'here is your briefing', no "
    "restating the location name back at them.\n"
    "\n"
    + _HARD_RULES
    + "- Plain prose only: no headings, no bullet lists, no bold markers, no "
    "emoji.\n"
    "\n"
    "OUTPUT FORMAT — exactly three lines, each starting with its tag, nothing "
    "before or after:\n"
    "BRIEFING: <one paragraph of 40 to 80 words, no line breaks>\n"
    "WHY: <one sentence on why the top-ranked card matters most right now, "
    "using its figures>\n"
    "READINESS: <one short sentence naming the factor that most affected the "
    "readiness score; never repeat the numeric score>\n"
    "Write the text after every tag in the requested language. Keep the three "
    "tags themselves in English exactly as shown."
)

_BRIEFING_TAGS = ("BRIEFING", "WHY", "READINESS")


def _parse_tagged(raw: str) -> dict:
    """Split the three tagged lines out of the briefing completion.

    Tolerant by design: a tag the model dropped simply comes back empty, and
    the caller decides whether what survived is usable.
    """
    out = {tag: "" for tag in _BRIEFING_TAGS}
    current = None
    for line in (raw or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        matched = False
        for tag in _BRIEFING_TAGS:
            match = re.match(rf"^\**{tag}\**\s*[:：]\s*(.*)$", stripped, re.IGNORECASE)
            if match:
                current, matched = tag, True
                out[tag] = match.group(1).strip()
                break
        if not matched and current:
            out[current] = (out[current] + " " + stripped).strip()
    return out


def _card_block(cards: list | None) -> str:
    """Compact 'what the dashboard is showing' block for the prompt."""
    if not cards:
        return ""
    lines = []
    for card in cards[:6]:
        bits = [f"{card.get('type', '?')}"]
        if card.get("value") is not None:
            bits.append(f"{card['value']}{(' ' + card['unit']) if card.get('unit') else ''}")
        for entry in (card.get("why") or [])[:3]:
            bits.append(f"{entry.get('key')}={entry.get('value')}")
        lines.append("  * " + "; ".join(str(b) for b in bits))
    return "- Cards on the dashboard, highest priority first:\n" + "\n".join(lines)


def compose_briefing(
    *,
    language: str = "en",
    location_name: str = "",
    verdict: str | None = None,
    ocean: dict | None = None,
    pfz: dict | None = None,
    hazard: dict | None = None,
    cards: list | None = None,
    readiness: dict | None = None,
    local_hour: int | None = None,
    memory_note: str = "",
    timeout: float | None = None,
) -> dict | None:
    """One LLM call producing the dashboard's three localized prose pieces.

    Returns None when the LLM is unavailable, when the model quoted none of the
    live figures, or when a danger verdict was not honoured — the dashboard
    then renders its cards with no briefing rather than a fabricated one.
    """
    if not is_enabled() or not llm_client.is_available():
        return None
    if not (ocean or pfz or hazard or cards):
        return None            # nothing live to brief on -- say nothing

    lang_name = _LANGUAGE_NAMES.get((language or "en").lower(), "English")
    verdict_txt = str(verdict or "").upper()

    top_card = (cards or [{}])[0].get("type", "") if cards else ""
    factor_lines = ""
    if readiness and readiness.get("factors"):
        factor_lines = "; ".join(
            f"{f.get('factor')} {f.get('contribution')}/{f.get('max')} ({f.get('detail')})"
            for f in readiness["factors"]
        )

    blocks = [
        f"- Location: {location_name}" if location_name else "",
        f"- Local hour now: {local_hour:02d}:00" if local_hour is not None else "",
        _fmt_block("Live ocean state", ocean),
        _fmt_block("Nearest potential fishing zone (PFZ)", pfz),
        _fmt_block("Hazard / safety assessment", hazard),
        _card_block(cards),
        f"- Top-ranked card: {top_card}" if top_card else "",
        f"- Readiness factors: {factor_lines}" if factor_lines else "",
        f"- Known about this fisher: {memory_note}" if memory_note else "",
    ]
    live_block = "\n".join(b for b in blocks if b)

    danger_note = ""
    if verdict_txt in _DANGER_VERDICTS:
        danger_note = (
            f"\nSAFETY OVERRIDE: the assessed verdict is {verdict_txt}. The "
            "briefing's first sentence must plainly tell them not to go out."
        )

    user_prompt = (
        f"Write today's pre-departure briefing in {lang_name}.\n"
        f"{danger_note}\n\n"
        f"LIVE DATA AVAILABLE RIGHT NOW:\n{live_block}\n"
    )

    to = timeout if timeout is not None else float(
        os.getenv("ORCA_BRIEFING_TIMEOUT", "12").strip() or 12)
    try:
        raw = llm_client.complete(
            _BRIEFING_SYSTEM_PROMPT, user_prompt,
            temperature=0.7, max_tokens=700, timeout=to, attempts=1,
        )
    except llm_client.LLMUnavailableError:
        return None
    except Exception as exc:            # the dashboard must still render
        _log.warning("compose_briefing failed (%s); dashboard omits briefing", exc)
        return None

    parsed = _parse_tagged(raw)
    briefing = _strip_markup(parsed["BRIEFING"]).replace("\n", " ").strip()
    why = _strip_markup(parsed["WHY"]).replace("\n", " ").strip()
    note = _strip_markup(parsed["READINESS"]).replace("\n", " ").strip()
    if len(briefing) < 40:
        return None

    # Anti-generic guard: the briefing must quote a figure we actually supplied.
    live_nums = _numbers_in(ocean) + _numbers_in(pfz)
    if live_nums and not any(n in briefing for n in live_nums):
        _log.info("briefing dropped — quoted none of the live figures")
        return None

    if verdict_txt in _DANGER_VERDICTS and not _honours_danger(briefing):
        _log.info("briefing dropped — danger verdict not honoured")
        return None

    return {"briefing": briefing, "why_top_card": why, "readiness_note": note}
