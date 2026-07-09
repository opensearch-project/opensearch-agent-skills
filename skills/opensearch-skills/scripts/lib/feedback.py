"""Anonymous feedback collection for OpenSearch Agent Skills.

Submits feedback via Google Forms POST endpoint.
No authentication required from the submitter. Results visible only to form owner.
"""

import urllib.parse
import urllib.request

# Google Form configuration.
GOOGLE_FORM_ID = "1FAIpQLScuPX1RdlAgzniUREg9E0wVtPG31lOCnbKUtRRKsMMxgzDpVQ"
FIELD_IDS = {
    "feedback_type": "entry.432142350",
    "skill_name": "entry.843860941",
    "context": "entry.1975973927",
    "comment": "entry.414948368",
    "rating": "entry.1436210928",
}


def format_feedback_preview(
    feedback_type: str,
    skill_name: str,
    context: str = "",
    comment: str = "",
    rating: str = "",
) -> str:
    """Format feedback data for user review before submission."""
    lines = [
        "--- Feedback Preview ---",
        f"Type: {feedback_type}",
        f"Skill: {skill_name}",
    ]
    if rating:
        lines.append(f"Rating: {rating}/5")
    if context:
        lines.append(f"Context: {context[:200]}{'...' if len(context) > 200 else ''}")
    if comment:
        lines.append(f"Comment: {comment}")
    lines.append("------------------------")
    return "\n".join(lines)


def submit_feedback(
    feedback_type: str,
    skill_name: str,
    context: str = "",
    comment: str = "",
    rating: str = "",
) -> str:
    """Submit anonymous feedback via Google Forms POST.

    Args:
        feedback_type: One of 'failure', 'gap', 'friction', 'success'.
        skill_name: Name of the skill generating feedback.
        context: Technical context (error message, command attempted, etc).
        comment: User's free-text comment.
        rating: Rating (1-5) for success feedback.

    Returns:
        Success or error message.
    """
    if not GOOGLE_FORM_ID or not FIELD_IDS.get("feedback_type"):
        return (
            "Feedback collection is not yet configured. "
            "Set GOOGLE_FORM_ID and FIELD_IDS in scripts/lib/feedback.py"
        )

    url = f"https://docs.google.com/forms/d/e/{GOOGLE_FORM_ID}/formResponse"

    payload = {}
    if FIELD_IDS["feedback_type"]:
        payload[FIELD_IDS["feedback_type"]] = feedback_type.capitalize()
    if FIELD_IDS["skill_name"]:
        payload[FIELD_IDS["skill_name"]] = skill_name
    if FIELD_IDS["context"]:
        payload[FIELD_IDS["context"]] = (context[:2000] if context else "")
    if FIELD_IDS["comment"]:
        payload[FIELD_IDS["comment"]] = (comment[:2000] if comment else "")
    if FIELD_IDS["rating"] and rating:
        payload[FIELD_IDS["rating"]] = rating

    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data)

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return "✓ Feedback submitted anonymously. Thank you!"
            return f"Submission failed with status {resp.status}"
    except Exception as e:
        return f"Failed to submit feedback: {e}"
