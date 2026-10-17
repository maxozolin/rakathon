"""Tests for the MCP packaging layer (avicenna_mcp): catalog search, registry packs, probability,
screening into excluded / can_apply, skills and the MCP server surface.

Everything runs on a small synthetic catalog — no registry snapshots needed.
"""

import asyncio
import copy
import json
import re
import sqlite3
from pathlib import Path

import pytest

from avicenna_matcher.errors import StructuralError
from avicenna_mcp import catalog as cat
from avicenna_mcp import config
from avicenna_mcp.packs import (MAX_AGE_CRITERION_ID, MIN_AGE_CRITERION_ID, SEX_CRITERION_ID,
                                UNPUBLISHED_CRITERION_ID, PackStore, check_pack, registry_pack, resolve_pack)
from avicenna_mcp.patient import patient_profile
from avicenna_mcp.screening import Screener, check_packet, load_packet

SKILLS = config.MATCHER_DIR / "skills"
EXAMPLE_PACKET = SKILLS / "patient-data-format" / "example_packet.json"
EXAMPLE_PACK = SKILLS / "trial-data-format" / "example_pack.json"
CURATED_DIR = config.MATCHER_DIR / "packs"

MOTOL = {"org": "Fakultni nemocnice v Motole", "city": "Praha", "country": "Czechia"}
BRNO = {"org": "Masarykuv onkologicky ustav", "city": "Brno", "country": "Czechia"}


def _row(trial_id, **kw):
    r = {
        "trial_id": trial_id, "registry": "ctgov", "title": f"Study {trial_id}", "short_title": None,
        "status": "RECRUITING", "status_detail": "recruiting", "available": 1, "recruiting": 1,
        "phase": "PHASE3", "study_type": "interventional", "conditions": [], "sex": "all",
        "min_age_years": 18.0, "max_age_years": None, "age_groups": None, "sites": [MOTOL],
        "inclusion": ["Histologically confirmed disease"], "exclusion": ["Active infection"],
        "products": None, "sponsor": "Sponsor", "linked_ids": [], "url": None, "last_update": "2026-01-01",
    }
    r.update(kw)
    r["geo_rank"], r["best_site"] = cat.geo_rank(r["sites"])
    return r


ROWS = [
    # The curated example trial (KRAS G12C colorectal), Motol.
    _row("NCT06252649", title="Sotorasib, Panitumumab and FOLFIRI in Metastatic Colorectal Cancer With KRAS G12C",
         conditions=["Metastatic Colorectal Cancer"], products="sotorasib panitumumab"),
    # Same trial in CTIS — must be deduplicated in search and reuse the curated pack.
    _row("2023-000001-11-00", registry="ctis", title="CodeBreaK 301 colorectal", conditions=["colorectal cancer"],
         linked_ids=["NCT06252649"], min_age_years=None, age_groups="18-64 years"),
    # Colorectal trial that excludes the 66-year-old example patient by structured age.
    _row("NCT00000070", title="Young-onset colon cancer", conditions=["Colon Cancer"], max_age_years=50.0,
         sites=[BRNO]),
    # Female-only colorectal trial: sex is `partial`, never excludes, but is penalised.
    _row("NCT00000071", title="Colorectal cancer in women", conditions=["Colorectal Cancer"], sex="female"),
    # Not available: never returned by default.
    _row("NCT00000072", title="Closed colorectal study", conditions=["Colorectal Cancer"], available=0,
         recruiting=0, status="ACTIVE_NOT_RECRUITING"),
    # Unrelated, with diacritics.
    _row("NCT00000073", title="Karcinom prsu – léčba", conditions=["Breast Cancer"], inclusion=[], exclusion=[]),
]


@pytest.fixture
def catalog(tmp_path):
    path = tmp_path / "catalog.sqlite"
    con = sqlite3.connect(path)
    con.executescript(cat._SCHEMA)
    for r in ROWS:
        cat._insert(con, r)
    con.executemany("INSERT INTO meta VALUES (?, ?)", [("catalog_version", cat.CATALOG_VERSION), ("count_ctgov", "5")])
    con.commit()
    con.close()
    c = cat.TrialCatalog(path, auto_build=False)
    yield c
    c.close()


@pytest.fixture
def store():
    return PackStore(CURATED_DIR)


@pytest.fixture
def packet():
    return load_packet(packet_path=str(EXAMPLE_PACKET))


# ------------------------------------------------------------------ catalog helpers

def test_parse_ctgov_age():
    assert cat.parse_ctgov_age("18 Years") == 18.0
    assert cat.parse_ctgov_age("6 Months") == 0.5
    assert cat.parse_ctgov_age("N/A") is None
    assert cat.parse_ctgov_age(None) is None


def test_parse_ctis_age_groups():
    assert cat.parse_ctis_age_groups("18-64 years, 65+ years") == (18.0, None)
    assert cat.parse_ctis_age_groups("18-64 years") == (18.0, 64.0)
    assert cat.parse_ctis_age_groups("adults") == (None, None)


