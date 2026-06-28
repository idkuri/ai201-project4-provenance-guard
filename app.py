import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from labels import generate_label
from scoring import compute_confidence
from signals.burstiness_signal import run_burstiness_signal
from signals.llm_signal import run_llm_signal
from signals.stylometric_signal import run_stylometric_signal
from storage.db import (
    get_dashboard_stats,
    get_log_entries,
    get_submission,
    init_db,
    is_verified_creator,
    set_verified_creator,
    update_appeal,
    write_audit_entry,
)

app = Flask(__name__)

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)


def _build_text_payload(data: dict) -> tuple[str, str]:
    content_type = data.get("content_type", "text")
    if content_type not in ("text", "metadata"):
        content_type = "text"

    if content_type == "metadata":
        metadata = data.get("metadata") or {}
        parts = [
            str(metadata.get("title", "")),
            str(metadata.get("tags", "")),
            str(metadata.get("author_bio", "")),
        ]
        text = " ".join(p for p in parts if p).strip()
        if not text:
            text = data.get("text", "").strip()
    else:
        text = data.get("text", "").strip()

    return text, content_type


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data = request.get_json(silent=True) or {}
    text, content_type = _build_text_payload(data)
    creator_id = data.get("creator_id", "").strip()

    if not text or not creator_id:
        return jsonify({"error": "text and creator_id are required"}), 400

    content_id = str(uuid.uuid4())
    llm_score = run_llm_signal(text)
    stylometric_score = run_stylometric_signal(text)
    burstiness_score = run_burstiness_signal(text)

    confidence, attribution = compute_confidence(
        llm_score,
        stylometric_score,
        burstiness_score=burstiness_score,
        content_type=content_type,
        use_ensemble=False,
    )

    verified = is_verified_creator(creator_id)
    label = generate_label(attribution, confidence, verified_badge=verified)

    entry = {
        "content_id": content_id,
        "creator_id": creator_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attribution": attribution,
        "confidence": confidence,
        "llm_score": round(llm_score, 3),
        "stylometric_score": round(stylometric_score, 3),
        "burstiness_score": round(burstiness_score, 3),
        "status": "classified",
        "content_type": content_type,
        "label": label,
    }
    write_audit_entry(entry)

    response = {
        "content_id": content_id,
        "attribution": attribution,
        "confidence": confidence,
        "label": label,
        "creator_badge": "verified_human" if verified else None,
    }
    return jsonify(response)


@app.route("/appeal", methods=["POST"])
def appeal():
    data = request.get_json(silent=True) or {}
    content_id = data.get("content_id", "").strip()
    creator_id = data.get("creator_id", "").strip()
    creator_reasoning = data.get("creator_reasoning", "").strip()

    if not content_id or not creator_id or not creator_reasoning:
        return jsonify(
            {"error": "content_id, creator_id, and creator_reasoning are required"}
        ), 400

    submission = get_submission(content_id)
    if not submission:
        return jsonify({"error": "content not found"}), 404
    if submission["creator_id"] != creator_id:
        return jsonify({"error": "creator_id does not match submission"}), 403

    update_appeal(content_id, creator_reasoning)

    return jsonify(
        {
            "message": "Appeal received",
            "content_id": content_id,
            "status": "under_review",
        }
    )


@app.route("/verify", methods=["POST"])
def verify():
    data = request.get_json(silent=True) or {}
    creator_id = data.get("creator_id", "").strip()
    sample_text = data.get("sample_text", "").strip()

    if not creator_id or not sample_text:
        return jsonify({"error": "creator_id and sample_text are required"}), 400

    llm_score = run_llm_signal(sample_text)
    stylometric_score = run_stylometric_signal(sample_text)
    burstiness_score = run_burstiness_signal(sample_text)
    confidence, attribution = compute_confidence(
        llm_score, stylometric_score, burstiness_score=burstiness_score
    )

    if attribution == "likely_human" and confidence <= 0.25:
        set_verified_creator(creator_id)
        return jsonify(
            {
                "verified_human": True,
                "creator_id": creator_id,
                "message": "Creator verified as human writer.",
            }
        )

    return jsonify(
        {
            "verified_human": False,
            "creator_id": creator_id,
            "confidence": confidence,
            "attribution": attribution,
            "message": "Sample did not meet verification threshold.",
        }
    )


@app.route("/log", methods=["GET"])
def log():
    return jsonify({"entries": get_log_entries()})


@app.route("/dashboard", methods=["GET"])
def dashboard():
    stats = get_dashboard_stats()
    return render_template("dashboard.html", stats=stats)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
