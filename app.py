import uuid
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename
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
app.config["TEMPLATES_AUTO_RELOAD"] = True

UPLOAD_DIR = Path(__file__).resolve().parent / "storage" / "uploads"
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

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


def _save_uploaded_image(image_file) -> str | None:
    if not image_file or not image_file.filename:
        return None

    filename = secure_filename(image_file.filename)
    if not filename:
        return None

    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_EXTENSIONS:
        return None

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4()}{suffix}"
    image_file.save(UPLOAD_DIR / stored_name)
    return stored_name


def _parse_submit_request() -> tuple[dict, str | None]:
    if request.form or request.files:
        creator_id = request.form.get("creator_id", "").strip()
        text = request.form.get("text", "").strip()
        image_path = _save_uploaded_image(request.files.get("image"))
        content_type = "multimodal" if image_path else "text"
        data = {
            "creator_id": creator_id,
            "text": text,
            "content_type": content_type,
        }
        return data, image_path

    data = request.get_json(silent=True) or {}
    return data, None


@app.route("/")
def index():
    return jsonify(
        {
            "service": "Provenance Guard",
            "endpoints": {
                "POST /submit": "Classify text content",
                "POST /appeal": "Contest a classification",
                "GET /log": "View audit log",
                "POST /verify": "Verify human creator",
                "GET /dashboard": "Analytics dashboard",
            },
        }
    )


@app.route("/submit", methods=["POST"])
@limiter.limit("10 per minute;100 per day")
def submit():
    data, image_path = _parse_submit_request()
    text, content_type = _build_text_payload(data)
    creator_id = data.get("creator_id", "").strip()
    if image_path and text:
        content_type = "multimodal"

    if not creator_id:
        return jsonify({"error": "creator_id is required"}), 400
    if not text and not image_path:
        return jsonify({"error": "text or image is required"}), 400
    if not text and image_path:
        text = f"Image upload: {image_path}"
        content_type = "metadata"

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
        "image_path": image_path,
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


@app.route("/stats", methods=["GET"])
def stats():
    return jsonify(get_dashboard_stats())


@app.route("/dashboard", methods=["GET"])
def dashboard():
    stats = get_dashboard_stats()
    return render_template("dashboard.html", stats=stats)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)
