"""
Sanitization layer — masks sensitive data before it reaches the LLM.
Re-identifies on our side via a session vault.
"""
import re
# --- Layer 2: NER via spaCy ---
_nlp = None

def _get_nlp():
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load("en_core_web_sm")
    return _nlp


def detect_ner_entities(text: str) -> list:
    """Return list of (entity_type, value) tuples from spaCy NER."""
    if not text:
        return []
    nlp = _get_nlp()
    doc = nlp(text)
    entities = []
    for ent in doc.ents:
        # Keep only the labels that matter for meetings
        if ent.label_ in {"PERSON", "ORG", "GPE", "LOC", "MONEY", "DATE"}:
            entities.append((ent.label_, ent.text))
    return entities
# Ordered list: (label, compiled pattern)
PATTERNS = [
    ("EMAIL", re.compile(r"[\w\.\-+]+@[\w\.\-]+\.\w+")),
    ("API_KEY", re.compile(r"(?:sk_|gsk_|ghp_|AKIA|xoxb-)[A-Za-z0-9_\-]{10,}")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")),
    ("PHONE", re.compile(r"(?:\+\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b")),
    ("SALARY", re.compile(
    r"(?:\$|₹|€|£|Rs\.?|INR|USD|EUR|GBP)\s?\d{1,3}(?:[,\d]{0,12})(?:\.\d+)?(?:K|M|Cr|Lakh|L)?\b",
    re.IGNORECASE,
)),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]

# Optional: names to mask (only if user adds them) — empty by default
SENSITIVE_WORDS = []

def sanitize(text: str, mask_names: bool = False, custom_terms: list = None) -> tuple[str, dict]:
    """
    Multi-layer sanitization.
    Layer 1: regex patterns (structured PII)
    Layer 2: NER entities (people, orgs) — optional via mask_names
    Layer 4: custom company terms
    """
    if not text:
        return text, {}

    vault: dict = {}
    counters: dict = {}

    def _make_token(label: str, value: str) -> str:
        counters[label] = counters.get(label, 0) + 1
        token = f"{label}_{counters[label]}"
        while token in vault:
            counters[label] += 1
            token = f"{label}_{counters[label]}"
        vault[token] = value
        return token

    # ----- Layer 1: Regex patterns -----
    for label, pattern in PATTERNS:
        def _repl(match, _label=label):
            return _make_token(_label, match.group(0))
        text = pattern.sub(_repl, text)

    # ----- Layer 2: NER (people, orgs) -----
    if mask_names:
        try:
            ner_entities = detect_ner_entities(text)
        except Exception:
            ner_entities = []

        # Sort by length descending so "Alice Smith" is masked before "Alice"
        ner_entities.sort(key=lambda x: len(x[1]), reverse=True)

        for label, value in ner_entities:
            if value in text and value not in vault.values():
                token_label = {
                    "PERSON": "PERSON",
                    "ORG": "ORG",
                    "GPE": "LOC",
                    "LOC": "LOC",
                    "MONEY": "MONEY",
                    "DATE": "DATE",
                }.get(label, "ENTITY")
                token = _make_token(token_label, value)
                text = text.replace(value, token)

    # ----- Layer 4: Custom terms -----
    terms = custom_terms or SENSITIVE_WORDS
    for i, word in enumerate(terms, start=1):
        if word and word in text:
            token = f"TERM_{i}"
            vault[token] = word
            text = text.replace(word, token)

    return text, vault


def detokenize(text: str, vault: dict) -> str:
    """Restore original values from the vault."""
    if not text or not vault:
        return text
    # Replace longer tokens first to avoid partial collisions
    for token in sorted(vault.keys(), key=len, reverse=True):
        text = text.replace(token, vault[token])
    return text


def detokenize_obj(obj, vault: dict):
    """
    Recursively detokenize strings inside dicts/lists (for LLM JSON output).
    """
    if isinstance(obj, str):
        return detokenize(obj, vault)
    if isinstance(obj, list):
        return [detokenize_obj(x, vault) for x in obj]
    if isinstance(obj, dict):
        return {k: detokenize_obj(v, vault) for k, v in obj.items()}
    return obj
def validate_output(llm_output: str, vault: dict) -> list:
    """
    Check that:
    1. Every token in the output maps to a vault entry.
    2. No obvious raw PII leaked into the output.
    Returns a list of warning strings.
    """
    warnings = []

    # Check 1: unknown tokens (LLM hallucinated a token that isn't in vault)
    import re as _re
    tokens = _re.findall(r"\b([A-Z_]+_\d+)\b", llm_output)
    for t in set(tokens):
        if t not in vault:
            warnings.append(f"Unknown token in output: {t} (not in vault)")

    # Check 2: raw PII appeared in output
    for label, pattern in PATTERNS:
        matches = pattern.findall(llm_output)
        if matches:
            warnings.append(f"Raw {label} leaked into LLM output: {matches[:3]}")

    return warnings
