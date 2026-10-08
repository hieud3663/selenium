"""Auth regressions exercise rejection oracles and the default credential-independent scope."""
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from config import Settings
from pages.login_page import LoginPage
from testcases.reader import auth_flow_ids, load_cases
from tests import test_login as browser_tests


class AuthFlowTests(unittest.TestCase):
    def test_field_specific_error_does_not_require_generic_credentials_error(self):
        driver = Mock()
        error = Mock()
        error.text = 'Bạn chưa nhập mật khẩu'
        driver.find_elements.return_value = [error]
        page = LoginPage(driver, Settings(timeout=0.01))
        self.assertIs(page.wait_for_error('Bạn chưa nhập mật khẩu'), error)
        error.text = 'Unexpected response'
        from selenium.common.exceptions import TimeoutException
        with self.assertRaises(TimeoutException):
            page.wait_for_error('Bạn chưa nhập mật khẩu')


    def test_default_runner_executes_only_auth_scope_even_without_valid_password(self):
        import run_tests
        specs = load_cases()
        ids = auth_flow_ids(specs)
        received = []
        def observe(case):
            self.assertEqual(case.settings.password, '')
            received.append(case.spec['id'])
        synthetic = type('AuthFixture', (unittest.TestCase,), {'test_' + case_id: observe for case_id in ids})
        with tempfile.TemporaryDirectory() as directory, \
             patch('run_tests.ROOT', Path(directory)), \
             patch('run_tests.SETTINGS', replace(Settings(), password='', success_text='', protected_url='')), \
             patch('tests.test_login.TestLogin', synthetic), \
             patch('reporting.allure_report.generate_html'), \
             contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_tests.main([]), 0)
            report_path = next((Path(directory) / 'reports').glob('*/results.json'))
            report = json.loads(report_path.read_text(encoding='utf-8'))
        self.assertEqual(received, ids)
        self.assertEqual(report['tests_run'], 40)
        self.assertEqual(len(ids), 40)


if __name__ == '__main__':
    unittest.main()
