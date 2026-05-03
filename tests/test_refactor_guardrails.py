import unittest
from pathlib import Path

from app import app
from verification.refactor_guard import collect_route_map, diff_route_maps, load_baseline, run_smoke_checks


class RefactorGuardrailsTestCase(unittest.TestCase):
    def test_route_contract_has_no_breaking_changes(self):
        baseline_path = Path('verification/route_baseline.json')
        self.assertTrue(baseline_path.exists(), 'Missing verification/route_baseline.json baseline file')

        baseline = load_baseline(baseline_path)
        current = collect_route_map(app)
        diff = diff_route_maps(baseline, current)

        self.assertEqual(
            diff['removed'],
            [],
            f"Removed routes detected: {diff['removed']}"
        )
        self.assertEqual(
            diff['changed_methods'],
            [],
            f"Route method changes detected: {diff['changed_methods']}"
        )

    def test_refactor_smoke_endpoints(self):
        smoke = run_smoke_checks(app)
        self.assertEqual(smoke['failed'], [], f"Smoke checks failed: {smoke['failed']}")


if __name__ == '__main__':
    unittest.main()
