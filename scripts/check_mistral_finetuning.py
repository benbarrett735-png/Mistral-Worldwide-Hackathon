#!/usr/bin/env python3
"""
Check what your Mistral API key can see for fine-tuning.
Run from repo root with MISTRAL_API_KEY in .env.

Usage: python scripts/check_mistral_finetuning.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import MISTRAL_API_KEY

if not MISTRAL_API_KEY:
    print("Set MISTRAL_API_KEY in .env")
    sys.exit(1)

from mistralai import Mistral

client = Mistral(api_key=MISTRAL_API_KEY)

print("=== List models (and fine_tuning capability) ===\n")
try:
    r = client.models.list()
    for m in getattr(r, "data", []) or []:
        cap = getattr(m, "capabilities", None) or {}
        ft = getattr(cap, "fine_tuning", None) if hasattr(cap, "fine_tuning") else cap.get("fine_tuning") if isinstance(cap, dict) else None
        if ft or "fine_tun" in str(m).lower() or "pixtral" in str(getattr(m, "id", "")).lower():
            print(f"  id={getattr(m, 'id', m)}  fine_tuning={ft}")
    if not getattr(r, "data", None):
        print("  (no models or empty list)")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== List fine-tuning jobs ===\n")
try:
    jobs = client.fine_tuning.jobs.list()
    for j in getattr(jobs, "data", []) or []:
        print(f"  id={getattr(j, 'id', j)}  status={getattr(j, 'status', '?')}  model={getattr(j, 'model', '?')}")
    if not getattr(jobs, "data", None):
        print("  (no jobs)")
except Exception as e:
    print(f"  Error: {e}")

print("\n=== List uploaded files (purpose fine-tune) ===\n")
try:
    fl = client.files.list()
    for f in getattr(fl, "data", []) or []:
        if getattr(f, "purpose", None) == "fine-tune":
            print(f"  id={getattr(f, 'id', f)}  filename={getattr(f, 'file_name', '?')}")
    if not any(getattr(f, "purpose", None) == "fine-tune" for f in getattr(fl, "data", []) or []):
        print("  (no fine-tune files)")
except Exception as e:
    print(f"  Error: {e}")

print("\nDone. If 'Available model(s):' is empty on job create, fine-tuning is not enabled for this key/account.")
