import re


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def run_burstiness_signal(text: str) -> float:
    """Return 0-1 score based on n-gram repetition (AI repeats patterns)."""
    words = _words(text)
    if len(words) < 4:
        return 0.5

    bigrams = [tuple(words[i : i + 2]) for i in range(len(words) - 1)]
    if not bigrams:
        return 0.5

    unique_bigrams = len(set(bigrams))
    repetition_ratio = 1.0 - (unique_bigrams / len(bigrams))

    # Word frequency skew: repeated function words inflate AI score
    freq = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1
    max_freq = max(freq.values())
    skew = max_freq / len(words)

    score = (repetition_ratio * 0.6) + (skew * 0.4)
    return max(0.0, min(1.0, score))
