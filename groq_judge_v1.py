import json
import os
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo


API_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
DAILY_LIMIT = 20
STATE_FILE = Path("groq_judge_v1_state.json")

SYSTEM_PROMPT = """
You are a trading opportunity quality judge.

You do NOT predict the future.
You do NOT place orders.
You do NOT set position size.
You do NOT override risk management.

Your only job is to judge whether a Quant-generated trading candidate
has enough contextual quality to deserve further risk evaluation.

Return ONLY valid JSON with exactly:
{
  "decision": "PASS" or "WAIT",
  "quality": "HIGH" or "MEDIUM" or "LOW",
  "reasons": ["short reason 1", "short reason 2"]
}

Be conservative.
If information is conflicting, incomplete, or suspicious, return WAIT.
Do not invent missing market data.
"""

BANGKOK = ZoneInfo("Asia/Bangkok")


def today_key():
    return datetime.now(BANGKOK).strftime("%Y-%m-%d")


def load_state():
    if not STATE_FILE.exists():
        return {
            "date": today_key(),
            "calls": 0,
        }

    try:
        state = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        if state.get("date") != today_key():
            return {
                "date": today_key(),
                "calls": 0,
            }

        return state

    except Exception:
        return {
            "date": today_key(),
            "calls": 0,
        }


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2),
        encoding="utf-8",
    )


def remaining_calls():
    """Return API calls made today.

    There is no artificial local daily cap.
    The real Groq API quota/rate limit is authoritative.
    """
    state = load_state()
    return int(state.get("calls", 0))
def _extract_text(response):
    choices = response.get("choices", [])

    if not choices:
        raise ValueError("Groq returned no choices")

    message = choices[0].get("message", {})
    text = message.get("content", "")

    if not text:
        raise ValueError("Groq returned no text")

    return text.strip()


def _validate_result(result):
    if not isinstance(result, dict):
        raise ValueError("AI result is not an object")

    if result.get("decision") not in {"PASS", "WAIT"}:
        raise ValueError("Invalid AI decision")

    if result.get("quality") not in {"HIGH", "MEDIUM", "LOW"}:
        raise ValueError("Invalid AI quality")

    reasons = result.get("reasons")

    if not isinstance(reasons, list):
        raise ValueError("Invalid AI reasons")

    return {
        "decision": result["decision"],
        "quality": result["quality"],
        "reasons": [str(x) for x in reasons[:5]],
    }


def judge(candidate):
    """
    Research-only Groq judge.

    Returns WAIT without calling Groq when:
    - API key is missing
    - daily budget is exhausted
    - request/response fails
    - response JSON is invalid
    """

    api_key = os.environ.get("GROQ_API_KEY")

    if not api_key:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": ["GROQ_API_KEY is not set"],
            "source": "SAFE_FALLBACK",
        }

    state = load_state()

    user_payload = json.dumps(
        candidate,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )

    prompt = (
        SYSTEM_PROMPT
        + "\n\nQUANT CANDIDATE:\n"
        + user_payload
    )

    body = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_payload,
            },
        ],
        "temperature": 0.0,
        "response_format": {
            "type": "json_object"
        },
    }

    request = Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "personal-trading-bot/1.0",
        },
        method="POST",
    )

    # Count only an actual API attempt.
    state["calls"] = int(state.get("calls", 0)) + 1
    save_state(state)

    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")

        response_json = json.loads(raw)
        text = _extract_text(response_json)
        result = json.loads(text)
        validated = _validate_result(result)

        validated["source"] = "GROQ"
        validated["model"] = MODEL
        validated["calls_today"] = state["calls"]

        return validated

    except HTTPError as exc:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": [f"Groq HTTP error: {exc.code}"],
            "source": "SAFE_FALLBACK",
            "model": MODEL,
            "calls_today": state["calls"],
        }

    except (URLError, TimeoutError) as exc:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": [
                f"Groq connection error: {type(exc).__name__}"
            ],
            "source": "SAFE_FALLBACK",
            "model": MODEL,
            "calls_today": state["calls"],
        }

    except Exception as exc:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": [
                f"Invalid Groq response: {type(exc).__name__}"
            ],
            "source": "SAFE_FALLBACK",
            "model": MODEL,
            "calls_today": state["calls"],
        }


if __name__ == "__main__":
    print("GROQ AI JUDGE V1")
    print("Model           :", MODEL)
    print("Daily limit     :", DAILY_LIMIT)
    print("Calls remaining :", remaining_calls())
    print(
        "API key         :",
        "SET" if os.environ.get("GROQ_API_KEY") else "NOT SET"
    )
    print("Core modified   : NO")
