"""
Helpstroll inference.
Call check_distress(image_base64) -> "SAFE" | "DISTRESS"
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import HELPSTROLL_MODEL_ID, MISTRAL_API_KEY

USER_PROMPT = (
    "Analyze this image. Is the person in danger or distress? "
    "Respond with exactly one word: DISTRESS or SAFE."
)


def check_distress(image_base64: str) -> dict:
    """
    Run Helpstroll distress detection on a base64 JPEG image.
    Returns {"status": "SAFE" | "DISTRESS", "raw": str}.
    Falls back to "SAFE" if model / key unavailable.
    """
    if not MISTRAL_API_KEY:
        return {"status": "SAFE", "raw": "NO_KEY"}

    try:
        from mistralai import Mistral
        client = Mistral(api_key=MISTRAL_API_KEY)

        response = client.chat.complete(
            model=HELPSTROLL_MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": USER_PROMPT},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                    ],
                }
            ],
            max_tokens=10,
        )
        raw = response.choices[0].message.content.strip().upper()
        status = "DISTRESS" if "DISTRESS" in raw else "SAFE"
        return {"status": status, "raw": raw}
    except Exception as e:
        return {"status": "SAFE", "raw": f"ERROR:{e}"}


if __name__ == "__main__":
    import base64
    import sys

    if len(sys.argv) < 2:
        print("Usage: python infer.py <image.jpg>")
        sys.exit(1)

    path = Path(sys.argv[1])
    b64 = base64.b64encode(path.read_bytes()).decode()
    result = check_distress(b64)
    print(f"Result: {result}")
