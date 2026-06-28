AI_THRESHOLD = 0.80
HUMAN_THRESHOLD = 0.30

# Weights when all 3 signals are available (M7 ensemble)
WEIGHT_LLM = 0.50
WEIGHT_STYLO = 0.30
WEIGHT_BURST = 0.20

# Weights for base 2-signal pipeline (M4)
WEIGHT_LLM_BASE = 0.60
WEIGHT_STYLO_BASE = 0.40


def compute_confidence(
    llm_score: float,
    stylometric_score: float,
    burstiness_score: float | None = None,
    content_type: str = "text",
    use_ensemble: bool = False,
) -> tuple[float, str]:
    """Combine signal scores into confidence and attribution."""
    if use_ensemble and burstiness_score is not None:
        confidence = (
            WEIGHT_LLM * llm_score
            + WEIGHT_STYLO * stylometric_score
            + WEIGHT_BURST * burstiness_score
        )
    else:
        confidence = (
            WEIGHT_LLM_BASE * llm_score + WEIGHT_STYLO_BASE * stylometric_score
        )

    if content_type == "metadata":
        # Metadata-only: rely more on structure, less on LLM
        confidence = 0.3 * llm_score + 0.5 * stylometric_score + 0.2 * (
            burstiness_score if burstiness_score is not None else stylometric_score
        )

    confidence = max(0.0, min(1.0, confidence))

    if confidence >= AI_THRESHOLD:
        attribution = "likely_ai"
    elif confidence <= HUMAN_THRESHOLD:
        attribution = "likely_human"
    else:
        attribution = "uncertain"

    return round(confidence, 3), attribution
