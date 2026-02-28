"""
Flystral inference.
Call get_command(image_base64) -> {"command": str, "param": str}
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FLYSTRAL_MODEL_ID, MISTRAL_API_KEY

USER_PROMPT = (
    "You are Flystral, a drone autopilot AI. "
    "Analyze this drone camera image and output exactly one command from:\n"
    "FOLLOW|<speed 0.1-1.0>, AVOID_LEFT|<dist_m>, AVOID_RIGHT|<dist_m>, "
    "CLIMB|<meters>, HOVER|<seconds>, REPLAN|0, DESCEND|<meters>\n"
    "Respond with the command only. Example: FOLLOW|0.7"
)

VALID_COMMANDS = {"FOLLOW", "AVOID_LEFT", "AVOID_RIGHT", "CLIMB", "HOVER", "REPLAN", "DESCEND"}


def get_command(image_base64: str) -> dict:
    """
    Run Flystral vision inference.
    Returns {"command": str, "param": str, "raw": str}.
    Falls back to FOLLOW|0.5 if model / key unavailable.
    """
    if not MISTRAL_API_KEY:
        return {"command": "FOLLOW", "param": "0.5", "raw": "NO_KEY"}

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        response = client.chat.complete(
            model=FLYSTRAL_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    ],
                }
            ],
            max_tokens=20,
        )
        raw = response.choices[0].message.content.strip()
        return parse_command(raw)
    except Exception as e:
        return {"command": "FOLLOW", "param": "0.5", "raw": f"ERROR:{e}"}


def parse_command(raw: str) -> dict:
    """Parse raw model output 'COMMAND|param' into a structured dict."""
    parts = raw.strip().split("|")
    command = parts[0].upper().strip()
    param = parts[1].strip() if len(parts) > 1 else "0"

    if command not in VALID_COMMANDS:
        command = "FOLLOW"
        param = "0.5"

    return {"command": command, "param": param, "raw": raw}


if __name__ == "__main__":
    import base64

    if len(sys.argv) < 2:
        print("Usage: python infer.py <image.jpg>")
        sys.exit(1)

    path = Path(sys.argv[1])
    b64 = base64.b64encode(path.read_bytes()).decode()
    result = get_command(b64)
    print(f"Command: {result['command']}  Param: {result['param']}")
    print(f"Raw: {result['raw']}")
