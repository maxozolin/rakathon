"""Avicenna MCP: the deterministic matcher packaged as a Model Context Protocol server.

Layers (each usable without the MCP runtime):
- `catalog`     — local full-text index over the CT.gov + CTIS registry snapshots.
- `packs`       — curated CriteriaPack store + registry-derived (auto) packs.
- `probability` — transparent, uncalibrated enrollment-likelihood heuristic (a separate axis;
                  never replaces the matcher's eligibility_state).
- `screening`   — search → evaluate → {excluded, can_apply}.
- `server`      — MCP tools, prompts (skills) and resources.
"""

__version__ = "0.1.0"
