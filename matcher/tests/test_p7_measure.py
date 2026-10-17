"""P7 — corpus measurement harness (tools/measure.py).

Synthetic inputs only: hand-written criterion strings, throw-away SQLite catalogs built in
tmp_path, and the SYNTHETIC packs in tools/sample_packs. Oracles come from MATCHER_DESIGN.md
§5.4 / §8 / §13.7 (which completeness scenario may clear which construct), not from the code.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import measure as m  # noqa: E402

SAMPLES = TOOLS / "sample_packs"


def _pack(name):
    return json.loads((SAMPLES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Part A — splitting and lexical classification
# ---------------------------------------------------------------------------

CTGOV_TEXT = """Inclusion Criteria:

* Age ≥ 18 years
* Adequate organ function:
  * ANC ≥ 1.5 × 10^9/L
  * Creatinine ≤ 1.5 × ULN
* Signed informed consent

Exclusion Criteria:

* History of brain metastases
* Pregnant or breastfeeding
"""


def test_split_ctgov_folds_subitems_and_switches_section():
    items = m.split_ctgov(CTGOV_TEXT)
    assert [k for k, _ in items] == ["inclusion"] * 3 + ["exclusion"] * 2
    assert "ANC" in items[1][1] and "ULN" in items[1][1]       # nested bullets folded into parent
    assert items[3] == ("exclusion", "History of brain metastases")


def test_split_ctgov_ignores_text_before_first_header():
    assert m.split_ctgov("Some preamble\n* stray bullet\n") == []


@pytest.mark.parametrize("kind, text, on, off", [
    ("inclusion", "Serum creatinine ≤ 1.5 × ULN", {"relative_to_reference", "measurement"}, {"absence_condition"}),
    ("inclusion", "Creatinine clearance ≥ 50 mL/min (Cockcroft-Gault)", {"derived_value"}, set()),
    ("inclusion", "No prior treatment with a SERD", {"absence_therapy"}, {"absence_condition"}),
    ("inclusion", "ECOG performance status 0 or 1", {"measurement"}, {"absence_therapy", "absence_condition"}),
    ("inclusion", "Signed informed consent", {"procedural_only"}, {"four_constructs", "opaque_proxy"}),
    ("exclusion", "History of brain metastases", {"absence_condition", "four_constructs"}, {"absence_therapy"}),
    # §5.4: an exclusion is cleared only by proving absence, keyword or not
    ("exclusion", "Has residual tumor after surgery", {"absence_condition"}, set()),
    ("exclusion", "Prior treatment with an anti-PD-1 antibody", {"absence_therapy"}, {"absence_condition"}),
    ("exclusion", "QTcF > 470 ms", {"derived_value", "measurement"}, {"absence_condition", "absence_therapy"}),
    ("exclusion", "For participants in France: persons under guardianship", {"jurisdiction", "guarded"}, set()),
    ("exclusion", "Any condition that in the opinion of the investigator would interfere",
     {"investigator_judgment", "opaque_proxy"}, set()),
    ("inclusion", "AST ≤ 2.5 × ULN unless liver metastases are present", {"guarded", "relative_to_reference"}, set()),
])
def test_classify(kind, text, on, off):
    f = m.classify(kind, text)
    assert {k for k in on if not f[k]} == set(), f
    assert {k for k in off if f[k]} == set(), f


def test_classify_returns_independent_copies():
    a = m.classify("exclusion", "History of stroke")
    a["absence_condition"] = False
    assert m.classify("exclusion", "History of stroke")["absence_condition"] is True


def _trial(*criteria):
    return m.Trial("T", "test", False, list(criteria))


@pytest.mark.parametrize("criteria, atomizer, expected", [
    # §13.7: condition absence (existential) clears from S1 on; therapy-scoped not_exists needs S2
    ([("inclusion", "Age ≥ 18 years"), ("exclusion", "History of stroke")], "optimistic",
     {"S0": "needs_chart_review", "S1": "eligible_pending_review", "S2": "eligible_pending_review"}),
    ([("inclusion", "Age ≥ 18 years"), ("inclusion", "No prior treatment with a SERD")], "optimistic",
     {"S0": "needs_chart_review", "S1": "needs_chart_review", "S2": "eligible_pending_review"}),
    # §8 severity: one un-evaluable hard exclusion → manual_review regardless of completeness
    ([("inclusion", "Age ≥ 18 years"), ("exclusion", "Any illness that in the opinion of the investigator "
                                                    "would interfere")], "optimistic",
     {"S0": "manual_review", "S1": "manual_review", "S2": "manual_review"}),
    ([("inclusion", "Age ≥ 18 years"), ("exclusion", "Any illness that in the opinion of the investigator "
                                                    "would interfere")], "judgment_atomized",
     {"S0": "needs_chart_review", "S1": "eligible_pending_review", "S2": "eligible_pending_review"}),
    # procedural criteria are not hard and never block
    ([("inclusion", "Age ≥ 18 years"), ("inclusion", "Signed informed consent")], "conservative",
     {"S0": "eligible_pending_review", "S1": "eligible_pending_review", "S2": "eligible_pending_review"}),
])
def test_best_case_state_scenarios(criteria, atomizer, expected):
    t = _trial(*criteria)
    assert {sc: m.best_case_state(t, sc, atomizer) for sc in m.SCENARIOS} == expected


def test_best_case_ratio_rule_is_strictly_greater_than_one_third():
    judg = ("inclusion", "Adequate condition as judged by the investigator")
    ok = ("inclusion", "Age ≥ 18 years")
    assert m.best_case_state(_trial(judg, ok, ok), "S2", "optimistic") == "needs_chart_review"   # exactly 1/3
    assert m.best_case_state(_trial(judg, judg, ok), "S2", "optimistic") == "manual_review"     # 2/3


def test_best_case_yield_is_monotone_in_completeness():
    rank = {"eligible_pending_review": 0, "needs_chart_review": 1, "manual_review": 2}
    texts = ["Age ≥ 18 years", "History of stroke", "No prior treatment with a SERD", "Prior anti-PD-1 therapy",
             "Has residual tumor", "Any condition that in the opinion of the investigator would interfere"]
    import itertools
    for combo in itertools.combinations(texts, 3):
        t = _trial(*[("exclusion" if i % 2 else "inclusion", x) for i, x in enumerate(combo)])
        for atz in m.ATOMIZERS:
            r = [rank[m.best_case_state(t, sc, atz)] for sc in m.SCENARIOS]
            assert r == sorted(r, reverse=True), (combo, atz, r)


# ---------------------------------------------------------------------------
# Part A — loaders on throw-away synthetic catalogs
# ---------------------------------------------------------------------------

def _ctis_db(path):
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE trials_retrieve (ct_number TEXT, inclusions_json TEXT, exclusions_json TEXT, "
                  "sites_json TEXT)")
        c.execute("INSERT INTO trials_retrieve VALUES (?,?,?,?)",
                  ("2099-500001-01-00", json.dumps(["Age ≥ 18", "  "]), json.dumps(["History of stroke"]),
                   json.dumps([{"name": "Fakultní nemocnice v MOTOLE"}])))
        c.execute("INSERT INTO trials_retrieve VALUES (?,?,?,?)", ("2099-500002-01-00", None, None, None))


def _ctgov_db(path):
    with sqlite3.connect(path) as c:
        c.execute("CREATE TABLE ctgov_studies (nct_id TEXT, eligibility_text TEXT, motol_related INT, "
                  "homolka_related INT)")
        c.execute("INSERT INTO ctgov_studies VALUES (?,?,?,?)", ("NCT99999999", CTGOV_TEXT, 0, 1))


def test_loaders_on_synthetic_catalogs(tmp_path):
    _ctis_db(tmp_path / "ctis.sqlite")
    _ctgov_db(tmp_path / "ctgov.sqlite")
    ctis = m.load_ctis(str(tmp_path / "ctis.sqlite"))
    assert [(t.trial_id, t.priority, t.criteria) for t in ctis] == [
        ("2099-500001-01-00", True, [("inclusion", "Age ≥ 18"), ("exclusion", "History of stroke")]),
        ("2099-500002-01-00", False, [])]
    ctgov = m.load_ctgov(str(tmp_path / "ctgov.sqlite"))
    assert ctgov[0].priority is True and len(ctgov[0].criteria) == 5
    s = m.corpus_stats(ctis + ctgov)
    assert (s["trials"], s["trials_with_criteria"], s["priority"]) == (3, 2, 2)
    assert s["total"]["n"] == 7


def test_loaders_open_read_only(tmp_path):
    _ctis_db(tmp_path / "ctis.sqlite")
    with pytest.raises(sqlite3.OperationalError):
        with m._ro(str(tmp_path / "ctis.sqlite")) as c:
            c.execute("DELETE FROM trials_retrieve")


@pytest.mark.parametrize("fn", ["load_ctis", "load_ctgov", "load_packs"])
def test_refuses_patient_data_paths(tmp_path, fn):
    bad = tmp_path / "data" / "rakathon-dataset" / "x.sqlite"
    with pytest.raises(SystemExit, match="patient data"):
        getattr(m, fn)(str(bad))


def test_measure_source_never_names_a_patient_data_location():
    src = (TOOLS / "measure.py").read_text(encoding="utf-8")
    assert src.count("rakathon-dataset") == 1      # only inside the refusal guard
    for banned in ("socket", "urllib", "requests", "datetime.now", "uuid", "random"):
        assert banned not in src


# ---------------------------------------------------------------------------
# Part B — synthetic witness through the real pipeline
# ---------------------------------------------------------------------------

def test_sample_packs_are_valid_and_marked_synthetic():
    packs = m.load_packs(str(SAMPLES))
    assert len(packs) >= 4
    assert all("SYNTH" in p["trial_id"] and "SYNTHETIC" in p["pack_id"] for p in packs)


@pytest.mark.parametrize("name, expected", [
    # not_exists (scoped therapy) + existential exclusion: S1 bare negatives clear only the existential one
    ("synth_onc_not_exists.json",
     {"S0": "needs_chart_review", "S1": "needs_chart_review", "S2": "eligible_pending_review"}),
    ("synth_cz_guard.json",
     {"S0": "needs_chart_review", "S1": "eligible_pending_review", "S2": "eligible_pending_review"}),
    # §8 severity: an opaque hard exclusion pins manual_review whatever the completeness
    ("synth_partial_opaque.json", {"S0": "manual_review", "S1": "manual_review", "S2": "manual_review"}),
    # basket: arms need contradictory HER2 values; per-arm witnesses still find a fitting arm
    ("synth_basket_arms.json",
     {"S0": "eligible_pending_review", "S1": "eligible_pending_review", "S2": "eligible_pending_review"}),
])
def test_measure_pack_scenarios(name, expected):
    r = m.measure_pack(_pack(name))
    assert r["states"] == expected


def test_onc_pack_s1_leaves_exactly_the_scoped_not_exists_unresolved():
    from avicenna_matcher import pipeline
    pk = _pack("synth_onc_not_exists.json")
    w, failed = m.build_witness(pk, "main")
    assert failed == []
    r = pipeline.evaluate(pk, m._packet(w.facts("S1")), None, result_id="t", generated_at=m.ANCHOR)
    unresolved = {c["criterion_id"]: c["reason_code"] for c in r["criterion_results"] if c["outcome"] == "unresolved"}
    assert unresolved == {"inc:no-serd": "absence_not_established"}


def test_witness_is_a_genuine_best_case():
    """Every witness fact must make its criterion pass when evaluable — S2 leaves nothing unresolved
    except criteria the harness reports as having no witness."""
    from avicenna_matcher import pipeline
    for pk in m.load_packs(str(SAMPLES)):
        for arm in pk["arms"]:
            w, failed = m.build_witness(pk, arm["arm_id"])
            r = pipeline.evaluate(pk, m._packet(w.facts("S2")), {"site_context": w.site} if w.site else None,
                                  result_id="t", generated_at=m.ANCHOR)
            scope = {c["criterion_id"]: c["arm_scope"] for c in pk["criteria"]}
            mine = [c for c in r["criterion_results"] if c["hardness"] == "hard" and c["applicable"]
                    and c["criterion_id"] not in failed and scope[c["criterion_id"]] in (None, arm["arm_id"])]
            assert mine
            for c in mine:
                if c["outcome"] == "unresolved":
                    # only §6 partial-atomization downgrade may keep a witnessed criterion open
                    assert pk["criteria_completeness"] == "partial", c
                    assert c["reason_code"] == "partial_atomization", c
                else:
                    assert c["outcome"] in ("satisfied", "clear"), c


def test_partial_pack_reports_forced_complete_variant():
    r = m.measure_pack(_pack("synth_partial_opaque.json"))
    assert r["no_witness"] == ["exc:judg"]
    assert set(r["forced_complete"]) == set(m.SCENARIOS)


def test_witness_conflict_is_reported_not_hidden():
    w = m.Witness()
    w._num("lab.x", "U", "ge", 10)
    with pytest.raises(m.WitnessFail):
        w._num("lab.x", "U", "lt", 5)
    with pytest.raises(m.WitnessFail):
        w._absent("lab.x", None)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def test_render_is_deterministic_and_answers_both_questions(tmp_path):
    _ctis_db(tmp_path / "ctis.sqlite")
    argv = ["--ctis", str(tmp_path / "ctis.sqlite"), "--packs", str(SAMPLES)]
    m.main(argv + ["-o", str(tmp_path / "a.md")])
    m.main(argv + ["-o", str(tmp_path / "b.md")])
    a = (tmp_path / "a.md").read_bytes()
    assert a == (tmp_path / "b.md").read_bytes()
    text = a.decode()
    assert "§10.2" in text and "§13.7" in text and "PROXY" in text
    assert "SYNTH-P7-ONC" in text
