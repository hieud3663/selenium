"""Offline integration checks for the official Allure result writer."""
import base64
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import allure_commons
from config import Settings
from reporting.allure_report import AllureWriter
from testcases.reader import load_cases
from reporting.test_result import EvidenceResult


class AllureReportTests(unittest.TestCase):
    def test_runner_closes_shared_browser_when_report_writer_raises(self):
        import run_tests
        closed = []
        class Fixture(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                cls.addClassCleanup(lambda: closed.append(True))
            def test_TC_FUNC_01(self):
                self.assertTrue(True)
        with tempfile.TemporaryDirectory() as directory, \
             patch('run_tests.ROOT', Path(directory)), \
             patch('tests.test_login.TestLogin', Fixture), \
             patch('run_tests.auth_flow_ids', return_value=['TC_FUNC_01']), \
             patch('reporting.allure_report.AllureWriter.finish', side_effect=OSError('report removed')), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(OSError):
                run_tests.main([])
        self.assertEqual(closed, [True])

    def test_open_report_selects_latest_html_without_reading_excel_or_running_tests(self):
        import run_tests
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "reports" / "old" / "allure-report"
            latest = root / "reports" / "latest-run" / "allure-report"
            old.mkdir(parents=True)
            latest.mkdir(parents=True)
            (old / "index.html").write_text("old", encoding="utf-8")
            (latest / "index.html").write_text("latest", encoding="utf-8")
            import os
            os.utime(old / "index.html", (1, 1))
            os.utime(latest / "index.html", (2, 2))
            with patch("run_tests.ROOT", root), patch("run_tests.load_cases") as read_excel, \
                 patch("reporting.allure_report.open_html") as open_html:
                self.assertEqual(run_tests.main(["--open-report"]), 0)
                open_html.assert_called_once_with(latest, run_tests.SETTINGS.allure_command)
                read_excel.assert_not_called()

    def test_cli_flags_pass_configuration_directly_to_test_instances(self):
        import run_tests
        received = []
        def observe_settings(case):
            received.append(case.settings)
            case.skipTest("Offline configuration fixture")
        synthetic = type("SettingsFixture", (unittest.TestCase,), {"test_TC_FUNC_01": observe_settings})
        with tempfile.TemporaryDirectory() as directory, \
             patch("run_tests.ROOT", Path(directory)), \
             patch("run_tests.SETTINGS", Settings(run_browser=False, run_security=False, username="configured-user")), \
             patch("tests.test_login.TestLogin", synthetic), \
             patch("reporting.allure_report.generate_html"), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_tests.main(["--browser", "--security", "--test", "TC_FUNC_01"]), 2)
        self.assertEqual(len(received), 1)
        self.assertTrue(received[0].run_browser)
        self.assertTrue(received[0].run_security)
        self.assertEqual(received[0].username, "configured-user")

    def test_failure_screenshot_is_copied_to_allure_attachment(self):
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")
        class FakeDriver:
            def execute_script(self, script):
                pass
            def save_screenshot(self, path):
                Path(path).write_bytes(png)
                return True
        def fail_with_browser(case):
            case.driver = FakeDriver()
            case.fail("Failure with screenshot")
        synthetic = type("ScreenshotFixture", (unittest.TestCase,), {"test_TC_FUNC_01": fail_with_browser})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with AllureWriter(output / "allure-results") as writer:
                factory = lambda *a, **kw: EvidenceResult(*a, report_dir=output, cases=load_cases(),
                                                        allure_writer=writer, **kw)
                unittest.TextTestRunner(stream=io.StringIO(), resultclass=factory).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(synthetic))
            record = json.loads(next((output / "allure-results").glob("*-result.json")).read_text(encoding="utf-8"))
            attachment = next(a for a in record["attachments"] if a["type"] == "image/png")
            self.assertEqual((output / "allure-results" / attachment["source"]).read_bytes(), png)

    def test_html_generation_error_keeps_results_and_reports_exit_one(self):
        import run_tests
        def skip(case):
            case.skipTest("No browser in offline fixture")
        synthetic = type("NoBrowserFixture", (unittest.TestCase,), {"test_TC_FUNC_01": skip})
        with tempfile.TemporaryDirectory() as directory, \
             patch("run_tests.SETTINGS", Settings(run_browser=False, run_security=False)), \
             patch("run_tests.ROOT", Path(directory)), \
             patch("run_tests.load_cases", return_value=load_cases()), \
             patch("tests.test_login.TestLogin", synthetic), \
             patch("reporting.allure_report.generate_html", side_effect=RuntimeError("Missing CLI")), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_tests.main(["--allure-html", "--test", "TC_FUNC_01"]), 1)
            report_path = next((Path(directory) / "reports").glob("*/results.json"))
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["exit_code"], 1)
            self.assertEqual(report["counts"], {"SKIP": 1})
            self.assertEqual(report["allure_html_error"], "Missing CLI")
            self.assertEqual(len(list((report_path.parent / "allure-results").glob("*-result.json"))), 1)

    def test_allure_preserves_statuses_scope_redaction_and_cleanup_errors(self):
        def passed(case):
            case.assertTrue(True)
        def failed(case):
            case.fail("private-password assertion failure")
        def broken(case):
            raise RuntimeError("private-password browser disconnected")
        def skipped(case):
            case.skipTest("Missing fixture")
        def cleanup_error(case):
            def cleanup():
                raise RuntimeError("cleanup failed")
            case.addCleanup(cleanup)
        synthetic = type("SyntheticAllure", (unittest.TestCase,), {
            "test_TC_FUNC_01": passed, "test_TC_FUNC_08": passed,
            "test_TC_SEC_02": failed, "test_TC_SEC_03": broken,
            "test_TC_SEC_04": skipped, "test_TC_UI_02": cleanup_error,
        })
        # Fixture metadata is independent of which website cases have been implemented.
        cases = load_cases()
        scopes = {"TC_FUNC_01": "Automated", "TC_FUNC_08": "Partial"}
        for spec in cases:
            if spec["id"] in scopes:
                spec["automation"] = scopes[spec["id"]]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            plugins_before = set(allure_commons.plugin_manager.get_plugins())
            with AllureWriter(output / "allure-results") as writer:
                factory = lambda *a, **kw: EvidenceResult(*a, report_dir=output, cases=cases,
                                                        allure_writer=writer, settings=Settings(password="private-password"), **kw)
                result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=factory).run(
                    unittest.defaultTestLoader.loadTestsFromTestCase(synthetic))
            self.assertEqual(set(allure_commons.plugin_manager.get_plugins()), plugins_before)
            files = list((output / "allure-results").glob("*-result.json"))
            self.assertEqual(len(files), 6)
            records = {r["name"].split(":", 1)[0]: r
                       for r in (json.loads(p.read_text(encoding="utf-8")) for p in files)}
            for id, status in {"TC_FUNC_01": "passed", "TC_FUNC_08": "passed",
                               "TC_SEC_02": "failed", "TC_SEC_03": "broken",
                               "TC_SEC_04": "skipped", "TC_UI_02": "broken"}.items():
                self.assertEqual(records[id]["status"], status)
                self.assertGreaterEqual(records[id]["stop"], records[id]["start"])
                self.assertEqual(records[id]["stage"], "finished")
                for attachment in records[id]["attachments"]:
                    self.assertTrue((output / "allure-results" / attachment["source"]).exists())
            self.assertIn("[Partial]", records["TC_FUNC_08"]["name"])
            self.assertIn({"name": "tag", "value": "Partial"}, records["TC_FUNC_08"]["labels"])
            self.assertEqual(result.records["TC_FUNC_08"]["status"], "PARTIAL_PASS")
            for file in (output / "allure-results").iterdir():
                self.assertNotIn("private-password", file.read_text(encoding="utf-8"))

    def test_environment_properties_do_not_include_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with AllureWriter(output) as writer:
                writer.environment({"scope": "Kiểm tra cục bộ", "run_id": "sample-run"})
            text = (output / "environment.properties").read_text(encoding="ascii")
            self.assertIn("run_id=sample-run", text)
            self.assertIn("\\u", text)
