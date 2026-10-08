"""Login actions and observations, without business assertions."""
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from pages.base_page import BasePage

class LoginPage(BasePage):
    USERNAME_INPUT = (By.NAME, "username")
    PASSWORD_INPUT = (By.NAME, "userpwd")
    LOGIN_BUTTON = (By.XPATH, "//input[@value='Đăng nhập']")
    EMAIL_LOGIN_LINK = (By.XPATH, "//a[contains(normalize-space(.), 'Đăng nhập bằng e-mail UTC')]")

    def __init__(self, driver, settings):
        super().__init__(driver, settings.timeout)
        self.settings = settings
    def navigate(self):
        self.open_url(self.settings.url)
        self.find(self.USERNAME_INPUT)
        self.find(self.PASSWORD_INPUT)
        self.find_clickable(self.LOGIN_BUTTON)
    def enter_username(self, text):
        self.type_text(self.USERNAME_INPUT, text)
    def enter_password(self, text):
        self.type_text(self.PASSWORD_INPUT, text)
    def click_login(self):
        self.click(self.LOGIN_BUTTON)
    def login(self, username, password, enter=False):
        self.enter_username(username)
        self.enter_password(password)
        if enter:
            self.find(self.PASSWORD_INPUT).send_keys(Keys.ENTER)
        else:
            self.click_login()
    def wait_for_success(self):
        locator = (By.CSS_SELECTOR, self.settings.success_selector)
        return self.wait.until(lambda d: next((e for e in d.find_elements(*locator)
            if e.is_displayed() and e.text.strip() == self.settings.success_text), False))
    def wait_for_error(self, text=None):
        expected = self.settings.error_text if text is None else text
        locator = (By.CSS_SELECTOR, self.settings.error_selector)
        return self.wait.until(lambda d: next((e for e in d.find_elements(*locator)
            if e.is_displayed() and e.text.strip() == expected), False))
    def is_login_page(self):
        return all(any(e.is_displayed() for e in self.find_all(locator))
            for locator in (self.USERNAME_INPUT, self.PASSWORD_INPUT, self.LOGIN_BUTTON))
    def remember_checkbox(self):
        element = self.wait.until(EC.presence_of_element_located(
            (By.CSS_SELECTOR, self.settings.remember_selector)))
        if element.get_attribute("type") != "checkbox":
            raise ValueError("remember_selector trong config.py phải trỏ đúng input[type=checkbox].")
        return element
    def toggle_remember_me(self):
        element = self.remember_checkbox()
        if element.is_displayed():
            element.click()
        else:
            label = self.driver.find_element(By.CSS_SELECTOR,
                f'label[for="{element.get_attribute("id")}"]')
            label.click()
        return element
    def login_form(self):
        username = self.find(self.USERNAME_INPUT)
        password = self.find(self.PASSWORD_INPUT)
        form = self.driver.execute_script("return arguments[0].form;", username)
        password_form = self.driver.execute_script("return arguments[0].form;", password)
        if form is None or form != password_form:
            raise ValueError("Không tìm thấy form chung cho username và password.")
        return form

    def logout(self):
        locator = (By.XPATH, "//a[contains(translate(@href,'LOGOUT','logout'),'logout') or "
                   "contains(normalize-space(.),'Đăng xuất')] | "
                   "//button[contains(normalize-space(.),'Đăng xuất')]")
        visible = [element for element in self.find_all(locator) if element.is_displayed() and element.is_enabled()]
        if len(visible) != 1:
            raise ValueError("Không xác định được duy nhất nút Đăng xuất trên trang đã login.")
        visible[0].click()
