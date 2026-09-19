"""
Sanitization layer — masks sensitive data before it reaches the LLM.
Re-identifies on our side via a session vault.
"""
import re

# Ordered list: (label, compiled pattern)
PATTERNS = [
    ("EMAIL", re.compile(r"[\w\.\-+]+@[\w\.\-]+\.\w+")),
    ("API_KEY", re.compile(r"(?:sk_|gsk_|ghp_|AKIA|xoxb-)[A-Za-z0-9_\-]{10,}")),
    ("CREDIT_CARD", re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b")),
    ("PHONE", re.compile(r"(?:\+\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{4}\b")),
    ("SALARY", re.compile(r"\$\s?\d{2,3}(?:,\d{3})+(?:\.\d+)?|\$\s?\d+K\b", re.IGNORECASE)),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]

# Optional: names to mask (only if user adds them) — empty by default
SENSITIVE_WORDS = []


def sanitize(text: str) -> tuple[str, dict]:
    """
    Replace sensitive values with reversible tokens.
    Returns (sanitized_text, vault).
    """
    if not text:
        return text, {}

    vault: dict = {}
    counters: dict = {}

    for label, pattern in PATTERNS:
        def _repl(match, _label=label):
            counters[_label] = counters.get(_label, 0) + 1
            token = f"{_label}_{counters[_label]}"
            # Guard against accidental double-token collisions
            while token in vault:
                counters[_label] += 1
                token = f"{_label}_{counters[_label]}"
            vault[token] = match.group(0)
            return token

        text = pattern.sub(_repl, text)

    # Custom sensitive words (client names, codenames, etc.)
    for i, word in enumerate(SENSITIVE_WORDS, start=1):
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