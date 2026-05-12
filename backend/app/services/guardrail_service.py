"""Input guardrails: block abusive language, medical/legal advice requests, etc."""
from __future__ import annotations

import re

# ── Abuse word list (normalised, extend as needed) ───────────────────────────
_ABUSE_WORDS: set[str] = {
    "fuck", "shit", "bastard", "asshole", "bitch", "damn", "crap",
    "idiot", "stupid", "moron", "retard", "dickhead", "motherfucker",
    "wtf", "stfu", "kys",
}

# ── Medical / legal pattern triggers ─────────────────────────────────────────
_MEDICAL_PATTERNS = [
    r"\b(diagnos|symptom|treatment|cure|medicine|prescription|overdos|surgery|cancer|seizure|stroke)\b",
    r"\b(should i take|can i take|is it safe to take)\b",
    r"\b(call (an )?ambulance|medical emergency|heart attack)\b",
]

_LEGAL_PATTERNS = [
    r"\b(legal advice|sue|lawsuit|attorney|court|negligence|liability|compensation claim)\b",
    r"\b(is it illegal|can (i|you) be (sued|arrested))\b",
]

_MEDICAL_RE = re.compile("|".join(_MEDICAL_PATTERNS), re.IGNORECASE)
_LEGAL_RE   = re.compile("|".join(_LEGAL_PATTERNS),   re.IGNORECASE)


# ── Polite refusal messages ───────────────────────────────────────────────────
_MSG_ABUSE = (
    "I am here to assist you with your product concerns. "
    "I kindly request that you maintain a respectful tone so I can help you effectively."
)
_MSG_MEDICAL = (
    "I appreciate you reaching out. However, I am only able to assist with product-related queries "
    "and am not in a position to provide medical guidance. "
    "For any health-related concerns, please consult a qualified medical professional."
)
_MSG_LEGAL = (
    "Thank you for your message. I specialise in product support and am not able to provide legal advice. "
    "For legal matters, please consult a qualified legal professional."
)


def check(text: str) -> tuple[bool, str]:
    """Return (is_blocked, response_message). blocked=False means text is safe."""
    normalised = text.lower()
    words = re.findall(r"\b\w+\b", normalised)

    if any(w in _ABUSE_WORDS for w in words):
        return True, _MSG_ABUSE

    if _MEDICAL_RE.search(normalised):
        return True, _MSG_MEDICAL

    if _LEGAL_RE.search(normalised):
        return True, _MSG_LEGAL

    return False, ""
