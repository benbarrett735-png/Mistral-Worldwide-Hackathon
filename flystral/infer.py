"""
Flystral inference CLI.
Uses the fine-tuned endpoint (FLYSTRAL_ENDPOINT) via run_flystral_agent.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import FLYSTRAL_ENDPOINT
from flystral.agent import run_flystral_agent


def get_command(image_base64: str) -> dict:
    """
    Run Flystral via fine-tuned endpoint.
    Returns {"command": str, "param": str, "raw": str}.
    Requires FLYSTRAL_ENDPOINT.
    """
    if not FLYSTRAL_ENDPOINT:
        return {"command": "FOLLOW", "param": "0.5", "raw": "FLYSTRAL_ENDPOINT not set"}
    result = run_flystral_agent(image_base64)
    return {
        "command": result.get("command", "FOLLOW"),
        "param": str(result.get("param", "0.5")),
        "raw": str(result),
    }


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
