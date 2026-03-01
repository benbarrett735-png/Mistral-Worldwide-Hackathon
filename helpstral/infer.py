"""
Helpstral inference CLI.
Uses the fine-tuned endpoint (HELPSTRAL_ENDPOINT) via run_helpstral_agent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import HELPSTRAL_ENDPOINT
from helpstral.agent import run_helpstral_agent


def check_distress(image_base64: str) -> dict:
    """
    Run Helpstral via fine-tuned endpoint.
    Returns {"status": "SAFE" | "DISTRESS" | ..., "raw": str}.
    Requires HELPSTRAL_ENDPOINT.
    """
    if not HELPSTRAL_ENDPOINT:
        return {"status": "SAFE", "raw": "HELPSTRAL_ENDPOINT not set"}
    result = run_helpstral_agent(image_base64)
    return {"status": result.get("status", "SAFE"), "raw": str(result)}


if __name__ == "__main__":
    import base64

    if len(sys.argv) < 2:
        print("Usage: python infer.py <image.jpg>")
        sys.exit(1)

    path = Path(sys.argv[1])
    b64 = base64.b64encode(path.read_bytes()).decode()
    result = check_distress(b64)
    print(f"Result: {result}")
