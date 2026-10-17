"""Minimal, read-only view of a patient packet used for search filters and the probability layer.

It never feeds the matcher: the matcher reads the full packet itself. Only positive, known,
patient-scoped facts are used; anything else is treated as unknown.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# ICD-10 (3-char prefix) → registry search terms. Coarse on purpose: it drives retrieval and a
# relevance check, never eligibility. Unknown codes simply yield no terms.
ICD10_TERMS: Dict[str, List[str]] = {
    **{f"C0{i}": ["head and neck", "oral", "oropharyngeal"] for i in range(0, 10)},
    **{f"C1{i}": ["head and neck", "pharyngeal"] for i in range(0, 5)},
    "C15": ["esophageal", "oesophageal"], "C16": ["gastric", "stomach", "gastroesophageal"],
    "C17": ["small bowel", "small intestine"], "C18": ["colorectal", "colon"], "C19": ["colorectal", "rectal"],
    "C20": ["colorectal", "rectal", "rectum"], "C21": ["anal"], "C22": ["hepatocellular", "liver", "biliary"],
    "C23": ["biliary", "gallbladder"], "C24": ["biliary", "cholangiocarcinoma"], "C25": ["pancreatic", "pancreas"],
    "C32": ["laryngeal", "head and neck"], "C34": ["lung", "NSCLC", "SCLC"], "C37": ["thymic", "thymoma"],
    "C40": ["bone sarcoma", "osteosarcoma"], "C41": ["bone sarcoma", "Ewing"], "C43": ["melanoma"],
    "C44": ["skin cancer", "basal cell", "cutaneous squamous"], "C45": ["mesothelioma"],
    "C48": ["peritoneal"], "C49": ["soft tissue sarcoma", "sarcoma"], "C50": ["breast"],
    "C51": ["vulvar"], "C53": ["cervical"], "C54": ["endometrial", "uterine"], "C55": ["uterine"],
    "C56": ["ovarian"], "C57": ["ovarian", "fallopian"], "C61": ["prostate"], "C62": ["testicular", "germ cell"],
    "C64": ["renal cell", "kidney"], "C65": ["urothelial", "renal pelvis"], "C66": ["urothelial", "ureter"],
    "C67": ["bladder", "urothelial"], "C68": ["urothelial"], "C69": ["uveal", "retinoblastoma"],
    "C71": ["glioma", "glioblastoma", "brain tumor"], "C73": ["thyroid"], "C74": ["adrenal", "neuroblastoma"],
    "C7A": ["neuroendocrine"], "C81": ["Hodgkin lymphoma"],
    "C82": ["follicular lymphoma", "lymphoma"], "C83": ["lymphoma", "DLBCL", "mantle cell"],
    "C84": ["T-cell lymphoma"], "C85": ["lymphoma"], "C88": ["lymphoma", "Waldenstrom"],
    "C90": ["multiple myeloma", "myeloma"], "C91": ["lymphoblastic leukemia", "CLL", "leukemia"],
    "C92": ["myeloid leukemia", "AML", "CML", "leukemia"], "C93": ["leukemia"], "C95": ["leukemia"],
    "D46": ["myelodysplastic", "MDS"], "D47": ["myeloproliferative"],
}


def _known_positive(f: dict) -> bool:
    return (f.get("state") == "known" and f.get("assertion") in ("positive", "historical", None)
            and f.get("subject_scope", "patient") == "patient")


def patient_profile(packet: Dict[str, Any]) -> Dict[str, Any]:
    age: Optional[Tuple[Optional[float], Optional[float]]] = None
    gender: Optional[str] = None
    icd10: List[str] = []
    for f in packet.get("facts") or []:
        if not isinstance(f, dict) or not _known_positive(f):
            continue
        key, v = f.get("fact_key"), f.get("value")
        if not isinstance(v, dict):
            continue
        kind = v.get("kind")
        if key == "demographics.age":
            if kind in ("integer", "quantity") and isinstance(v.get("value"), (int, float)):
                age = (float(v["value"]), float(v["value"]))
            elif kind == "interval":
                age = (v.get("lower"), v.get("upper"))
            elif kind == "band":
                age = (v.get("lower_inclusive"), v.get("upper_inclusive"))
        elif key == "demographics.administrative_gender" and kind == "coded":
            code = str(v.get("code") or "").lower()
            if code in ("female", "male"):
                gender = code
        elif key == "disease.primary" and kind == "coded" and str(v.get("system", "")).upper().startswith("ICD-10"):
            if v.get("code"):
                icd10.append(str(v["code"]).upper())
    terms: List[str] = []
    for code in icd10:
        for t in ICD10_TERMS.get(code[:3], []):
            if t not in terms:
                terms.append(t)
    point_age = age[0] if age and age[0] is not None and age[0] == age[1] else None
    return {"age_band": age, "age": point_age, "gender": gender, "icd10": icd10, "diagnosis_terms": terms}
