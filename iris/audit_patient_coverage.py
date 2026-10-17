"""Offline, restricted coverage audit. No network access or clinical adjudication.

Writes owner-only aggregates and candidate evidence pointers, never text excerpts.
Coverage means source presence/regex candidates, not validated patient facts.
"""
import base64
from collections import Counter, defaultdict
import csv
import hashlib
import html
import json
import os
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/rakathon-dataset'
OUTPUT = ROOT / '.opencode-secrets/patient-coverage'


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text)
                   if not unicodedata.combining(c))


def rx(pattern, sensitive=False):
    return re.compile(pattern, 0 if sensitive else re.I)


# Result-bearing candidates intentionally use narrow context; they still need
# subject, negation, history, copy-forward and specimen adjudication locally.
RULES = {
    'histology': (r'\bhistol\w*|\bcytol\w*|\bmorfolog\w*|\badenokarcinom\w*|\bkarcinom\w*|\bHGSOC\b|\bSCLC\b|\bNSCLC\b',
                  r'\b(?:adenokarcinom\w*|dlazdicobunec\w*|malobunec\w*|nemalobunec\w*|lobular\w*|duktal\w*|seroz\w*|HGSOC|SCLC|NSCLC)\b|(?:histolog\w*|cytol\w*)[^\n.;]{0,60}(?:potvrz\w*|prokaz\w*|adenokarcinom\w*|karcinom\w*)'),
    'stage_tnm': (r'\bTNM\b|\bstadi\w*|\bstage\b|\b(?:[cpyra]{0,3})T(?:is|[0-4x])(?:[a-d])?(?:\s|N|\b)',
                  r'\b[cpyra]{0,3}T(?:is|[0-4x])[a-d]?(?:\s*|\s*[,;]\s*)[cpyra]{0,3}N[0-3x]|\b(?:stadi\w*|stage)\s*[:=-]?\s*(?:[0-4]\b|IV\b|III\b|II\b|I\b)'),
    'metastatic_extent': (r'\bmetast\w*|\bdisemin\w*|\bgeneraliz\w*|\blokalne\s+pokrocil\w*',
                          r'\bmetast\w*|\bdisemin\w*|\bgeneraliz\w*|\blokalne\s+pokrocil\w*'),
    'recurrence_progression': (r'\brecidiv\w*|\brelaps\w*|\bprogres\w*|\brefrakter\w*',
                              r'\brecidiv\w*|\brelaps\w*|\bprogres\w*|\brefrakter\w*'),
    'ecog': (r'\bECOG\b', r'\bECOG\s*(?:PS\s*)?[:=.-]?\s*[0-4](?:\s*[-/]\s*[0-4])?\b'),
    'karnofsky': (r'\bKarnof\w*', r'\bKarnof\w*\s*[:=()%.-]?\s*(?:100|[1-9]0)\s*%?'),
    'therapy_line': (r'\b(?:lini\w*|[1-9]L)\b',
                     r'\b[1-9]\s*\.?\s*lini\w*\s*(?:system\w*\s*)?(?:lec\w*|terap\w*|CHT\b|HT\b)|\b(?:prvni|druh\w*|tret\w*|ctvrt\w*|pat\w*)\s+lini\w*\s*(?:lec\w*|terap\w*)|\b[1-9]L\s*(?:lec\w*|terap\w*|CHT\b)'),
    'therapy_intent': (r'\b(?:neoadjuvan\w*|adjuvan\w*|paliativ\w*)',
                       r'\b(?:neoadjuvan\w*|adjuvan\w*|paliativ\w*)\s+(?:lec\w*|terap\w*|CHT\b|chemoterap\w*|radioterap\w*)'),
    'cns_mets': (r'\bCNS\b|\bmozk\w*|\bbrain\b',
                 r'(?:metast\w*|meta)\s*(?:do\s+|v\s+|na\s+)?(?:CNS|mozk\w*)\b|(?:CNS|mozk\w*)[^\n.;]{0,40}\bmetast\w*'),
    'recist': (r'\bRECIST\b|\bmeriteln\w*|\bmeasurable\b',
               r'\bRECIST\b|\b(?:meriteln\w*|measurable)\s+(?:lez\w*|onemocnen\w*|lozisk\w*|disease)'),
    'tissue_availability': (r'\bFFPE\b|\barchiv\w*\s+(?:tkan\w*|vzorek\w*|material\w*)',
                            r'(?:FFPE|archiv\w*\s+(?:tkan\w*|vzorek\w*|material\w*))[^\n.;]{0,60}(?:dostup\w*|k\s+dispozici)|(?:dostup\w*|k\s+dispozici)[^\n.;]{0,60}(?:FFPE|archiv\w*\s+tkan\w*)'),
    'qtc': (r'\bQTc\w*\b', r'\bQTc\w*\s*[:=]?\s*[2-6]\d{2}\s*(?:ms)?\b'),
    'lvef': (r'\bLVEF\b|\bEF\s*LK\b|\bejekcn\w*\s+frakc\w*',
             r'(?:\bLVEF\b|\bEF\s*LK\b|\bejekcn\w*\s+frakc\w*)\s*[:=]?\s*\d{1,2}(?:\s*[-/]\s*\d{1,2})?\s*%'),
    'pregnancy_test': (r'\bhCG\b|\bgravid\w*|\btehot\w*',
                       r'\b(?:hCG|tehotensk\w*\s+test)\s*[:=]?\s*(?:neg\w*|poz\w*|\d+[.,]?\d*\s*(?:IU|U))'),
    'infection_safety': (r'\bHIV\b|\bHBV\b|\bHCV\b|\bHBsAg\b|\bhepatit\w*',
                         r'\b(?:HIV|HBV|HCV|HBsAg|anti[- ]?HCV)\s*[:=]?\s*(?:neg\w*|poz\w*|reaktiv\w*|nereaktiv\w*)'),
}

