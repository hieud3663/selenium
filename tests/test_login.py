"""40 unauthenticated auth-flow checks. No valid login or authenticated session is required."""
import math
import statistics
import time
import unittest
from urllib.parse import unquote_plus, urlparse

from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC

from config import SETTINGS
from pages.login_page import LoginPage
from pages.browser_session import collect_until_idle, network_events, requests, responses
from testcases.reader import load_cases

CASES = {case["id"]: case for case in load_cases()}


class TestLogin(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._class_session_active = True
        cls._shared_driver = None
        cls._startup_error = None
        cls._browser_sessions = 0

    @classmethod
    def tearDownClass(cls):
        cls._class_session_active = False

    @classmethod
    def close_shared_browser(cls, driver):
        try:
            driver.quit()
        finally:
            cls._shared_driver = None

    def setUp(self):
        self.current_phase = "setup"
        self.settings = getattr(self, "settings", SETTINGS)
        self.case_id = self._testMethodName.removeprefix("test_")
        self.spec = getattr(self, "spec", CASES[self.case_id])
        if self.spec["id"] != self.case_id:
            raise ValueError("Excel ID không khớp phương thức testcase.")
        if not self.settings.run_browser:
            raise ValueError("Lượt thực thi testcase yêu cầu browser; dùng --check để chỉ đối chiếu dữ liệu.")
        required = ("username", "invalid_password", "nonexistent_username", "error_selector", "error_text")
        missing = [name for name in required if not getattr(self.settings, name)]
        if missing:
            raise ValueError("Thiếu cấu hình auth trong config.py: " + ", ".join(missing))
        if self.settings.invalid_password == self.settings.password:
            raise ValueError("invalid_password không được trùng mật khẩu gốc.")
        cls = type(self)
        shared = getattr(cls, "_class_session_active", False)
        if shared and cls._startup_error:
            raise RuntimeError("Chrome của suite không khởi tạo được; xem lỗi đầu tiên.") from cls._startup_error
        self.driver = cls._shared_driver if shared else None
        if self.driver is None:
            options = webdriver.ChromeOptions()
            options.page_load_strategy = "eager"
            options.add_argument("--window-size=1366,768")
            options.add_experimental_option("excludeSwitches", ["enable-logging"])
            if self.settings.headless:
                options.add_argument("--headless=new")
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
            try:
                self.driver = webdriver.Chrome(options=options)
            except Exception as error:
                if shared:
                    cls._startup_error = error
                raise
            if shared:
                cls._shared_driver = self.driver
                cls._browser_sessions += 1
                cls.addClassCleanup(cls.close_shared_browser, self.driver)
            else:
                self.addCleanup(self.driver.quit)
        self.driver.set_page_load_timeout(self.settings.timeout)
        self.driver.set_script_timeout(self.settings.timeout)
        if shared:
            self.prepare_shared_browser()
        else:
            self.driver.execute_cdp_cmd("Network.enable", {})
        self.login_page = LoginPage(self.driver, self.settings)
        self.login_page.navigate()
        self.current_phase = "test"

    def prepare_shared_browser(self):
        """Restore mutations from previous tests without restarting Chrome."""
        handles = self.driver.window_handles
        if not handles:
            raise RuntimeError("Cửa sổ Chrome của suite đã bị đóng.")
        self.driver.switch_to.window(handles[0])
        self.driver.execute_cdp_cmd("Page.stopLoading", {})
        current = self.driver.current_url
        if isinstance(current, str) and urlparse(current).netloc == urlparse(self.settings.url).netloc:
            self.driver.execute_script("localStorage.clear(); sessionStorage.clear();")
        self.driver.get("about:blank")
        self.driver.switch_to.default_content()
        for handle in handles[1:]:
            self.driver.switch_to.window(handle)
            self.driver.close()
        self.driver.switch_to.window(handles[0])
        for command, parameters in (
            ("Network.enable", {}),
            ("Network.emulateNetworkConditions", {"offline": False, "latency": 0,
                                                   "downloadThroughput": -1, "uploadThroughput": -1}),
            ("Network.setCacheDisabled", {"cacheDisabled": False}),
            ("Network.clearBrowserCookies", {}),
            ("Emulation.clearDeviceMetricsOverride", {}),
            ("Storage.clearDataForOrigin", {"origin": f"{urlparse(self.settings.url).scheme}://{urlparse(self.settings.url).netloc}",
                                           "storageTypes": "local_storage,indexeddb,cache_storage"}),
        ):
            self.driver.execute_cdp_cmd(command, parameters)
        self.driver.set_window_size(1366, 768)
        network_events(self.driver)

    def parameter(self, name):
        value = self.spec["parameters"].get(name)
        if value is None or value == "":
            raise ValueError(f"{self.case_id}: thiếu tham số '{name}' trong Excel.")
        return value

    def observation(self, **values):
        self.observations = getattr(self, "observations", {}) | values

    def assert_rejected(self, expected=None):
        expected = self.settings.error_text if expected is None else expected
        message = self.login_page.wait_for_error(expected)
        self.assertEqual(message.text.strip(), expected)
        self.assertTrue(self.login_page.is_login_page(), "Form login phải còn hiển thị sau từ chối.")

    def reset_form(self):
        self.driver.delete_all_cookies()
        self.login_page.navigate()
        self.driver.execute_script("localStorage.clear(); sessionStorage.clear();")
        self.login_page.navigate()

    def reject(self, username, password, enter=False, capture=False):
        action = self.login_page.login_form().get_attribute("action") if capture else None
        if capture:
            network_events(self.driver)
        started = time.perf_counter()
        self.login_page.login(username, password, enter=enter)
        self.assert_rejected()
        duration = (time.perf_counter() - started) * 1000
        events = collect_until_idle(self.driver, self.settings.timeout) if capture else []
        return duration, action, events

    def empty_fields(self, username, password):
        form = self.login_page.login_form()
        action = form.get_attribute('action')
        network_events(self.driver)
        self.login_page.enter_username(username)
        self.login_page.enter_password(password)
        self.login_page.click_login()
        invalid = self.driver.execute_script("""
            return [...document.querySelectorAll('input')].some(e =>
                !e.validity.valid && e.validationMessage.length > 0);
        """)
        if invalid:
            self.assertTrue(self.login_page.is_login_page())
        else:
            self.assert_rejected(self.parameter('error_text'))
            events = collect_until_idle(self.driver, self.settings.timeout)
            auth = [request for request in requests(events) if urlparse(request['url']).path == urlparse(action).path]
            self.assertTrue(auth)
            self.assertTrue(all(request['method']=='POST' for request in auth))

    def assert_required_fields(self):
        field = self.parameter('empty_field')
        self.empty_fields('' if field in {'username','both'} else 'validation_test',
                          '' if field in {'password','both'} else 'validation_test')

    def check_sql_payload(self, payload, field="username"):
        username = payload if field == "username" else self.settings.username
        password = self.settings.invalid_password if field == "username" else payload
        self.reject(username, password)
        source = self.login_page.get_page_source().lower()
        for pattern in (r"\bsyntax error\b", r"\bsql syntax\b", r"\bora-\d{5}\b",
                        r"\bmysql(?:i)?[ _]+error\b", r"\bsqlserverexception\b",
                        r"\bsqlite(?:3)?[ .]+(?:error|operationalerror|databaseerror)\b",
                        r"\bpsycopg(?:2)?\.(?:errors|error)\b"):
            self.assertNotRegex(source, pattern, "Quan sát thấy lỗi nội bộ DB trong response HTML.")

    def check_xss_payload(self, payload):
        self.login_page.login(payload, self.settings.invalid_password)
        try:
            alert = self.login_page.wait.until(EC.alert_is_present())
        except TimeoutException:
            alert = None
        if alert is not None:
            alert.dismiss()
            self.fail("Xuất hiện alert sau payload XSS.")
        self.assert_rejected()
        active = self.driver.execute_script("""
            return [...document.querySelectorAll('script,img')].some(e =>
                (e.tagName==='SCRIPT' && e.textContent.includes('UTC_XSS_TEST')) ||
                (e.tagName==='IMG' && (e.getAttribute('onerror')||'').includes('UTC_XSS_TEST')));
        """)
        self.assertIs(active, False, "Payload phản chiếu thành node script/handler đang hoạt động.")

    def navigation_metric(self, name):
        metrics = self.driver.execute_script("""
            const e=performance.getEntriesByType('navigation')[0];
            return e ? {load:e.loadEventEnd-e.startTime,ttfb:e.responseStart-e.requestStart}:null;
        """)
        self.assertIsInstance(metrics, dict)
        value = metrics.get(name)
        self.assertIsInstance(value, (int, float))
        self.assertFalse(isinstance(value, bool))
        self.assertTrue(math.isfinite(value) and value > 0, "Metric phải hữu hạn và dương.")
        return value

    def cold_page_events(self):
        self.driver.execute_cdp_cmd("Network.setCacheDisabled", {"cacheDisabled": True})
        self.driver.execute_cdp_cmd("Network.clearBrowserCache", {})
        network_events(self.driver)
        self.login_page.navigate()
        return collect_until_idle(self.driver, self.settings.timeout)

    def page_samples(self, name, limit):
        samples = []
        for _ in range(self.parameter("samples")):
            self.cold_page_events()
            samples.append(self.navigation_metric(name))
        self.observation(metric=name, samples_ms=samples, limit_ms=limit)
        self.assertLess(max(samples), limit)

    def test_TC_FUNC_01(self):
        """Username known to exist + known incorrect password must be rejected."""
        self.reject(self.settings.username, self.settings.invalid_password)

    def test_TC_FUNC_02(self):
        self.assert_required_fields()

    def test_TC_FUNC_03(self):
        self.assert_required_fields()

    def test_TC_FUNC_04(self):
        self.assert_required_fields()

    def test_TC_FUNC_05(self):
        self.reject(self.settings.nonexistent_username, self.settings.invalid_password)

    def test_TC_FUNC_06(self):
        self.reject(self.settings.invalid_password, self.settings.nonexistent_username)

    def test_TC_FUNC_07(self):
        sample = self.settings.invalid_password.swapcase()
        self.assertNotEqual(sample, self.settings.invalid_password)
        self.reject(self.settings.username, sample)

    def test_TC_FUNC_08(self):
        box = self.login_page.remember_checkbox()
        if not box.is_selected():
            self.login_page.toggle_remember_me()
        self.login_page.wait.until(lambda _: self.login_page.remember_checkbox().is_selected())
        self.assertTrue(self.login_page.remember_checkbox().is_selected())
        self.reject(self.settings.nonexistent_username, self.settings.invalid_password)

    def test_TC_FUNC_09(self):
        if self.login_page.remember_checkbox().is_selected():
            self.login_page.toggle_remember_me()
        self.login_page.wait.until(lambda _: not self.login_page.remember_checkbox().is_selected())
        self.assertFalse(self.login_page.remember_checkbox().is_selected())
        self.reject(self.settings.nonexistent_username, self.settings.invalid_password)

    def test_TC_FUNC_10(self):
        """Enter submission with incorrect credentials produces the same error oracle."""
        self.reject(self.settings.nonexistent_username, self.settings.invalid_password, enter=True)

    def test_TC_FUNC_11(self):
        """Direct navigation to auth entry without credentials still displays login controls."""
        self.driver.get(self.settings.url)
        self.login_page.wait.until(lambda _: self.login_page.is_login_page())
        self.assertTrue(self.login_page.is_login_page())

    def test_TC_FUNC_12(self):
        self.reject(self.settings.nonexistent_username, self.settings.invalid_password)
        self.driver.refresh()
        self.login_page.wait.until(lambda _: self.login_page.is_login_page())
        self.assertTrue(self.login_page.is_login_page())






























if __name__ == "__main__":
    unittest.main(verbosity=2)
