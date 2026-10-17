"""Avicenna trial-matching MCP server.

Tools wrap the trial catalog (search), the criteria-pack store and the deterministic matcher; the
eligibility verdict always comes from `avicenna_matcher`, the probability from the separate heuristic in
`avicenna_mcp.probability`. Skills (data-format and patient-explanation guidance) are exposed as
prompts and resources.

Run: `avicenna-mcp` (stdio). Utilities: `avicenna-mcp build-catalog | search | screen | match`.
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import sys
import threading
from pathlib import Path
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import Field

from avicenna_matcher.validator import StructuralError

from . import __version__, config
from .catalog import TrialCatalog, build_catalog
from .packs import PackStore, check_pack, resolve_pack
from .probability import DISCLAIMER, MODEL_VERSION
from .screening import Screener, check_packet, load_packet

SERVER_NAME = "avicenna-trials"

INSTRUCTIONS = f"""\
Avicenna clinical-trial matching for Czech oncology patients (CT.gov + CTIS trials with Czech sites).

Typical flow:
1. Patient data must be an avicenna.patient-packet (skill `patient-data-format`); check it with
   validate_patient_packet.
2. search_trials finds currently available trials (free text, filters, Prague-first ordering).
3. screen_patient reuses that search and evaluates every hit with the deterministic matcher, returning
   `excluded` (a hard criterion is resolved against the patient) and `can_apply` (not ruled out) with a
   heuristic probability. match_trial does the same for one trial with full detail.
4. To present a trial to a patient follow the skill `explain-trial-to-patient`.
5. To improve a trial's evaluation, curate a criteria pack (skill `trial-data-format`) and save it with
   save_criteria_pack.

