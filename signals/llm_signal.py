import json
import os
import re

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

MODEL = "llama-3.3-70b-versatile"


def run_llm_signal(text: str) -> float:
    """Return 0-1 score where higher values indicate AI-generated text."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key or api_key == "your_key_here":
        return _fallback_llm_score(text)

    client = Groq(api_key=api_key)
    prompt = (
        "You are an expert at detecting AI-generated writing. "
        "Analyze the text and return JSON only: "
        '{"ai_likelihood": <float 0.0 to 1.0>}. '
        "Use the full range: polished generic AI essays should score 0.85+, "
        "casual personal human writing should score 0.15 or below, "
        "borderline cases should land near 0.5.\n\n"
        f"Text:\n{text}"
    )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            return _fallback_llm_score(text)
        data = json.loads(match.group())
        score = float(data.get("ai_likelihood", 0.5))
        return max(0.0, min(1.0, score))
    except Exception:
        return _fallback_llm_score(text)


def _fallback_llm_score(text: str) -> float:
    """Simple heuristic when Groq is unavailable."""
    lower = text.lower()
    ai_phrases = [
        "it is important to note",
        " furthermore",
        "paradigm shift",
        "stakeholders",
        "in conclusion",
        "additionally",
    ]
    hits = sum(1 for phrase in ai_phrases if phrase in lower)
    casual_markers = ["lol", "idk", "honestly", "ok so", "won't", "don't", "??"]
    casual = sum(1 for marker in casual_markers if marker in lower)
    score = 0.35 + (hits * 0.15) - (casual * 0.10)
    return max(0.0, min(1.0, score))
