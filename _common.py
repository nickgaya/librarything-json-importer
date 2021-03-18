"""Common classes and functions for LibraryThing automation scripts."""
import json
import logging
import os.path
import time
from contextlib import nullcontext
from urllib.parse import urlparse

from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException, NoSuchWindowException)
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logger = None


def get_path(obj, *keys):
    """Extract a value from a JSON data structure."""
    for key in keys:
        if not obj:
            return obj
        if isinstance(key, int):
            try:
                obj = obj[key]
            except IndexError:
                return None
        elif isinstance(key, str):
            obj = obj.get(key)
        else:
            raise TypeError(f"Invalid key type: {type(key).__qualname__}")
    return obj


def normalize_newlines(s):
    """Normalize line breaks in a string."""
    return s.replace('\r\n', '\n').replace('\r', '\n') if s else s


def get_driver(scope):
    """Return a WebDriver object given a driver or element."""
    return scope if isinstance(scope, WebDriver) else scope.parent


def get_class_list(elt):
    """Return the list of CSS classes of an element."""
    value = elt.get_attribute('class')
    return value.split() if value else []


def get_inline_styles(elt):
    """Yield the (key, value) pairs of an element's style attribute."""
    value = elt.get_attribute('style')
    if not value:
        return
    for item in value.split(';'):
        if item:
            key, value = item.split(':', 1)
            yield key.strip(), value.strip()


def get_parent(elt):
    """Get the parent of a given element."""
    return elt.find_element_by_xpath('./..')


def defocus(elt):
    """Remove focus from a given element."""
    get_driver(elt).execute_script("arguments[0].blur()", elt)


def page_loaded_condition(driver):
    """Expected condition for page load."""
    return driver.execute_script("return document.readyState") == 'complete'


def try_find(find_fn, *args, **kwargs):
    """Try to find an element, or return None."""
    try:
        return find_fn(*args, **kwargs)
    except NoSuchElementException:
        return None


class LibraryThingRobot:
    """Base class for automation of LibraryThing flows."""

    def __init__(self, config, driver):
        self.config = config
        self.driver = driver

    def wait_until(self, condition, seconds=10):
        """Wait up to 10 seconds for the given wait condition."""
        return WebDriverWait(self.driver, seconds).until(condition)

    def wait_for_lb(self):
        """Wait for the lightbox to appear and load."""
        lb = self.wait_until(
            EC.visibility_of_element_located((By.ID, 'LT_LB')))
        loading = lb.find_element_by_id('LT_LB_loading')
        self.wait_until(EC.invisibility_of_element(loading))
        return lb.find_element_by_id('LT_LB_content')

    def close_lb(self, lb_content, message, *args):
        """Click the lightbox close button."""
        lb_close = self.driver.find_element_by_css_selector(
            '#LT_LT_closebutton > a')
        logger.debug(message, *args)
        lb_close.click()
        self.wait_until(EC.invisibility_of_element(lb_content))

    def wait_until_location_stable(self, elt, seconds=30):
        """Attempt to wait until an element's location is stable."""
        prev_location = None
        location = elt.location
        deadline = time.monotonic() + seconds
        while location != prev_location:
            if time.monotonic() > deadline:
                raise TimeoutError("Element location failed to stabilize")
            time.sleep(1)
            location, prev_location = elt.location, location

    def click_link(self, elt, message, *args):
        """Click an element and wait for a new page to load."""
        html = self.driver.find_element_by_tag_name('html')
        logger.debug(message, *args)
        elt.click()
        self.wait_until(EC.staleness_of(html))
        self.wait_until(page_loaded_condition, 30)

    def user_alert(self, message):
        """Display an alert to the user."""
        self.driver.execute_script("alert(arguments[0])", message)
        WebDriverWait(self.driver, 60).until_not(EC.alert_is_present())

    def close_gdpr_banner(self):
        """Dismiss GDPR banner if present."""
        self.wait_until(page_loaded_condition)
        try:
            banner = self.driver.find_element_by_id('gdpr_notice')
        except NoSuchElementException:
            return
        logger.debug("Clicking GDPR banner 'I Agree' button")
        banner.find_element_by_id('gdpr_closebutton').click()
        self.wait_until(EC.invisibility_of_element(banner))

    def login(self):
        """Log in to LibraryThing."""
        driver = self.driver
        cookies_file = self.config.cookies_file
        driver.get('https://www.librarything.com')
        if cookies_file and os.path.exists(cookies_file):
            logger.debug("Loading cookies from %r", cookies_file)
            with open(cookies_file) as f:
                cookies = json.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
            driver.get('https://www.librarything.com/home')
        if not urlparse(driver.current_url).path == '/home':
            self.user_alert("[LTJI] Log in and complete robot check")
            logger.debug("Waiting for user login")
            self.wait_until(
                lambda wd: urlparse(wd.current_url).path == '/home', 180)
        logger.debug("Login successful")
        self.close_gdpr_banner()
        if cookies_file:
            with open(cookies_file, 'w') as f:
                json.dump(driver.get_cookies(), f)
            logger.debug("Saved cookies to %r", cookies_file)


