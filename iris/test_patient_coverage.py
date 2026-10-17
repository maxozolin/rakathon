"""Synthetic tests only; this module never reads patient data."""
import unittest
from audit_patient_coverage import compile_rules, normalize, rx, LAB_RULES


class CoverageRulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rules = compile_rules()

    def candidate(self, feature, text):
        return bool(self.rules[feature][1].search(normalize(text)))

    def test_ecog_scale_and_interval(self):
        self.assertTrue(self.candidate('ecog', 'ECOG: 1'))
        self.assertTrue(self.candidate('ecog', 'ECOG 1-2'))
        self.assertFalse(self.candidate('ecog', 'ECOG 12'))
        self.assertFalse(self.candidate('ecog', 'ECOG neuvedeno'))

    def test_karnofsky_scale(self):
        self.assertTrue(self.candidate('karnofsky', 'Karnofsky 90%'))

    def test_egfr_gene_not_renal_function(self):
        mention, _ = self.rules['biomarker_egfr']
        self.assertFalse(bool(mention.search('eGFR(CKD): 1.0 ml/s')))
        self.assertTrue(self.candidate('biomarker_egfr', 'EGFR neg'))

    def test_tnm_not_hospital_abbreviation(self):
        mention, _ = self.rules['stage_tnm']
        self.assertFalse(bool(mention.search('FTNm')))
        self.assertTrue(self.candidate('stage_tnm', 'pT1cpN0M0'))

    def test_therapy_line_not_fracture(self):
        self.assertFalse(self.candidate('therapy_line', 'lomná linie'))
        self.assertTrue(self.candidate('therapy_line', '2. linie léčby'))

    def test_marker_mention_not_test_result(self):
        self.assertFalse(self.candidate('biomarker_er', 'ER neuvedeno'))
        self.assertFalse(self.candidate('biomarker_pr', 'PR neuvedeno'))
        self.assertTrue(self.candidate('biomarker_er', 'ER 90%'))
        self.assertFalse(self.candidate('biomarker_her2', 'HER2 nelze'))
        self.assertTrue(self.candidate('biomarker_her2', 'HER2 2+'))
        self.assertFalse(self.candidate('biomarker_brca', 'Analyzovány oblasti BRCA1, BRCA2'))

    def test_anc_not_percentage(self):
        rule = rx(LAB_RULES['anc_absolute'])
        self.assertFalse(bool(rule.search('Neutrofily relativni %')))
        self.assertTrue(bool(rule.search('Neutrofily abs. pocet')))


if __name__ == '__main__':
    unittest.main()
