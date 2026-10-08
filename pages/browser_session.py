"""Chrome session and network observations used by browser testcase assertions."""
import json
import time

from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from pages.login_page import LoginPage


def start_browser(settings, profile=None):
    options = webdriver.ChromeOptions()
    options.page_load_strategy = "eager"
    options.add_experimental_option("excludeSwitches", ["enable-logging"])
    if settings.headless:
        options.add_argument("--headless=new")
    if profile:
        options.add_argument(f"--user-data-dir={profile}")
        options.add_argument("--disable-session-crashed-bubble")
    options.add_argument("--window-size=1366,768")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    driver = webdriver.Chrome(options=options)
    try:
        driver.set_page_load_timeout(settings.timeout)
        driver.set_script_timeout(settings.timeout)
        driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        driver.quit()
        raise
    return driver, LoginPage(driver, settings)


def network_events(driver):
    return [json.loads(entry["message"])["message"] for entry in driver.get_log("performance")]


def requests(events):
    return [event["params"]["request"] for event in events if event["method"] == "Network.requestWillBeSent"]


def responses(events):
    return [event["params"]["response"] for event in events if event["method"] == "Network.responseReceived"]


def collect_until_idle(driver, timeout):
    events = []
    last_activity = time.monotonic()
    def idle(_):
        nonlocal last_activity
        batch = network_events(driver)
        events.extend(batch)
        if any(event["method"].startswith("Network.") for event in batch):
            last_activity = time.monotonic()
        return time.monotonic() - last_activity >= 0.5
    WebDriverWait(driver, timeout).until(idle)
    return events
