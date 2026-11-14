"""Offline tooling tests; deliberately outside pytest's destructive DB fixtures."""
import unittest
from datetime import date
from scripts.repro_demo import validate_target, plan
from scripts.repository_release import public_path, forbidden_path, findings
from scripts.build_audit_package import safe_rel

class HardeningTests(unittest.TestCase):
    def test_target_refusals(self):
        for url in ['sqlite:///local.db','postgresql+psycopg://u:p@remote/petops_repro_demo_test','postgresql+psycopg://u:p@localhost/petops_demo','postgresql+psycopg://u:p@localhost/petops_repro_demo_test?host=remote']:
            with self.subTest(url=url.split('://')[0]):
                with self.assertRaises(ValueError):validate_target(url)
    def test_exact_target(self):
        self.assertEqual(validate_target('postgresql+psycopg://fixture:placeholder@127.0.0.1/petops_repro_demo_test').database,'petops_repro_demo_test')
    def test_repeatable_plan(self):
        self.assertEqual(plan(date(2026,11,15)),plan(date(2026,11,15)))
    def test_exclusions(self):
        for path in ['.env','.env.production','docs/private/notes.md','participants/p1.json','.local/runtime.json','dump.backup','../app/main.py']:
            self.assertTrue(forbidden_path(path),path);self.assertFalse(public_path(path),path)
    def test_allowlist(self):
        self.assertTrue(public_path('app/main.py'));self.assertTrue(public_path('.env.example'))
        self.assertFalse(public_path('docs/evidence/participant.png'));self.assertFalse(public_path('docs/current/CURRENT_HANDOFF.md'))
    def test_secret_detection_without_values(self):
        self.assertIn('database_password_url',findings(b'postgresql://person:' + b'nonfixture-value@localhost/db'))
        self.assertEqual(findings(b'postgresql://petops:CHANGE_ME@localhost/db'),[])
    def test_audit_package_exclusions(self):
        for path in ['.local/config.json','.env.staging','private/notes.md','participant_data/p1.json','database.dump','server.key','../data.md']:
            self.assertFalse(safe_rel(path),path)
        self.assertTrue(safe_rel('alembic/versions/0008_rules.sql'))
        self.assertTrue(safe_rel('.env.example'))

if __name__=='__main__':unittest.main()