Rules: `eligibility_state` is the authoritative matcher verdict; there is no plain "eligible" — the
study team always confirms. {DISCLAIMER} Patient packets must be pseudonymous; never put names or
national IDs into tool calls.
"""

PROMPT_DOCS = {
    "trial-pack-builder": "TRIAL_PACK_BUILDER_PROMPT.md",
    "patient-packet-builder": "PATIENT_PACKET_BUILDER_PROMPT.md",
}
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

PacketArg = Annotated[Optional[Dict[str, Any]], Field(
    description="Patient packet JSON (avicenna.patient-packet/1.1.0 or internal 0.1); see skill patient-data-format")]
PacketPathArg = Annotated[Optional[str], Field(description="Path to a packet JSON file readable by the server (alternative to `packet`)")]
ContextArg = Annotated[Optional[Dict[str, Any]], Field(
    description="Optional evaluation context: anchor, mode, site_context, screening_recency_days, policy_version")]



# --------------------------------------------------------------------------------------------- state

class Services:
    """Lazily opened catalog + pack store, shared by all tool calls."""

    def __init__(self) -> None:
        self._catalog: Optional[TrialCatalog] = None
        self._lock = threading.Lock()
        self.store = PackStore()

    @property
    def catalog(self) -> TrialCatalog:
        with self._lock:
            if self._catalog is None:
                self._catalog = TrialCatalog()
            return self._catalog

    @property
    def screener(self) -> Screener:
        return Screener(self.catalog, self.store)

    def rebuild(self) -> dict[str, Any]:
        with self._lock:
            if self._catalog is not None:
                self._catalog.close()
                self._catalog = None
            build_catalog(config.catalog_db())
        return self.catalog.meta()

    def warm_up(self) -> None:
        def run():
            try:
                _ = self.catalog
            except Exception as e:  # reported again on first real use
                print(f"[avicenna-mcp] catalog warm-up failed: {e}", file=sys.stderr)
        threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------------------------- skills

def _frontmatter(text: str) -> Dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    out: Dict[str, str] = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip().strip('"')
    return out


def list_skills() -> List[Dict[str, Any]]:
    out = []
    root = config.skills_dir()
    for p in sorted(root.glob("*/SKILL.md")) if root.exists() else []:
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        files = sorted(f.name for f in p.parent.iterdir() if f.is_file() and f.name != "SKILL.md")
        out.append({"name": fm.get("name", p.parent.name), "description": fm.get("description", ""),
                    "files": files, "uri": f"avicenna://skills/{p.parent.name}"})
    return out


def read_skill(name: str, file: Optional[str] = None) -> str:
    if not _NAME_RE.match(name):
        raise ValueError(f"invalid skill name {name!r}")
    d = config.skills_dir() / name
    target = d / (file or "SKILL.md")
    if file is not None and (Path(file).name != file or not target.is_file()):
        raise ValueError(f"unknown file {file!r} in skill {name!r}")
    if not target.is_file():
        raise ValueError(f"unknown skill {name!r}; available: {[s['name'] for s in list_skills()]}")
    return target.read_text(encoding="utf-8")


def _read_schema(name: str) -> str:
    if not _NAME_RE.match(name.replace("_", "-").replace(".", "-")):
        raise ValueError(f"invalid schema name {name!r}")
    for cand in (f"{name}.schema.json", f"{name}.json", name):
        p = config.schemas_dir() / cand
        if p.is_file():
            return p.read_text(encoding="utf-8")
    raise ValueError(f"unknown schema {name!r}; available: {sorted(p.name for p in config.schemas_dir().glob('*.json'))}")


# --------------------------------------------------------------------------------------------- server

def _packet(packet: Optional[Dict[str, Any]], packet_path: Optional[str]) -> dict:
    try:
        return load_packet(packet, packet_path)
    except (OSError, ValueError) as e:
        raise ValueError(f"could not load the patient packet: {e}") from e


def _user_errors(fn):
    """Report expected failures (bad input, unknown ids, invalid packs/packets) to the client as ToolError."""
    from mcp.server.mcpserver.exceptions import ToolError

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, KeyError, FileNotFoundError, FileExistsError, StructuralError) as e:
            raise ToolError(str(e.args[0]) if isinstance(e, KeyError) and e.args else str(e)) from e
    return wrapper


def create_server(services: Optional[Services] = None) -> Any:
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    svc = services or Services()
    server = MCPServer(SERVER_NAME, instructions=INSTRUCTIONS, version=__version__)
    _tool = server.tool

    def tool(**kw):
        def deco(fn):
            return _tool(**kw)(_user_errors(fn))
        return deco
    server_tool = tool
    ro = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)

    # ---- search & catalog

    @server_tool(name="search_trials", annotations=ro, description=(
        "Search the currently available clinical trials (CT.gov + EU CTIS, Czech sites). Free-text over title, "
        "conditions, products and criteria; diacritics-insensitive; Prague/Motol first by default. Returns "
        "summaries; use get_trial for criteria."))
    def search_trials(
        query: Annotated[Optional[str], Field(description="Words, e.g. 'colorectal KRAS G12C'. Empty = browse.")] = None,
        recruiting_only: Annotated[bool, Field(description="Only trials actively recruiting now")] = False,
        include_unavailable: Annotated[bool, Field(description="Also return closed/active-not-recruiting trials")] = False,
        registry: Annotated[Optional[Literal["ctgov", "ctis"]], Field(description="Restrict to one registry")] = None,
        max_geo_rank: Annotated[Optional[int], Field(ge=1, le=5, description="1 Motol/Homolka, 2 Prague, 3 Brno/Ostrava, 4 Czechia, 5 any")] = None,
        phase: Annotated[Optional[str], Field(description="Substring of the phase, e.g. 'PHASE3' or 'Phase II'")] = None,
        patient_age: Annotated[Optional[float], Field(description="Drop trials whose structured age range excludes this age")] = None,
        patient_sex: Annotated[Optional[Literal["female", "male"]], Field(description="Drop single-sex trials of the other sex")] = None,
        sort: Literal["geo", "relevance"] = "geo",
        match: Annotated[Literal["auto", "and", "or"], Field(description="all words / any word / all-then-any")] = "auto",
        limit: Annotated[int, Field(ge=1, le=200)] = 20,
        offset: Annotated[int, Field(ge=0)] = 0,
    ) -> dict[str, Any]:
        return svc.catalog.search(query, available_only=not include_unavailable, recruiting_only=recruiting_only,
                                  registry=registry, max_geo_rank=max_geo_rank, phase=phase,
                                  patient_age=patient_age, patient_sex=patient_sex, sort=sort, limit=limit,
                                  offset=offset, mode=match)

    @server_tool(name="get_trial", annotations=ro, description=(
        "Full public record of one trial: sites, status, phase, products, verbatim inclusion/exclusion criteria, "
        "linked registry ids, and whether a curated criteria pack exists."))
    def get_trial(trial_id: Annotated[str, Field(description="NCT number or EU CT number")]) -> dict[str, Any]:
        t = svc.catalog.get(trial_id.strip())
        if t is None:
            raise ValueError(f"unknown trial {trial_id!r}")
        _, source = resolve_pack(t, t["trial_id"], svc.store)
        t["criteria_pack_source"] = source
        return t

    @server_tool(name="catalog_info", description=(
        "Catalog build metadata and counts. rebuild=true re-imports the CT.gov/CTIS snapshots (~1 min)."),
        annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, openWorldHint=False))
    def catalog_info(rebuild: bool = False) -> dict[str, Any]:
        meta = svc.rebuild() if rebuild else svc.catalog.meta()
        return {"catalog": meta, "catalog_path": str(config.catalog_db()), "packs_dir": str(config.packs_dir()),
                "curated_packs": len(svc.store.list()), "probability_model": MODEL_VERSION,
                "server_version": __version__}

    # ---- matching

    @server_tool(name="screen_patient", annotations=ro, description=(
        "Search available trials for a patient and sort them into `excluded` (a hard criterion is resolved "
        "against the patient — reasons included) and `can_apply` (not ruled out), each with eligibility_state "
        "and a heuristic probability (sorted high→low). Without `query`, searches by the packet's diagnosis. "
        "Pass `trial_ids` to screen specific trials instead of searching."))
    def screen_patient(
        packet: PacketArg = None,
        packet_path: PacketPathArg = None,
        query: Annotated[Optional[str], Field(description="Search text; default = terms from the ICD-10 diagnosis")] = None,
        trial_ids: Annotated[Optional[List[str]], Field(description="Screen exactly these trials (skips search)")] = None,
        recruiting_only: bool = False,
        registry: Optional[Literal["ctgov", "ctis"]] = None,
        max_geo_rank: Annotated[Optional[int], Field(ge=1, le=5)] = None,
        phase: Optional[str] = None,
        min_probability: Annotated[float, Field(ge=0, le=1, description="Hide can_apply trials below this")] = 0.0,
        limit: Annotated[int, Field(ge=1, le=200, description="Max trials taken from the search")] = 30,
        context: ContextArg = None,
    ) -> dict[str, Any]:
        pk = _packet(packet, packet_path)
        try:
            return svc.screener.screen(pk, query, context=context, trial_ids=trial_ids,
                                       recruiting_only=recruiting_only, max_geo_rank=max_geo_rank,
                                       registry=registry, phase=phase, limit=limit,
                                       min_probability=min_probability)
        except StructuralError as e:
            raise ValueError(f"patient packet rejected: {e}") from e

    @server_tool(name="match_trial", annotations=ro, description=(
        "Evaluate one patient against one trial: eligibility_state, criteria met / disqualifying / still to "
        "check (verbatim criterion text and fact ids), probability with its factors. include_full_result adds "
        "the matcher's audit-grade TrialResult."))
    def match_trial(
        trial_id: str,
        packet: PacketArg = None,
        packet_path: PacketPathArg = None,
        include_full_result: bool = False,
        context: ContextArg = None,
    ) -> dict[str, Any]:
        pk = _packet(packet, packet_path)
        try:
            check_packet(pk, context)
        except StructuralError as e:
            raise ValueError(f"patient packet rejected: {e}") from e
        try:
            return svc.screener.match(pk, trial_id.strip(), context, include_full_result=include_full_result)
        except KeyError as e:
            raise ValueError(str(e.args[0])) from e
        except StructuralError as e:
            raise ValueError(f"criteria pack for {trial_id} is invalid: {e}") from e

    @server_tool(name="validate_patient_packet", annotations=ro, description=(
        "Validate a patient packet (canonical 1.1.0 or internal 0.1) and report what the matcher will see: "
        "fact count, adapter losses, assessed/unassessed fact keys, anchor, mode."))
    def validate_patient_packet(packet: PacketArg = None, packet_path: PacketPathArg = None,
                                context: ContextArg = None) -> dict[str, Any]:
        pk = _packet(packet, packet_path)
        try:
            return check_packet(pk, context)
        except StructuralError as e:
            return {"valid": False, "error": str(e)}

    # ---- criteria packs

    @server_tool(name="get_criteria_pack", annotations=ro, description=(
        "The criteria pack used for a trial: curated if one exists, otherwise the automatic registry pack "
        "(age/sex structured, every bullet verbatim and opaque) — a starting point for curation."))
    def get_criteria_pack(trial_id: str) -> dict[str, Any]:
        tid = trial_id.strip()
        pack, source = resolve_pack(svc.catalog.get(tid), tid, svc.store)
        if pack is None:
            raise ValueError(f"unknown trial {trial_id!r}")
        return {"source": source, "pack": pack}

    @server_tool(name="validate_criteria_pack", annotations=ro, description=(
        "Check a criteria pack against the schema and the matcher's structural rules (see skill trial-data-format)."))
    def validate_criteria_pack(pack: Dict[str, Any]) -> dict[str, Any]:
        try:
            warnings = check_pack(pack)
        except StructuralError as e:
            return {"valid": False, "error": str(e)}
        return {"valid": True, "warnings": warnings, "n_criteria": len(pack.get("criteria") or [])}

    @server_tool(name="save_criteria_pack", description=(
        "Validate and store a curated criteria pack; future screenings of that trial (and of its linked "
        "registry record) use it instead of the registry pack."),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False))
    def save_criteria_pack(pack: Dict[str, Any],
                           overwrite: Annotated[bool, Field(description="Replace an existing curated pack")] = False
                           ) -> dict[str, Any]:
        try:
            path, warnings = svc.store.save(pack, overwrite=overwrite)
        except StructuralError as e:
            raise ValueError(f"pack rejected: {e}") from e
        except (FileExistsError, KeyError, ValueError) as e:
            raise ValueError(str(e)) from e
        return {"saved": str(path), "trial_id": pack["trial_id"], "warnings": warnings}

    @server_tool(name="list_curated_packs", annotations=ro, description="Curated criteria packs on disk.")
    def list_curated_packs() -> dict[str, Any]:
        return {"packs_dir": str(svc.store.dir), "packs": svc.store.list()}

    # ---- skills (for clients without native skill support)

    @server_tool(name="list_skills", annotations=ro, description="Skills shipped with this server (guidance documents).")
    def list_skills_tool() -> dict[str, Any]:
        return {"skills": list_skills()}

    @server_tool(name="get_skill", annotations=ro, description=(
        "Read a skill: patient-data-format, trial-data-format, explain-trial-to-patient. `file` reads an "
        "attached example (e.g. example_packet.json)."))
    def get_skill(name: str, file: Optional[str] = None) -> str:
        return read_skill(name, file)

    # ---- resources

    for s in list_skills():
        _add_skill_resource(server, s)

    @server.resource("avicenna://schemas/{name}", name="schema", mime_type="application/json",
                     description="JSON Schemas: criteria_pack, patient_packet, trial_result, criterion_result, reason_codes.registry")
    def schema_resource(name: str) -> str:
        return _read_schema(name)

    @server.resource("avicenna://docs/{name}", name="builder-prompt", mime_type="text/markdown",
                     description="Normative builder prompts: trial-pack-builder, patient-packet-builder")
    def doc_resource(name: str) -> str:
        if name not in PROMPT_DOCS:
            raise ValueError(f"unknown doc {name!r}; available: {sorted(PROMPT_DOCS)}")
        return (config.prompts_dir() / PROMPT_DOCS[name]).read_text(encoding="utf-8")

    # ---- prompts

    @server.prompt(name="patient-data-format", description="How to build/check a patient packet for the matcher")
    def p_patient(task: str = "Check that the patient data is in the right format.") -> str:
        return f"{read_skill('patient-data-format')}\n\n---\nTask: {task}"

    @server.prompt(name="trial-data-format", description="How to atomize a trial into a criteria pack")
    def p_trial(trial_id: str = "") -> str:
        task = (f"Curate a criteria pack for {trial_id}: call get_trial and get_criteria_pack, atomize, "
                "validate_criteria_pack, then save_criteria_pack.") if trial_id else "Explain the trial data format."
        return f"{read_skill('trial-data-format')}\n\n---\nTask: {task}"

    @server.prompt(name="explain-trial-to-patient", description="Explain a trial and the match result to a patient")
    def p_explain(trial_id: str, language: str = "cs", packet_path: str = "") -> str:
        how = (f"Call get_trial('{trial_id}')" + (f" and match_trial('{trial_id}', packet_path='{packet_path}')"
                                                 if packet_path else ""))
        return (f"{read_skill('explain-trial-to-patient')}\n\n---\nTask: {how}, then write the patient-facing "
                f"explanation in language '{language}' following the skill above.")

    @server.prompt(name="find-trials-for-patient", description="Screen a patient and summarise which trials fit")
    def p_find(packet_path: str, query: str = "") -> str:
        q = f", query='{query}'" if query else ""
        return (f"1. validate_patient_packet(packet_path='{packet_path}') and report any adapter losses.\n"
                f"2. screen_patient(packet_path='{packet_path}'{q}).\n"
                "3. Summarise for the clinician: top `can_apply` trials (state, probability + confidence, site, the "
                "most important `to_check` items) and the `excluded` trials with the verbatim excluding criterion.\n"
                "4. State that probabilities are heuristic and that the study team confirms eligibility.")

    return server


def _add_skill_resource(server: Any, skill: Dict[str, Any]) -> None:
    dir_name = skill["uri"].rsplit("/", 1)[1]

    def read() -> str:
        return read_skill(dir_name)

    server.resource(skill["uri"], name=f"skill-{dir_name}", mime_type="text/markdown",
                    description=skill["description"][:300])(read)


# --------------------------------------------------------------------------------------------- CLI

def _dump(obj: Any) -> None:
    json.dump(obj, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="avicenna-mcp", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve", help="run the MCP server (default)")
    s.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    s.add_argument("--no-warmup", action="store_true", help="do not open/build the catalog at startup")
    sub.add_parser("build-catalog", help="(re)build the trial catalog index")
    q = sub.add_parser("search", help="search trials")
    q.add_argument("query", nargs="?")
    q.add_argument("--recruiting", action="store_true")
    q.add_argument("--limit", type=int, default=10)
    sc = sub.add_parser("screen", help="screen a patient packet")
    sc.add_argument("packet")
    sc.add_argument("--query")
    sc.add_argument("--limit", type=int, default=30)
    m = sub.add_parser("match", help="match a patient packet against one trial")
    m.add_argument("packet")
    m.add_argument("trial_id")
    args = ap.parse_args(argv)

    if args.cmd in (None, "serve"):
        svc = Services()
        if not getattr(args, "no_warmup", False):
            svc.warm_up()
        create_server(svc).run(getattr(args, "transport", "stdio"))
        return 0
    if args.cmd == "build-catalog":
        _dump(build_catalog(config.catalog_db()))
        return 0
    svc = Services()
    if args.cmd == "search":
        _dump(svc.catalog.search(args.query, recruiting_only=args.recruiting, limit=args.limit))
    elif args.cmd == "screen":
        _dump(svc.screener.screen(load_packet(packet_path=args.packet), args.query, limit=args.limit))
    elif args.cmd == "match":
        _dump(svc.screener.match(load_packet(packet_path=args.packet), args.trial_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
