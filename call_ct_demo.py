#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Place a Bland demo outbound call asking to schedule a CT scan.

Loads BLAND_API_KEY and BLAND_DEMO_PHONE_NUMBER from ~/dev/nightborn/.env
(or NIGHTBORN_ENV / overrides). Always dials the demo number — never a
number from the CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

BLAND_CALLS_URL: Final[str] = "https://api.bland.ai/v1/calls"
DEFAULT_ENV_PATH: Final[Path] = Path.home() / "dev" / "nightborn" / ".env"

CT_SCAN_DEMO_SCRIPT: Final[str] = """
You are on a live phone call for a hospital hackathon demo. Be warm, brief, and human.
Speak Czech if the callee answers in Czech; otherwise English.
Ask exactly ONE question per turn. Wait for their answer before asking anything else.
Never stack multiple questions in one sentence or turn.

Your ONLY agenda is to schedule (or confirm interest in) a CT scan appointment.
This is a DEMO — acknowledge that clearly if asked. Do not claim to be a real
hospital clerk with access to their medical record.

Open with one natural line, e.g.:
"Dobrý den, volám z dema Motol / Rakathon — mohl bych s vámi krátce domluvit
termín na CT vyšetření?"

Then follow up one topic at a time only as needed:
1) willing to schedule a CT?
2) preferred day/time window
3) any known contrast allergy (yes/no only)
4) confirm a fictional demo slot if they agree (e.g. "zítra 10:00, radiologie")

Keep the call short. Thank them and end when you have enough or they decline.
""".strip()


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE .env file (no export, no multiline)."""
    values: dict[str, str] = {}
    if not path.is_file():
        raise FileNotFoundError(f"env file not found: {path}")
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line: str = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key: str
        value: str
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        values[key] = value
    return values


def conversational_task(briefing: str) -> str:
    goal: str = briefing.strip() or CT_SCAN_DEMO_SCRIPT
    return "\n".join(
        [
            "You are on a live phone call. Be warm, brief, and human.",
            "Ask exactly ONE question per turn. Wait for their answer before asking anything else.",
            "Never stack multiple questions in one sentence or turn.",
            "Your ONLY agenda is the briefing below.",
            "Open with one natural question that directly serves the briefing.",
            "Follow up one topic at a time. Keep the call short; thank them and end when done.",
            "Briefing / goal for this call (authoritative):",
            goal,
        ]
    )


def place_call(*, api_key: str, phone_number: str, task: str) -> dict[str, object]:
    body: bytes = json.dumps(
        {"phone_number": phone_number, "task": conversational_task(task)}
    ).encode("utf-8")
    request = urllib.request.Request(
        BLAND_CALLS_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload: object = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail: str = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Bland HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Bland request failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise SystemExit(f"unexpected Bland response: {payload!r}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Call the nightborn Bland demo number with a CT-scan demo script."
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(os.environ.get("NIGHTBORN_ENV", DEFAULT_ENV_PATH)),
        help=f"path to nightborn .env (default: {DEFAULT_ENV_PATH})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print who would be dialed and the script; do not call Bland",
    )
    parser.add_argument(
        "--task",
        type=str,
        default=CT_SCAN_DEMO_SCRIPT,
        help="override the call briefing / demo script",
    )
    args: argparse.Namespace = parser.parse_args()

    env: dict[str, str] = load_dotenv(args.env)
    api_key: str = (
        os.environ.get("BLAND_API_KEY") or env.get("BLAND_API_KEY") or ""
    ).strip()
    phone: str = (
        os.environ.get("BLAND_DEMO_PHONE_NUMBER")
        or env.get("BLAND_DEMO_PHONE_NUMBER")
        or ""
    ).strip()

    if not api_key:
        raise SystemExit("BLAND_API_KEY missing (set in nightborn .env or environment)")
    if not phone:
        raise SystemExit(
            "BLAND_DEMO_PHONE_NUMBER missing (set in nightborn .env or environment)"
        )

    masked: str = f"{phone[:4]}…{phone[-2:]}" if len(phone) > 6 else "(set)"
    print(f"Dialing demo number {masked} via Bland…", file=sys.stderr)

    if args.dry_run:
        print(json.dumps({"phone_number": phone, "task": args.task}, ensure_ascii=False, indent=2))
        return

    result: dict[str, object] = place_call(
        api_key=api_key, phone_number=phone, task=args.task
    )
    call_id: object = result.get("call_id", "unknown")
    status: object = result.get("status", result.get("message", "unknown"))
    print(json.dumps({"call_id": call_id, "status": status, "raw": result}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