BIOMARKERS = {
    'her2': r'\bHER[- ]?2\b',
    'er': r'\bER\b|\bestrogen\w*\s+receptor\w*',
    'pr': r'\bPR\b|\bprogesteron\w*\s+receptor\w*',
    'brca': r'\b(?:BRCA|mBRCA)(?:\s*[12])?(?![12])\b',
    # Preserve case so renal eGFR is NOT counted as molecular EGFR.
    'egfr': r'\bEGFR\b',
    'alk': r'\bALK\b', 'braf': r'\bBRAF\b', 'kras': r'\bKRAS\b',
    'pdl1': r'\bPD[- ]?L[- ]?1\b', 'msi': r'\bMSI\b',
    'mmr': r'\b(?:MMR|dMMR|pMMR|MLH1|MSH2|MSH6|PMS2)\b', 'tmb': r'\bTMB\b',
}

LAB_RULES = {
    'anc_absolute': r'(?:neutrofil\w*.*(?:abs|pocet)|(?:abs|pocet).*neutrofil\w*|\bANC\b|\bNEU[T]?\s*[#])',
    'neutrophil_unspecified': r'neutrofil\w*|\bNEU[T]?\b',
    'platelets': r'trombocyt\w*|\bPLT\b',
    'hemoglobin': r'hemoglobin\w*|\bHGB\b|\bHB\b',
    'creatinine': r'kreatinin\w*|\bCREA\b|\bKREA\b',
    'egfr_renal': r'\beGFR\b|odhad\w*\s+(?:GF|glomerul\w*)|CKD[- ]?EPI|Lund[- ]?Malmo',
    'bilirubin': r'bilirubin\w*|\bBILI\b',
    'alt': r'\bALT\b|alanin\w*\s*(?:aminotransferaz\w*|transaminaz\w*)',
    'ast': r'\bAST\b|aspartat\w*\s*(?:aminotransferaz\w*|transaminaz\w*)',
    'albumin': r'albumin\w*|\bALB\b',
    'pregnancy_hcg': r'\bhCG\b|chori\w*gonadotrop\w*',
}


def compile_rules():
    rules = {name: (rx(mention), rx(candidate)) for name, (mention, candidate) in RULES.items()}
    result = r'\s*[:=,-]?\s*(?:\(?[0123]\+?\)?|\d{1,3}(?:[.,]\d+)?\s*%|neg\w*|poz\w*|positive\b|negative\b|mutac\w*|mutat\w*|wild[- ]?type\b|wt\b|high\b|low\b|deficien\w*|proficien\w*|loss\b|retained\b|exon\s*\d+)(?!\w)'
    for name, pattern in BIOMARKERS.items():
        rules['biomarker_' + name] = (rx(pattern, name == 'egfr'), rx('(?:' + pattern + ')' + result, name == 'egfr'))
    return rules