def test_geo_rank_prefers_motol():
    assert cat.geo_rank([BRNO, MOTOL]) == (1, "Fakultni nemocnice v Motole, Praha")
    assert cat.site_rank({"org": "X", "city": "Wien", "country": "Austria"}) == 5


def test_split_eligibility_text_keeps_verbatim_bullets():
    text = """Inclusion Criteria:

  * Age >= 18
  * ECOG 0-1
      * sub-point stays with its parent
Exclusion Criteria:

  * Prior sotorasib
    continued line
"""
    inc, exc = cat.split_eligibility_text(text)
    assert inc == ["Age >= 18", "ECOG 0-1 sub-point stays with its parent"]
    assert exc == ["Prior sotorasib continued line"]


# ------------------------------------------------------------------ search

def test_search_and_or_and_availability(catalog):
    hits = catalog.search("colorectal kras")
    assert [r["trial_id"] for r in hits["results"]] == ["NCT06252649"]
    assert hits["query_used"]["mode"] == "and"
    ids = {r["trial_id"] for r in catalog.search("colorectal colon", mode="or", limit=50)["results"]}
    assert {"NCT06252649", "NCT00000070", "NCT00000071"} <= ids
    assert "NCT00000072" not in ids  # not available
    assert "2023-000001-11-00" not in ids  # deduplicated against its linked NCT
    all_ids = {r["trial_id"] for r in catalog.search("colorectal", available_only=False, limit=50)["results"]}
    assert "NCT00000072" in all_ids


def test_search_auto_falls_back_to_or(catalog):
    hits = catalog.search("colon nonexistentword")
    assert hits["query_used"]["mode"] == "or"
    assert hits["total"] >= 1


def test_search_is_diacritics_insensitive_and_filters(catalog):
    assert [r["trial_id"] for r in catalog.search("lecba")["results"]] == ["NCT00000073"]
    ids = {r["trial_id"] for r in catalog.search("colorectal colon", mode="or", patient_age=66)["results"]}
    assert "NCT00000070" not in ids
    ids = {r["trial_id"] for r in catalog.search("colorectal", patient_sex="male")["results"]}
    assert "NCT00000071" not in ids
    assert all(r["geo_rank"] <= 2 for r in catalog.search(None, max_geo_rank=2, limit=50)["results"])


# ------------------------------------------------------------------ packs

def test_registry_pack_is_valid_and_conservative(catalog):
    for tid in ("NCT00000070", "NCT00000071", "2023-000001-11-00", "NCT00000073"):
        pk = registry_pack(catalog.get(tid))
        check_pack(pk)
        assert pk["criteria_completeness"] == "partial"
    by_id = {c["criterion_id"]: c for c in registry_pack(catalog.get("NCT00000070"))["criteria"]}
    assert by_id[MAX_AGE_CRITERION_ID]["completeness_note"] == "complete"
    assert by_id["exc:registry-1"]["completeness_note"] == "opaque_text"
    ctis = {c["criterion_id"]: c for c in registry_pack(catalog.get("2023-000001-11-00"))["criteria"]}
    assert all(ctis[c]["completeness_note"] == "partial" for c in ctis if c in (MIN_AGE_CRITERION_ID, MAX_AGE_CRITERION_ID))
    female = {c["criterion_id"]: c for c in registry_pack(catalog.get("NCT00000071"))["criteria"]}
    assert female[SEX_CRITERION_ID]["completeness_note"] == "partial"
    empty = {c["criterion_id"] for c in registry_pack(catalog.get("NCT00000073"))["criteria"]}
    assert UNPUBLISHED_CRITERION_ID in empty


def test_registry_pack_is_deterministic(catalog):
    t = catalog.get("NCT00000070")
    assert registry_pack(t) == registry_pack(copy.deepcopy(t))


def test_resolve_pack_prefers_curated_and_linked(catalog, store):
    assert resolve_pack(catalog.get("NCT06252649"), "NCT06252649", store)[1] == "curated"
    assert resolve_pack(catalog.get("2023-000001-11-00"), "2023-000001-11-00", store)[1] == "curated_linked"
    assert resolve_pack(catalog.get("NCT00000070"), "NCT00000070", store)[1] == "registry"
    assert resolve_pack(None, "NCT99999999", store) == (None, "none")


def test_pack_store_rejects_unsafe_ids_and_overwrite(tmp_path):
    st = PackStore(tmp_path)
    pk = json.loads(EXAMPLE_PACK.read_text())
    st.save(pk)
    with pytest.raises(FileExistsError):
        st.save(pk)
    st.save(pk, overwrite=True)
    with pytest.raises(ValueError):
        st.path_for("../evil")
    bad = copy.deepcopy(pk)
    bad["criteria"][0]["unexpected"] = 1
    with pytest.raises(StructuralError):
        st.save(bad, overwrite=True)


# ------------------------------------------------------------------ screening & probability

