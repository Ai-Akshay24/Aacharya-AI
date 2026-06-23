"""
matcher.py — Aacharya AI Local Deterministic Matching Pipeline
================================================================
Fully self-contained. No database access, no network calls, no external
LLM dependency. Reads knowledge_base.json once at import time and resolves
free-text user input (English / Hindi / Kannada, native script or Roman
transliteration) into a structured intent the FastAPI layer can act on.

Pipeline:
    Stage 0 — Normalize    : unicode/whitespace/punctuation cleanup
    Stage 1 — Emergency    : hardcoded critical-veto regex scan (runs first,
                              always, independent of later stages)
    Stage 2 — Concept exact: canonical token dictionary lookup (all langs)
    Stage 3 — Fuzzy fallback: RapidFuzz typo-tolerance against canonical
                              tokens only (never against the full synonym
                              set, and NEVER for critical-tier concepts)
    Stage 4 — Intent resolve: concept(s) -> structured MatchResult consumed
                              by the API layer (auth.py)
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

KB_PATH = Path(__file__).parent / "knowledge_base.json"

SUPPORTED_LANGUAGES = ("en", "hi", "kn")

# Fuzzy match thresholds are language-specific because Roman-transliterated
# Kannada/Hindi input tends to have higher spelling variance than English.
FUZZY_THRESHOLDS = {
    "en": 88,
    "hi": 82,
    "kn": 78,
}
DEFAULT_FUZZY_THRESHOLD = 80

# Multi-word tokens score lower on pure ratio; this is the minimum length
# (in characters) below which we don't bother fuzzy-matching at all, to
# avoid single-letter / noise collisions.
MIN_FUZZY_TOKEN_LEN = 3


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------

@dataclass
class MatchResult:
    """Structured output of the pipeline, consumed by the API layer."""
    matched: bool
    intent: str  # "emergency" | "symptom" | "disease" | "vaccine" | "medicine" | "unmatched"
    concept_id: Optional[str] = None
    concept_type: Optional[str] = None
    severity_tier: Optional[str] = None
    response_text: Optional[str] = None
    audio_file: Optional[str] = None
    requires_location: bool = False
    suggested_medicines: list = field(default_factory=list)
    linked_concepts: list = field(default_factory=list)
    escalation_flag: bool = False
    escalation_action: Optional[str] = None
    match_stage: Optional[str] = None  # which stage produced the hit, for debugging/logs
    match_score: Optional[float] = None  # fuzzy score if Stage 3, else None
    language: str = "en"


# --------------------------------------------------------------------------
# Stage 0 — Normalization
# --------------------------------------------------------------------------

# Minimal, hand-maintained Romanized-Hindi/Kannada -> normalized-Roman token
# fixups. This is NOT a full transliteration engine — it only canonicalizes
# the most common spelling drifts seen in rural Hinglish/Kanglish input
# (e.g. "dardh" -> "dard", "nolu" -> "novu"). Extend this table as real
# user logs reveal new variants; do not try to make this "smart."
ROMAN_SPELLING_FIXUPS = {
    "dardh": "dard",
    "dardd": "dard",
    "nolu": "novu",
    "noolu": "novu",
    "shir": "sir",
    "maleria": "malaria",
    "dengu": "dengue",
}

_PUNCT_RE = re.compile(r"[^\w\s\u0900-\u097F\u0C80-\u0CFF]", re.UNICODE)
_MULTISPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """
    Stage 0: Unicode-normalize, lowercase, strip punctuation, collapse
    whitespace, and apply known Roman spelling fixups. Does not change
    script (Devanagari/Kannada text stays as-is; only Roman tokens are
    fixed up against the lookup table).
    """
    if not text:
        return ""

    # NFC normalization handles composed/decomposed Unicode variants
    # (important for Devanagari/Kannada matras typed via different IMEs).
    text = unicodedata.normalize("NFC", text)
    text = text.lower().strip()
    text = _PUNCT_RE.sub(" ", text)
    text = _MULTISPACE_RE.sub(" ", text).strip()

    # Apply word-level Roman spelling fixups only (skip native script tokens,
    # which won't match the Roman fixup keys anyway).
    words = text.split(" ")
    fixed_words = [ROMAN_SPELLING_FIXUPS.get(w, w) for w in words]
    return " ".join(fixed_words)


# --------------------------------------------------------------------------
# Knowledge base loading
# --------------------------------------------------------------------------

class KnowledgeBase:
    """Loads and indexes knowledge_base.json once. Read-only at runtime."""

    def __init__(self, kb_path: Path = KB_PATH):
        self.kb_path = kb_path
        self.concepts: list[dict] = []
        self.by_id: dict[str, dict] = {}

        # exact_index[lang][normalized_token] = concept_id
        self.exact_index: dict[str, dict[str, str]] = {lang: {} for lang in SUPPORTED_LANGUAGES}

        # fuzzy_pool[lang] = list of (normalized_token, concept_id) for
        # NON-critical concepts only. Critical/bypass concepts are excluded
        # so a typo can never accidentally soften an emergency match.
        self.fuzzy_pool: dict[str, list[tuple[str, str]]] = {lang: [] for lang in SUPPORTED_LANGUAGES}

        self._load()

    def _load(self) -> None:
        if not self.kb_path.exists():
            raise FileNotFoundError(f"knowledge_base.json not found at {self.kb_path}")

        with open(self.kb_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.concepts = data.get("concepts", [])

        for concept in self.concepts:
            cid = concept["concept_id"]
            self.by_id[cid] = concept

            tokens_by_lang = concept.get("canonical_tokens", {})
            bypass_fuzzy = concept.get("bypass_fuzzy_matching", False)

            for lang in SUPPORTED_LANGUAGES:
                for raw_token in tokens_by_lang.get(lang, []):
                    norm_token = normalize(raw_token)
                    if not norm_token:
                        continue

                    # Exact index: last-write-wins is fine here since the
                    # KB is hand-curated and collisions should be caught
                    # in content review, not at runtime.
                    self.exact_index[lang][norm_token] = cid

                    if not bypass_fuzzy and len(norm_token) >= MIN_FUZZY_TOKEN_LEN:
                        self.fuzzy_pool[lang].append((norm_token, cid))

    def get(self, concept_id: str) -> Optional[dict]:
        return self.by_id.get(concept_id)


# Singleton, loaded once at import time.
_kb = KnowledgeBase()


# --------------------------------------------------------------------------
# Stage 1 — Emergency / Critical Veto Layer
# --------------------------------------------------------------------------
# This stage is intentionally independent of the KB's fuzzy/exact indices.
# It runs first, always, regardless of confidence elsewhere in the pipeline.
# It is built directly off concepts flagged severity_tier == "critical",
# matched via exact substring containment only (no fuzzy tolerance) —
# critical-symptom recognition should never depend on an approximate score.

def _build_critical_lookup() -> dict[str, list[tuple[str, str]]]:
    """Returns {lang: [(normalized_token, concept_id), ...]} for critical concepts."""
    lookup: dict[str, list[tuple[str, str]]] = {lang: [] for lang in SUPPORTED_LANGUAGES}
    for concept in _kb.concepts:
        if concept.get("severity_tier") != "critical":
            continue
        cid = concept["concept_id"]
        for lang in SUPPORTED_LANGUAGES:
            for raw_token in concept.get("canonical_tokens", {}).get(lang, []):
                norm_token = normalize(raw_token)
                if norm_token:
                    lookup[lang].append((norm_token, cid))
    return lookup


_CRITICAL_LOOKUP = _build_critical_lookup()


def stage1_emergency_scan(normalized_text: str, language: str) -> Optional[str]:
    """
    Returns a concept_id if a critical/emergency token is found via exact
    substring containment, else None. Checks the declared language first,
    then falls back to scanning all languages — a panicked user may type
    in a script that doesn't match their selected UI language.
    """
    languages_to_check = [language] + [l for l in SUPPORTED_LANGUAGES if l != language]

    for lang in languages_to_check:
        for token, cid in _CRITICAL_LOOKUP.get(lang, []):
            if token in normalized_text:
                return cid
    return None


# --------------------------------------------------------------------------
# Stage 2 — Exact Concept Resolution
# --------------------------------------------------------------------------

def stage2_exact_match(normalized_text: str, language: str) -> Optional[str]:
    """
    Exact substring containment against the canonical token dictionary for
    the declared language. Returns the first matching concept_id, or None.
    Longest-token-first ordering avoids a short generic token ("para")
    shadowing a more specific multi-word match.
    """
    lang_index = _kb.exact_index.get(language, {})
    if not lang_index:
        return None

    # Check longer tokens first so multi-word phrases win over substrings.
    for token in sorted(lang_index.keys(), key=len, reverse=True):
        if token in normalized_text:
            return lang_index[token]
    return None


# --------------------------------------------------------------------------
# Stage 3 — Fuzzy Typo Fallback (RapidFuzz)
# --------------------------------------------------------------------------

def stage3_fuzzy_match(normalized_text: str, language: str) -> tuple[Optional[str], Optional[float]]:
    """
    Fuzzy fallback restricted to the canonical token list for the declared
    language (NOT the full synonym set, and NEVER critical-tier concepts —
    those are excluded from fuzzy_pool at load time).

    Matches per-word against the pool using token_sort_ratio, so word order
    drift doesn't tank the score. Returns (concept_id, score) or (None, None).
    """
    pool = _kb.fuzzy_pool.get(language, [])
    if not pool:
        return None, None

    threshold = FUZZY_THRESHOLDS.get(language, DEFAULT_FUZZY_THRESHOLD)
    pool_tokens = [t for t, _ in pool]

    best_cid = None
    best_score = 0.0

    # Try matching the whole normalized input first (handles short queries
    # like "sir dardh" cleanly), then fall back to per-word matching for
    # longer free-text sentences.
    candidates = [normalized_text] + [
        w for w in normalized_text.split(" ") if len(w) >= MIN_FUZZY_TOKEN_LEN
    ]

    for candidate in candidates:
        result = process.extractOne(
            candidate,
            pool_tokens,
            scorer=fuzz.token_sort_ratio,
        )
        if result is None:
            continue
        matched_token, score, idx = result
        if score >= threshold and score > best_score:
            best_score = score
            best_cid = pool[idx][1]

    if best_cid is None:
        return None, None
    return best_cid, best_score


# --------------------------------------------------------------------------
# Stage 4 — Intent Resolution
# --------------------------------------------------------------------------

def _concept_to_result(
    concept: dict,
    language: str,
    match_stage: str,
    match_score: Optional[float] = None,
) -> MatchResult:
    """Builds a MatchResult from a KB concept dict, with language fallback to English."""
    response_block = concept.get("response", {})
    lang_response = response_block.get(language) or response_block.get("en", {})

    concept_type = concept.get("type", "unknown")
    intent = "emergency" if concept_type == "emergency" else concept_type

    return MatchResult(
        matched=True,
        intent=intent,
        concept_id=concept["concept_id"],
        concept_type=concept_type,
        severity_tier=concept.get("severity_tier"),
        response_text=lang_response.get("text"),
        audio_file=lang_response.get("audio_file"),
        requires_location=concept.get("requires_location", False),
        suggested_medicines=concept.get("suggested_medicines", []),
        linked_concepts=concept.get("linked_concepts", []),
        escalation_flag=concept.get("escalation_flag", False),
        escalation_action=concept.get("escalation_action"),
        match_stage=match_stage,
        match_score=match_score,
        language=language,
    )


def _unmatched_result(language: str) -> MatchResult:
    fallback_text = {
        "en": "I don't have specific information on that yet. For anything serious, please visit your nearest ASHA worker or call 108 in an emergency.",
        "hi": "मेरे पास इस बारे में अभी विशेष जानकारी नहीं है। किसी भी गंभीर समस्या के लिए, कृपया अपने नज़दीकी आशा कार्यकर्ता से मिलें या आपातकाल में 108 पर कॉल करें।",
        "kn": "ಇದರ ಬಗ್ಗೆ ನನ್ನ ಬಳಿ ಇನ್ನೂ ನಿರ್ದಿಷ್ಟ ಮಾಹಿತಿ ಇಲ್ಲ. ಯಾವುದೇ ಗಂಭೀರ ಸಮಸ್ಯೆಗೆ, ದಯವಿಟ್ಟು ನಿಮ್ಮ ಹತ್ತಿರದ ಆಶಾ ಕಾರ್ಯಕರ್ತೆಯನ್ನು ಭೇಟಿ ಮಾಡಿ ಅಥವಾ ತುರ್ತು ಪರಿಸ್ಥಿತಿಯಲ್ಲಿ 108ಗೆ ಕರೆ ಮಾಡಿ.",
    }
    return MatchResult(
        matched=False,
        intent="unmatched",
        response_text=fallback_text.get(language, fallback_text["en"]),
        language=language,
    )


# --------------------------------------------------------------------------
# Public entrypoint
# --------------------------------------------------------------------------

def resolve_query(raw_text: str, language: str = "en") -> MatchResult:
    """
    Main pipeline entrypoint. Runs Stage 0 -> 1 -> 2 -> 3 -> 4 in sequence
    and returns a MatchResult. This function has no side effects, no I/O
    beyond the KB already loaded in memory, and is safe to call concurrently.
    """
    if language not in SUPPORTED_LANGUAGES:
        language = "en"

    # Stage 0
    normalized_text = normalize(raw_text)
    if not normalized_text:
        return _unmatched_result(language)

    # Stage 1 — critical veto, always runs first, always wins.
    critical_cid = stage1_emergency_scan(normalized_text, language)
    if critical_cid:
        concept = _kb.get(critical_cid)
        if concept:
            return _concept_to_result(concept, language, match_stage="stage1_emergency")

    # Stage 2 — exact concept match.
    exact_cid = stage2_exact_match(normalized_text, language)
    if exact_cid:
        concept = _kb.get(exact_cid)
        if concept:
            return _concept_to_result(concept, language, match_stage="stage2_exact")

    # Stage 3 — fuzzy typo fallback (non-critical concepts only).
    fuzzy_cid, fuzzy_score = stage3_fuzzy_match(normalized_text, language)
    if fuzzy_cid:
        concept = _kb.get(fuzzy_cid)
        if concept:
            return _concept_to_result(
                concept, language, match_stage="stage3_fuzzy", match_score=fuzzy_score
            )

    # Stage 4 fallthrough — nothing matched.
    return _unmatched_result(language)


# --------------------------------------------------------------------------
# Self-test (run directly: `python matcher.py`)
# --------------------------------------------------------------------------

if __name__ == "__main__":
    test_cases = [
        ("snake bite happened to my father", "en"),
        ("seene mein dard ho raha hai", "hi"),
        ("ಎದೆ ನೋವು ಆಗ್ತಿದೆ", "kn"),
        ("sir dardh ho raha hai", "hi"),
        ("shir nolu ide", "kn"),
        ("mujhe bukhar hai", "hi"),
        ("do you have paracetamol", "en"),
        ("ಡೆಂಗ್ಯೂ ಬಗ್ಗೆ ಹೇಳಿ", "kn"),
        ("random unrelated gibberish text", "en"),
    ]

    for text, lang in test_cases:
        result = resolve_query(text, lang)
        print(f"\nINPUT: '{text}' (lang={lang})")
        print(f"  matched={result.matched} stage={result.match_stage} "
              f"concept={result.concept_id} score={result.match_score}")
        print(f"  -> {result.response_text}")
