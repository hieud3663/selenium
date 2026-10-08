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

    def test_empty_field_check_requires_matching_rejection_and_actual_post(self):
        for field, case_id in [('username', 'TC_FUNC_02'), ('password', 'TC_FUNC_03'), ('both', 'TC_FUNC_04')]:
            for method in ('POST', 'GET', None):
                with self.subTest(field=field, method=method):
                    case = browser_tests.TestLogin('test_' + case_id)
                    case.settings = Settings()
                    case.spec = next(spec for spec in load_cases() if spec['id'] == case_id)
                    case.driver = Mock()
                    case.driver.execute_script.return_value = False
                    case.login_page = Mock()
                    case.login_page.login_form.return_value.get_attribute.return_value = 'https://example.test/Login'
                    case.assert_rejected = Mock()
                    requests = [] if method is None else [{'url': 'https://example.test/Login', 'method': method}]
                    with patch('tests.test_login.network_events', return_value=[]), \
                         patch('tests.test_login.collect_until_idle', return_value=[]), \
                         patch('tests.test_login.requests', return_value=requests):
                        if method == 'POST':
                            case.assert_required_fields()
                        else:
                            with self.assertRaises(AssertionError):
                                case.assert_required_fields()
                    case.assert_rejected.assert_called_once_with(case.spec['parameters']['error_text'])
                    case.login_page.enter_username.assert_called_once_with('' if field in {'username', 'both'} else 'validation_test')
                    case.login_page.enter_password.assert_called_once_with('' if field in {'password', 'both'} else 'validation_test')

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