def test_screen_splits_excluded_and_can_apply(catalog, store, packet):
    out = Screener(catalog, store).screen(packet, limit=50)
    assert out["search"]["derived_from_diagnosis"] is True
    can = {s["trial_id"]: s for s in out["can_apply"]}
    exc = {s["trial_id"]: s for s in out["excluded"]}
    assert "NCT00000070" in exc  # max age 50 vs 66
    assert exc["NCT00000070"]["probability"] == 0.0
    assert any(e["criterion_id"] == MAX_AGE_CRITERION_ID for e in exc["NCT00000070"]["excluded_by"])
    assert "NCT06252649" in can and can["NCT06252649"]["pack_source"] == "curated"
    assert can["NCT06252649"]["eligibility_state"] != "ineligible"
    # Sex is never a hard exclusion from registry data, but the mismatch is heavily penalised.
    assert can["NCT00000071"]["probability"] < 0.1
    probs = [s["probability"] for s in out["can_apply"]]
    assert probs == sorted(probs, reverse=True)
    assert out["counts"]["evaluated"] == len(can) + len(exc)
    assert "heuristic" in out["disclaimer"].lower()


def test_screen_explicit_trial_ids_and_min_probability(catalog, store, packet):
    out = Screener(catalog, store).screen(packet, trial_ids=["NCT00000071", "NCT99999999"], min_probability=0.2)
    assert out["can_apply"] == []
    assert out["errors"] == [{"trial_id": "NCT99999999", "error": "unknown trial"}]


def test_match_detail_and_probability_bounds(catalog, store, packet):
    m = Screener(catalog, store).match(packet, "NCT06252649", include_full_result=True)
    assert m["trial_result"]["trial_eligibility_state"] == m["eligibility_state"]
    pd = m["probability_detail"]
    assert 0.0 < pd["probability"] <= 0.95
    assert pd["confidence"] in ("low", "medium", "high")
    assert Screener(catalog, store).match(packet, "NCT00000070")["probability"] == 0.0
    with pytest.raises(KeyError):
        Screener(catalog, store).match(packet, "NCT99999999")


def test_screen_rejects_defective_packet(catalog, store, packet):
    bad = copy.deepcopy(packet)
    bad["facts"][0]["unexpected"] = True
    with pytest.raises(StructuralError):
        Screener(catalog, store).screen(bad)


def test_patient_profile(packet):
    p = patient_profile(packet)
    assert p["age"] == 66 and p["gender"] == "male"
    assert p["icd10"] == ["C18.7"] and "colorectal" in p["diagnosis_terms"]


# ------------------------------------------------------------------ skills

def _frontmatter(path: Path) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    assert m, f"{path} has no frontmatter"
    return dict(l.split(":", 1) for l in m.group(1).splitlines() if ":" in l and not l.startswith(" "))


@pytest.mark.parametrize("name", ["patient-data-format", "trial-data-format", "explain-trial-to-patient"])
def test_skill_frontmatter(name):
    fm = _frontmatter(SKILLS / name / "SKILL.md")
    assert fm["name"].strip() == name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
    assert 50 < len(fm["description"].strip()) <= 1024


def test_skill_examples_are_valid():
    summary = check_packet(json.loads(EXAMPLE_PACKET.read_text()))
    assert summary["valid"] and summary["adapter_losses"] == []
    assert check_pack(json.loads(EXAMPLE_PACK.read_text())) == []


def test_curated_packs_are_valid():
    for p in CURATED_DIR.glob("*.json"):
        pk = json.loads(p.read_text())
        assert p.stem == pk["trial_id"]
        check_pack(pk)


# ------------------------------------------------------------------ MCP server

@pytest.fixture
def server(catalog, store):
    pytest.importorskip("mcp")
    from avicenna_mcp.server import Services, create_server
    svc = Services()
    svc._catalog = catalog
    svc.store = store
    return create_server(svc)


def _call(server, name, args):
    return asyncio.run(server.call_tool(name, args))


def test_server_lists_tools_prompts_resources(server):
    tools = {t.name for t in asyncio.run(server.list_tools())}
    assert {"search_trials", "get_trial", "screen_patient", "match_trial", "validate_patient_packet",
            "validate_criteria_pack", "save_criteria_pack", "get_criteria_pack", "get_skill"} <= tools
    prompts = {p.name for p in asyncio.run(server.list_prompts())}
    assert {"patient-data-format", "trial-data-format", "explain-trial-to-patient"} <= prompts
    uris = {str(r.uri) for r in asyncio.run(server.list_resources())}
    assert "avicenna://skills/explain-trial-to-patient" in uris


def test_server_tools_roundtrip(server):
    res = _call(server, "search_trials", {"query": "colorectal kras"})
    assert not res.is_error
    assert res.structured_content["results"][0]["trial_id"] == "NCT06252649"
    res = _call(server, "screen_patient", {"packet_path": str(EXAMPLE_PACKET)})
    assert not res.is_error and "NCT00000070" in {s["trial_id"] for s in res.structured_content["excluded"]}
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="unknown trial"):
        _call(server, "match_trial", {"trial_id": "NCT99999999", "packet_path": str(EXAMPLE_PACKET)})
    res = _call(server, "validate_criteria_pack", {"pack": {"schema_version": "x"}})
    assert res.structured_content["valid"] is False
