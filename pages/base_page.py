"""Shared browser interactions using explicit waits only."""
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class BasePage:
    def __init__(self, driver, timeout=10):
        self.driver = driver
        self.wait = WebDriverWait(driver, timeout)
    def open_url(self, url):
        self.driver.get(url)
    def find(self, locator):
        return self.wait.until(EC.visibility_of_element_located(locator))
    def find_clickable(self, locator):
        return self.wait.until(EC.element_to_be_clickable(locator))
    def find_all(self, locator):
        return self.driver.find_elements(*locator)
    def click(self, locator):
        self.find_clickable(locator).click()
    def type_text(self, locator, text):
        element = self.find_clickable(locator)
        element.clear()
        element.send_keys(text)
    def get_attribute(self, locator, name):
        return self.find(locator).get_attribute(name)
    def is_visible(self, locator):
        try:
            return self.find(locator).is_displayed()
        except TimeoutException:
            return False
    def is_present(self, locator):
        return bool(self.find_all(locator))
    def get_current_url(self):
        return self.driver.current_url
    def get_page_source(self):
        return self.driver.page_source
