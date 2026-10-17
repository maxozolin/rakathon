"""CLI: CriteriaPack JSON + patient packet JSON (+ context JSON) → trial_result JSON.

    avicenna-matcher PACK PACKET [--context CTX] --generated-at TS [--result-id ID]

No clock and no RNG: `--generated-at` is required, and `--result-id` defaults to a
content hash of the canonical inputs, so identical inputs yield byte-identical output.
Structural errors exit 2 with a JSON error object on stderr; nothing is written to stdout.
Patient content is never echoed in error messages beyond the validator's message.
"""

import argparse
import hashlib
import json
import sys
from typing import List, Optional

from . import pipeline
from .errors import StructuralError


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def derive_result_id(pack: dict, packet: dict, context: Optional[dict], generated_at: str) -> str:
    h = hashlib.sha256()
    for part in (pack, packet, context, generated_at):
        h.update(_canonical(part).encode("utf-8"))
        h.update(b"\x00")
    return "res-" + h.hexdigest()[:32]


def run_matcher(
    pack: dict,
    packet: dict,
    context: Optional[dict] = None,
    *,
    generated_at: str,
    result_id: Optional[str] = None,
) -> str:
    """Evaluate and return the canonical JSON serialization of the trial_result."""
    if result_id is None:
        result_id = derive_result_id(pack, packet, context, generated_at)
    result = pipeline.evaluate(pack, packet, context, result_id=result_id, generated_at=generated_at)
    return json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False) + "\n"


def _load(path: str):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="avicenna-matcher", description=__doc__.splitlines()[0])
    ap.add_argument("pack")
    ap.add_argument("packet")
    ap.add_argument("--context")
    ap.add_argument("--generated-at", required=True,
                    help="output timestamp (injected; the matcher never reads a clock)")
    ap.add_argument("--result-id")
    ap.add_argument("-o", "--output", help="write to file instead of stdout")
    args = ap.parse_args(argv)

    try:
        pack, packet = _load(args.pack), _load(args.packet)
        context = _load(args.context) if args.context else None
        out = run_matcher(pack, packet, context,
                          generated_at=args.generated_at, result_id=args.result_id)
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(json.dumps({"error": "input_error", "message": str(e)}) + "\n")
        return 2
    except StructuralError as e:
        sys.stderr.write(json.dumps({"error": "structural_error", "type": type(e).__name__,
                                     "message": str(e)}) + "\n")
        return 2

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
