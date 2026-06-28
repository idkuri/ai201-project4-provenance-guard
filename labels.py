def generate_label(attribution: str, confidence: float, verified_badge: bool = False) -> str:
    """Map attribution and confidence to plain-language label text."""
    if attribution == "likely_ai":
        pct = round(confidence * 100)
        label = (
            f"Likely AI-generated. Our analysis found strong signs of automated "
            f"writing (confidence: {pct}%). This is a high-confidence call, not a guarantee."
        )
    elif attribution == "likely_human":
        pct = round((1 - confidence) * 100)
        label = (
            f"Likely human-written. Our analysis found strong signs of authentic, "
            f"personal writing (confidence: {pct}%). This is a high-confidence call, not a guarantee."
        )
    else:
        pct = round(confidence * 100)
        label = (
            f"Attribution uncertain. We couldn't confidently tell if this is human or AI "
            f"(confidence: {pct}%). Creators can appeal this result."
        )

    if verified_badge:
        label += " · Verified Human Creator"

    return label
