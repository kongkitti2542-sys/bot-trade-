import json
import os
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from zoneinfo import ZoneInfo

API_URL = "https://generativelanguage.googleapis.com/v1beta/models"
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

DAILY_LIMIT = 20
STATE_FILE = Path("ai_judge_v1_state.json")

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
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

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
    state = load_state()
    return max(0, DAILY_LIMIT - int(state.get("calls", 0)))


def _extract_text(response):
    candidates = response.get("candidates", [])

    if not candidates:
        raise ValueError("Gemini returned no candidates")

    parts = candidates[0].get("content", {}).get("parts", [])

    texts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and part.get("text")
    ]

    if not texts:
        raise ValueError("Gemini returned no text")

    return "".join(texts).strip()


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
    Research-only Gemini judge.

    Returns WAIT without calling Gemini when:
      - API key is missing
      - daily budget is exhausted
      - request/response fails
      - response JSON is invalid
    """

    api_key = os.environ.get("GEMINI_API_KEY")

    if not api_key:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": ["GEMINI_API_KEY is not set"],
            "source": "SAFE_FALLBACK",
        }

    state = load_state()

    if int(state.get("calls", 0)) >= DAILY_LIMIT:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": ["Daily AI call budget exhausted"],
            "source": "BUDGET_GUARD",
        }

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
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt,
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "responseMimeType": "application/json",
        },
    }

    url = f"{API_URL}/{MODEL}:generateContent"

    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
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

        validated["source"] = "GEMINI"
        validated["model"] = MODEL
        validated["calls_today"] = state["calls"]

        return validated

    except HTTPError as exc:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": [f"Gemini HTTP error: {exc.code}"],
            "source": "SAFE_FALLBACK",
            "model": MODEL,
            "calls_today": state["calls"],
        }

    except (URLError, TimeoutError) as exc:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": [f"Gemini connection error: {type(exc).__name__}"],
            "source": "SAFE_FALLBACK",
            "model": MODEL,
            "calls_today": state["calls"],
        }

    except Exception as exc:
        return {
            "decision": "WAIT",
            "quality": "LOW",
            "reasons": [f"Invalid Gemini response: {type(exc).__name__}"],
            "source": "SAFE_FALLBACK",
            "model": MODEL,
            "calls_today": state["calls"],
        }


if __name__ == "__main__":
    print("AI JUDGE V1")
    print("Model           :", MODEL)
    print("Daily limit     :", DAILY_LIMIT)
    print("Calls remaining :", remaining_calls())
    print("API key         :", "SET" if os.environ.get("GEMINI_API_KEY") else "NOT SET")
    print("Core modified   : NO")
