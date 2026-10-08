"""Edit test configuration directly here; no .env or environment variables are used."""
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent

@dataclass(frozen=True)
class Settings:
    url: str = "https://vanphongdientu.utc.edu.vn/"
    timeout: float = 10
    run_browser: bool = True
    run_security: bool = True
    headless: bool = False

    username: str = "huongnt"
    password: str = "123456@utc"
    invalid_password: str = "wrong_password_123"
    nonexistent_username: str = "nonexistent_user_9999"

    success_selector: str = ".user-info, .profile, .fullname, .header-user, #user"
    success_text: str = "huongnt"
    protected_url: str = "https://vanphongdientu.utc.edu.vn/"
    error_selector: str = "div.error"
    error_text: str = "Tài khoản hoặc mật khẩu không đúng."
    remember_selector: str = "#persistent"

    username_trim: str = "reject"
    page_load_limit_ms: float | None = 5000.0
    ttfb_limit_ms: float | None = 3000.0
    allure_command: str = "allure"

    def __post_init__(self):
        if urlparse(self.url).scheme not in {"http", "https"} or not urlparse(self.url).netloc:
            raise ValueError("config.py: url phải là URL HTTP(S) đầy đủ.")
        for name in ("timeout", "page_load_limit_ms", "ttfb_limit_ms"):
            value = getattr(self, name)
            if value is None and name != "timeout":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(f"config.py: {name} phải là số dương hữu hạn.")


SETTINGS = Settings()
