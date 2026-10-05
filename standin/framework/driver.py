"""Browser driver factory. Only called when a test actually uses the browser."""

from __future__ import annotations

from selenium import webdriver
from selenium.webdriver.remote.webdriver import WebDriver

from framework.config import SuiteConfig


def create_driver(config: SuiteConfig) -> WebDriver:
    if config.browser == "firefox":
        firefox_options = webdriver.FirefoxOptions()
        if config.headless:
            firefox_options.add_argument("-headless")
        driver: WebDriver = webdriver.Firefox(options=firefox_options)
    elif config.browser == "chrome":
        chrome_options = webdriver.ChromeOptions()
        if config.headless:
            chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--window-size=1280,900")
        driver = webdriver.Chrome(options=chrome_options)
    else:
        raise ValueError(f"Unsupported browser: {config.browser}")
    driver.implicitly_wait(0)  # explicit waits only (see BasePage)
    return driver
