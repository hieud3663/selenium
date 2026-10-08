"""CI must reject missing browser evidence and preserve failed runner outcomes."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import ci_runner as ci_tests
from testcases.reader import load_cases


class CITests(unittest.TestCase):
    def test_default_ci_scope_checks_auth_without_successful_login(self):
        cases = load_cases()
        normal = set(ci_tests.selected_ids(cases))
        full = set(ci_tests.selected_ids(cases, security=True))
        self.assertEqual(len(normal), 40)
        self.assertEqual(full, normal)
        self.assertTrue({case['id'] for case in cases if 'payload' in case['parameters']} <= normal)
        self.assertTrue({'TC_FUNC_01', 'TC_FUNC_07', 'TC_FUNC_08', 'TC_FUNC_10', 'TC_UI_02'} <= normal)
        self.assertTrue({'TC_FUNC_02', 'TC_FUNC_03', 'TC_FUNC_04', 'TC_FUNC_05', 'TC_FUNC_06'} <= normal)

    def write_report(self, root, ids, exit_code=0):
        output = root / 'reports' / 'new-run'
        (output / 'allure-results').mkdir(parents=True)
        (output / 'allure-report').mkdir()
        (output / 'allure-report' / 'index.html').write_text('fixture', encoding='utf-8')
        (output / 'results.xlsx').touch()
        for case_id in ids:
            (output / 'allure-results' / f'{case_id}-result.json').write_text('{}', encoding='utf-8')
        report = {'run_id': 'new-run', 'tests_run': len(ids), 'exit_code': exit_code,
                  'environment': {'browser_enabled': True, 'headless': False},
                  'results': {case_id: {'status': 'PARTIAL_PASS'} for case_id in ids},
                  'unexecuted_cases': []}
        (output / 'results.json').write_text(json.dumps(report), encoding='utf-8')
        return report, output

    def test_gate_rejects_skip_missing_case_disabled_browser_and_missing_artifacts(self):
        for mutation in ('skip', 'case', 'browser', 'html', 'excel', 'allure'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                report, output = self.write_report(Path(directory), ['TC_FUNC_01'])
                if mutation == 'skip':
                    report['results']['TC_FUNC_01']['status'] = 'SKIP'
                elif mutation == 'case':
                    report['results'].clear()
                elif mutation == 'browser':
                    report['environment']['browser_enabled'] = False
                else:
                    path = {'html': 'allure-report/index.html', 'excel': 'results.xlsx',
                            'allure': 'allure-results/TC_FUNC_01-result.json'}[mutation]
                    (output / path).unlink()
                self.assertTrue(ci_tests.report_errors(report, ['TC_FUNC_01'], output))

    def test_ci_preserves_runner_codes_and_writes_summary_for_failed_run(self):
        for code in (0, 1, 2):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                ids = ci_tests.selected_ids(load_cases(), security=True)
                def run(arguments):
                    self.assertNotIn('--security', arguments)
                    self.assertIn('--headless', arguments)
                    self.assertEqual(arguments.count('--test'), len(ids))
                    self.write_report(root, ids, code)
                    return code
                with patch('tests.ci_runner.ROOT', root), patch('tests.ci_runner.run_tests', side_effect=run), \
                     patch.dict('os.environ', {'GITHUB_STEP_SUMMARY': str(root / 'summary.md')}), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(ci_tests.main(['--security', '--headless']), code)
                self.assertIn('PARTIAL_PASS', (root / 'summary.md').read_text(encoding='utf-8'))
                self.assertTrue((root / 'reports/new-run/ci-summary.md').is_file())

    def test_ci_cannot_reuse_a_previous_successful_report_when_runner_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_report(root, ci_tests.selected_ids(load_cases()))
            with patch('tests.ci_runner.ROOT', root), patch('tests.ci_runner.run_tests', return_value=0), \
                 contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(ci_tests.main([]), 1)

    def test_observed_framing_finding_is_reported_without_faking_test_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ids = ci_tests.selected_ids(load_cases())
            def run(arguments):
                self.assertIn('--headless', arguments)
                report, output = self.write_report(root, ids)
                report['environment']['headless'] = True
                report['results']['TC_SEC_12'] = {
                    'status': 'PASS',
                    'observations': {
                        'framing_assessment': 'SECURITY_FINDING',
                        'findings': ['missing_x_frame_options_and_csp_frame_ancestors',
                                     'login_form_rendered_in_cross_origin_iframe'],
                        'x_frame_options': None,
                        'csp_frame_ancestors': False,
                        'login_form_loaded_in_cross_origin_frame': True,
                    },
                }
                (output / 'results.json').write_text(json.dumps(report), encoding='utf-8')
                return 0
            summary_path = root / 'summary.md'
            with patch('tests.ci_runner.ROOT', root), patch('tests.ci_runner.run_tests', side_effect=run), \
                 patch.dict('os.environ', {'GITHUB_STEP_SUMMARY': str(summary_path)}), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ci_tests.main(['--headless']), 0)
            summary = summary_path.read_text(encoding='utf-8')
            self.assertIn('Headless Chrome', summary)
            self.assertIn('Security observations', summary)
            self.assertIn('CI gate', summary)
            self.assertIn('**PASSED**', summary)
            self.assertIn('PASS means the observation was collected', summary)
            self.assertIn('login_form_rendered_in_cross_origin_iframe', summary)


if __name__ == '__main__':
    unittest.main()