# Map from browser name to WebDriver class
DRIVERS = {
    'firefox': webdriver.Firefox,
    'chrome': webdriver.Chrome,
    'ie': webdriver.Ie,
    'edge': webdriver.Edge,
    'opera': webdriver.Opera,
    'safari': webdriver.Safari,
}


def iter_books(data, book_ids):
    """Iterate over the specified book data."""
    if book_ids:
        for book_id in book_ids:
            if book_id in data:
                yield book_id, data[book_id]
            else:
                logger.warning("Book id %r not found in data", book_id)
    else:
        yield from data.items()


def main_loop(config, data, verb, init_fn, process_fn):
    """Main processing loop of script."""
    success = False
    processed = 0
    errors = 0
    with DRIVERS[config.browser]() as driver:
        try:
            ltrobot = init_fn(driver)
            with (open(config.errors_file, 'w') if config.errors_file
                  else nullcontext()) as ef:
                for book_id, book_data in iter_books(data, config.book_ids):
                    time.sleep(1)
                    try:
                        process_fn(ltrobot, book_id, book_data)
                    except NoSuchWindowException:
                        raise  # Fatal error, abort
                    except Exception:
                        logger.warning("Failed to %s book %s", verb, book_id,
                                       exc_info=True)
                        if ef:
                            ef.write(book_id)
                            ef.write('\n')
                            ef.flush()
                        errors += 1
                        if config.debug_mode:
                            input("\aPress enter to continue: ")
                    else:
                        processed += 1
            logger.info("%d books %sed, %d errors (%d total)",
                        processed, verb, errors, processed + errors)
            success = True
        except KeyboardInterrupt:
            logger.info("Interrupted, exiting")
        except Exception:
            logger.error("%s failed with exception", verb.capitalize(),
                         exc_info=True)
        finally:
            if config.debug_mode:
                input("\aPress enter to exit: ")

    return success


def add_common_flags(parser):
    """Add basic flags to the argument parser."""
    parser.add_argument('-b', '--browser', choices=DRIVERS,
                        default='firefox', help="Browser to use")
    parser.add_argument('-c', '--cookies-file',
                        help="File to save/load login cookies")
    parser.add_argument('-e', '--errors-file', help="Output file for list of "
                        "book ids with processing errors")
    parser.add_argument('-i', '--book-ids',
                        help="Comma-separated list of book ids to process, or "
                        "@filename to read ids from file")
    parser.add_argument('-v', '--verbose', action='store_true',
                        help="Log additional debugging information.")
    parser.add_argument('-d', '--debug-mode', action='store_true',
                        help="Pause for confirmation after errors and at exit")


def init_logging(config, name):
    """Configure logging."""
    global logger
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(name)
    if config.verbose:
        logger.setLevel(logging.DEBUG)


def parse_list(value):
    """Parse a list of values separated by commas or whitespace."""
    return [w for v in value.split(',') for w in v.split()] if value else []


def parse_book_ids(config):
    """Parse list of book ids or read from file."""
    if config.book_ids is not None:
        if config.book_ids.startswith('@'):
            with open(config.book_ids[1:]) as f:
                config.book_ids = f.read()
        config.book_ids = parse_list(config.book_ids)
        if not config.book_ids:
            raise ValueError("Empty list of book ids")