def save_json(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    path.chmod(0o600)


def main():
    OUTPUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    OUTPUT.chmod(0o700)
    rules = compile_rules()
    structured = Counter()
    patient_counts = defaultdict(Counter)
    document_counts = defaultdict(Counter)
    resource_counts = Counter()
    quality = Counter()
    fingerprints = hashlib.sha256()
    patient_total = 0
    pointers_path = OUTPUT / 'candidate-pointers.ndjson'
    pointers_fd = os.open(pointers_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(pointers_fd, 'w') as pointers:
        for path in sorted((SOURCE / 'fhir').glob('PAC-*.json')):
            raw = path.read_bytes()
            fingerprints.update(hashlib.sha256(raw).digest())
            bundle = json.loads(raw)
            patient_total += 1
            patient_id = next(e['resource']['id'] for e in bundle['entry']
                              if e['resource']['resourceType'] == 'Patient')
            present = set()
            hits = defaultdict(set)
            texts_seen = set()
            for entry in bundle['entry']:
                resource = entry['resource']
                kind = resource['resourceType']
                resource_counts[kind] += 1
                if kind == 'Patient':
                    if resource.get('gender') not in (None, 'unknown'):
                        present.add('administrative_gender')
                    if resource.get('birthDate'):
                        present.add('partial_birth_date')
                    for extension in resource.get('extension', []):
                        tail = extension.get('url', '').rsplit('/', 1)[-1]
                        if tail == 'vek': present.add('age_exact_extension')
                        if tail == 'vek-pasmo': present.add('age_band_extension')
                if kind == 'Condition' and resource.get('code', {}).get('coding'):
                    present.add('coded_condition_not_primary_confirmation')
                if kind in ('MedicationRequest', 'MedicationAdministration'):
                    present.add('medication_event_not_regimen')
                    if any(c.get('system') == 'http://www.whocc.no/atc' for c in
                           resource.get('medicationCodeableConcept', {}).get('coding', [])):
                        present.add('medication_atc_code')
                if kind == 'Procedure': present.add('procedure_event')
                if kind == 'ImagingStudy': present.add('imaging_metadata_not_dicom')
                texts = []
                if kind == 'DocumentReference':
                    plain = []
                    fallback = []
                    for content in resource.get('content', []):
                        attachment = content.get('attachment', {})
                        if not attachment.get('data'): continue
                        try:
                            decoded = base64.b64decode(attachment['data'], validate=True).decode('utf-8')
                        except (ValueError, UnicodeDecodeError):
                            quality['attachment_decode_failure'] += 1
                            continue
                        if attachment.get('contentType') == 'text/plain': plain.append(decoded)
                        elif attachment.get('contentType') == 'text/html':
                            fallback.append(html.unescape(re.sub(r'<[^>]+>', ' ', decoded)))
                    texts = plain or fallback
                elif kind == 'DiagnosticReport' and resource.get('conclusion'):
                    texts = [resource['conclusion']]
                for text in texts:
                    text = normalize(text)
                    # Deduplicate normalized text per patient, not globally:
                    # repeated copy-forward must not inflate document coverage.
                    text_hash = hashlib.sha256(text.encode()).hexdigest()
                    if text_hash in texts_seen:
                        quality['duplicate_narrative_texts_skipped'] += 1
                        continue
                    texts_seen.add(text_hash)
                    present.add('narrative_text')
                    quality['unique_narrative_texts_scanned'] += 1
                    for name, (mention_rule, candidate_rule) in rules.items():
                        mention = mention_rule.search(text)
                        if not mention: continue
                        hits[name].add('mention')
                        document_counts[name]['mention'] += 1
                        candidate = candidate_rule.search(text)
                        nearby = text[max(0, mention.start() - 80):mention.end() + 100]
                        ambiguous = bool(rx(r'\b(?:rodinn\w*|RA\s*:|matk\w*|otec|bratr\w*|sestr\w*|plan\w*|indik\w*|vylouc\w*|bez|neg\w*|suspekt\w*|nelze|neprokaz\w*)').search(nearby))
                        if ambiguous:
                            hits[name].add('ambiguous_context')
                            document_counts[name]['ambiguous_context'] += 1
                        if candidate:
                            hits[name].add('candidate')
                            document_counts[name]['candidate'] += 1
                            pointers.write(json.dumps({'patient_id': patient_id,
                                'feature': name, 'resource_type': kind, 'resource_id': resource['id'],
                                'recorded_time': resource.get('date') or resource.get('effectiveDateTime'),
                                'candidate_offset': candidate.start(), 'ambiguous_context': ambiguous,
                                'clinical_adjudication': 'not_performed'}, ensure_ascii=False) + '\n')
            for fact in present: structured[fact] += 1
            for name, states in hits.items():
                for state in states: patient_counts[name][state] += 1
            # Panel conjunctions count candidates, not confirmed valid measurements.
            if {'ecog', 'stage_tnm', 'histology'} <= {k for k, v in hits.items() if 'candidate' in v}:
                structured['histology_stage_ecog_candidates_all'] += 1
    lab_matches = {name: rx(pattern) for name, pattern in LAB_RULES.items()}
    labs = defaultdict(lambda: defaultdict(set))
    lab_rows = defaultdict(Counter)
    with (SOURCE / 'lab.csv').open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.DictReader(stream, delimiter=';'):
            label = normalize(row.get('nazev', '') + ' ' + row.get('kod', ''))
            for name, rule in lab_matches.items():
                if not rule.search(label): continue
                pid = row['pseudonym']
                labs[name]['any_test_label'].add(pid)
                lab_rows[name]['matched_rows'] += 1
                if row.get('hodnota') and row.get('jednotka') and row.get('datum'):
                    labs[name]['numeric_unit_date_present_not_validated'].add(pid)
                    lab_rows[name]['numeric_unit_date_present_rows'] += 1
                if row.get('nclp'):
                    labs[name]['nclp_present'].add(pid)
    for panel, names in {'cbc_without_anc': ['platelets', 'hemoglobin'],
                         'cbc_with_anc_label': ['anc_absolute', 'platelets', 'hemoglobin'],
                         'chemistry_basic': ['creatinine', 'bilirubin', 'alt', 'ast', 'albumin']}.items():
        sets = [labs[name]['numeric_unit_date_present_not_validated'] for name in names]
        structured[panel + '_any_time_candidates'] = len(set.intersection(*sets))
    results = {
        'scope': 'offline structural and narrative candidate coverage, not validated clinical extraction',
        'patient_bundles_scanned': patient_total,
        'source_individual_bundle_digest': fingerprints.hexdigest(),
        'structured_patient_presence': dict(structured),
        'narrative_patient_coverage': {name: dict(patient_counts[name]) for name in rules},
        'narrative_document_coverage': {name: dict(document_counts[name]) for name in rules},
        'lab_patient_label_coverage': {name: {key: len(value) for key, value in labs[name].items()} for name in LAB_RULES},
        'lab_candidate_row_counts': {name: dict(value) for name, value in lab_rows.items()},
        'resource_inventory': dict(resource_counts), 'quality': dict(quality),
        'limitations': ['no patient-subject adjudication', 'no clinical accuracy assessment',
            'no negation/history resolution', 'no freshness adjudication',
            'no analyte/unit validation', 'no full molecular/histology coverage claim',
            'lab panels are any-time co-presence, not same-day panels',
            'candidate offsets refer to normalized text', 'no attempt to recover suppressed facts'],
    }
    save_json(OUTPUT / 'coverage.json', results)
    # Save the exact pattern definitions for reproducible operator review.
    save_json(OUTPUT / 'rules.json', {'version': 'candidate-audit-v1',
        'narrative': {name: {'mention': a.pattern, 'candidate': b.pattern,
                            'flags': a.flags} for name, (a, b) in rules.items()}, 'labs': LAB_RULES})
    print('Offline coverage audit complete. Restricted outputs: .opencode-secrets/patient-coverage/')
    print('No narratives, identifiers or clinical values emitted to console. Clinical validation not performed.')


if __name__ == '__main__':
    main()
