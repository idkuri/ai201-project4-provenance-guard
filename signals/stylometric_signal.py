import math
import re


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[.!?]+", text)
    return [p.strip() for p in parts if p.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def run_stylometric_signal(text: str) -> float:
    """Return 0-1 score where higher values indicate AI-like uniformity."""
    sentences = _sentences(text)
    words = _words(text)

    if not words:
        return 0.5

    # Sentence length uniformity (low coefficient of variation -> more AI-like)
    if len(sentences) >= 2:
        lengths = [len(s.split()) for s in sentences]
        mean_len = sum(lengths) / len(lengths)
        if mean_len > 0:
            std_dev = math.sqrt(
                sum((l - mean_len) ** 2 for l in lengths) / len(lengths)
            )
            cv = std_dev / mean_len
            variance_score = 1.0 - min(1.0, cv / 0.5)
        else:
            variance_score = 0.5
    else:
        variance_score = 0.55

    # Type-token ratio helps on short casual text; weight it lightly for long pieces
    unique_ratio = len(set(words)) / len(words)
    ttr_score = 1.0 - min(1.0, unique_ratio / 0.72)

    # Formal transition phrases common in AI prose
    lower = text.lower()
    transitions = [
        "furthermore",
        "moreover",
        "additionally",
        "it is important to note",
        "in conclusion",
        "paradigm shift",
        "stakeholders",
    ]
    transition_hits = sum(1 for phrase in transitions if phrase in lower)
    transition_score = min(1.0, transition_hits / 2.0)

    # Lack of contractions often signals polished AI/formal text
    contraction_markers = ["don't", "won't", "can't", "i'm", "it's", "that's"]
    has_contractions = any(c in lower for c in contraction_markers)
    formality_score = 0.75 if not has_contractions and len(words) > 20 else 0.35

    combined = (
        variance_score * 0.25
        + ttr_score * 0.10
        + transition_score * 0.40
        + formality_score * 0.25
    )
    return max(0.0, min(1.0, combined))
