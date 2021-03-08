import json
import logging
import math
import sys
import time
import traceback

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait

logger = logging.getLogger('ltji')


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


def set_text(scope, elt_id, value):
    """Set the value of a text element by id."""
    elt = scope.find_element_by_id(elt_id)
    if value:
        value = normalize_newlines(value)
        if elt.get_attribute('value') != value:
            if elt.tag_name == 'textarea':
                logger.debug("Setting text field %r", elt_id)
            else:
                logger.debug("Setting text field %r to value %r",
                             elt_id, value)
            elt.clear()
            elt.send_keys(value)
    else:
        if elt.get_attribute('value'):
            logger.debug("Clearing text field %r", elt_id)
            elt.clear()
    return elt


def select_by_value(select, value, log_msg, *log_args):
    """Set the value of a select element."""
    if select.first_selected_option.get_attribute('value') != value:
        logger.debug(log_msg, *log_args)
        select.select_by_value(value)


def set_select(scope, elt_id, value, name=None):
    """Set the value of a select element by id."""
    select = Select(scope.find_element_by_id(elt_id))
    if name:
        select_by_value(select, value,
                        "Setting selection %r to %r (%s)", elt_id, name, value)
    else:
        select_by_value(select, value,
                        "Setting selection %r to %s", elt_id, value)
    return select


def set_checkbox(scope, elt_id, selected):
    """Set the value of a checkbox element."""
    checkbox = scope.find_element_by_id(elt_id)
    if checkbox.is_selected() != selected:
        logger.debug("%s checkbox %r",
                     'Selecting' if selected else 'Deselecting', elt_id)
        checkbox.click()
    return checkbox


class LibraryThingDriver:
    def __init__(self, driver):
        self.driver = driver

    def wait_until(self, condition):
        """Wait up to 10 seconds for the given wait condition."""
        return WebDriverWait(self.driver, 10).until(condition)

    def login(self):
        """Log in to LibraryThing."""
        driver = self.driver
        driver.get('https://www.librarything.com/')
        # TODO: Cookies file should be specified via a command-line option
        try:
            with open('cookies.json') as f:
                cookies = json.load(f)
            for cookie in cookies:
                driver.add_cookie(cookie)
            return
        except Exception:
            pass

        print("Log in to LibraryThing, then press enter")
        input()

        with open('cookies.json', 'w') as f:
            json.dump(driver.get_cookies(), f)

    def set_author_role(self, scope, elt_id, text):
        """Set author role with the given element id."""
        select = Select(scope.find_element_by_id(elt_id))
        if not text:
            select_by_value(select, '', "Clearing author role %r", elt_id)
            return
        if select.first_selected_option.text == text:
            return  # Already selected
        available = {option.text for option in select.options[2:-2]}
        if text in available:
            logger.debug("Setting author role %r to %r", elt_id, text)
            select.select_by_visible_text(text)
        else:
            # Add new role
            logger.debug("Setting author role %r to custom value %r",
                         elt_id, text)
            select.select_by_value('xxxOTHERxxx')
            alert = self.wait_until(EC.alert_is_present())
            alert.send_keys(text)
            alert.accept()

    def set_author(self, scope, name_id, role_id, author):
        """Set author with the given name/role element ids."""
        author = author or {}
        set_text(scope, name_id, author.get('lf'))
        self.set_author_role(scope, role_id, author.get('role'))

    def set_other_authors(self, sauthors):
        """Set secondary authors."""
        sauthors = sauthors or []
        num_authors = len(sauthors)

        # Find relevant form elements
        parent = self.driver.find_element_by_id('bookedit_roles')
        num_rows = len(parent.find_elements_by_class_name('bookPersonName'))
        add_row_link = (parent.find_element_by_id('addPersonControl')
                        .find_element_by_tag_name('a'))

        idx = 0
        for idx, author in enumerate(sauthors):
            # Add rows as needed
            if idx >= num_rows:
                logger.debug("Clicking 'add another author'")
                add_row_link.click()
                self.wait_until(EC.presence_of_element_located(
                    (By.ID, f"person_name-{idx}")))
            self.set_author(
                parent, f'person_name-{idx}', f'person_role-{idx}', author)

        # Clear any extra rows
        for idx in range(num_authors, num_rows):
            self.set_author(
                parent, f'person_name-{idx}', f'person_role-{idx}', None)

    def set_tags(self, tags):
        """Set tags."""
        # TODO: Make extra tag configurable
        field = set_text(self.driver, 'form_tags',
                         ','.join((tags or []) + ['ltji']))
        defocus(field)  # Defocus text field to avoid autocomplete popup

    def set_rating(self, rating):
        """Set star rating."""
        star = math.ceil(rating) or 1  # Which star to click on
        target = str(int(rating * 2))
        parent = self.driver.find_element_by_xpath(
            '//*[@id="form_rating"]/../..')
        # Click up to 3 times until rating reaches desired value
        for _ in range(3):
            rating_elt = parent.find_element_by_id('form_rating')
            if rating_elt.get_attribute('value') == target:
                break
            star_elt = get_parent(rating_elt).find_element_by_css_selector(
                f':scope > img:nth-of-type({star})')
            logger.debug("Clicking rating star %d", star)
            star_elt.click()
            # Opacity is set to 0.3 while updating, then to 1 on success
            self.wait_until(
                lambda _: ('opacity', '1') in get_inline_styles(parent))
        else:
            rating_elt = parent.find_element_by_id('form_rating')
            if rating_elt.get_attribute('value') != target:
                raise RuntimeError("Failed to set rating")

    langs = {}  # Map of language strings to selection values

    def set_review_language(self, lang):
        """Set review language."""
        if not lang:
            return
        parent_elt = self.driver.find_element_by_id(
            'ajax_choose_reviewlanguage')
        # Check if correct language is already set
        if lang in self.langs:
            lang_elt = parent_elt.find_element_by_css_selector(
                'input[name="language"]')
            if lang_elt.get_attribute('value') == self.langs[lang]:
                return
        # Click button to change language
        logger.debug("Clicking review language 'change' button")
        parent_elt.find_element_by_css_selector('a').click()
        # Select language
        select = Select(self.wait_until(
            lambda _: parent_elt.find_element_by_css_selector('select')))
        if not self.langs:
            logger.debug("Populating language code map")
            for opt in select.options[3:]:
                self.langs[opt.text] = opt.get_attribute('value')
        if lang in self.langs:
            value = self.langs[lang]
            select_by_value(select, value,
                            "Selecting review language %r (%s)", lang, value)
        else:  # (blank)
            logger.debug("Selecting review language %r", lang)
            select.select_by_visible_text(lang)
        # Ensure "Make default" checkbox is unchecked
        cbox_elt = parent_elt.find_element_by_css_selector(
            'input[name="makedefault"]')
        if cbox_elt.is_selected():
            logger.debug("Deselecting review language 'Make default' checkbox")
            cbox_elt.click()

    custom_formats = {}  # Map from format code to select value

    def select_format(self, select, format_data):
        """Select media type by code value."""
        format_code = format_data['code']
        value = self.custom_formats.get(format_code, format_code)
        if value not in (opt.get_attribute('value') for opt in select.options):
            return False
        select_by_value(select, value,
                        "Selecting media type %r (%s)",
                        format_data['text'], value)
        return True

    def select_custom_format(self, select, format_data):
        """Select custom media type by name and parent code."""
        format_text = format_data['text']
        format_code = format_data['code']
        indent = '\u2003' * format_code.count('.')
        format_text_indented = f'{indent}{format_text}'
        pvalue, _ = format_code.rsplit('.', 1)
        popt = None
        for opt in select.options[5:]:
            if not popt:  # First scan list for parent format
                if opt.get_attribute('value') == pvalue:
                    popt = opt
            else:  # Then look for custom format under parent format
                # Get text with whitespace since we need to check the indent
                opt_text = opt.get_attribute("textContent")
                if not opt_text.startswith(indent):
                    break
                if opt_text == format_text_indented:
                    value = opt.get_attribute('value')
                    select_by_value(select, value,
                                    "Selecting media type %r (%s), "
                                    "nested under %r (%s)",
                                    format_text, value, popt.text, pvalue)
                    self.custom_formats[format_code] = value
                    return True
        return False

    def set_format(self, format_data):
        """Set media type."""
        parent = self.driver.find_element_by_id('mediatypemenus')
        complete = 'showmediatypeall' in get_class_list(parent)
        select = Select(parent.find_element_by_id(
            'mediatype_all' if complete else 'mediatype'))
        if not format_data:
            select_by_value(select, '', "Clearing media type")
            return
        if self.select_format(select, format_data):
            return
        if not complete:
            # Retry with complete list
            logger.debug("Selecting 'Show complete list' in media type menu")
            select.select_by_value('showcomplete')
            select = Select(parent.find_element_by_id('mediatype_all'))
            if self.select_format(select, format_data):
                return
        format_text = format_data['text']
        format_code = format_data['code']
        if '.X_m' in format_code and format_code not in self.custom_formats:
            # Try to find custom format by name
            if self.select_custom_format(select, format_data):
                return
            # Add new media type
            logger.debug("Selecting 'Add media' in media type menu")
            select.select_by_value('addmedia')
            set_text(parent, 'newmedia', format_text)
            set_select(parent, 'nestunder', format_code.rsplit('.', 1)[0])
        else:
            raise RuntimeError(f"Failed to set format {format_text!r} "
                               "({format_code})")

    def mr_add(self, scope, i, pfs, term):
        """Add a new fieldset to a muti-row section."""
        fsid = pfs.get_attribute('id')
        logger.debug("Adding %s %d", term, i+1)
        pfs.find_element_by_id(f'arb_{fsid}').click()
        return self.wait_until(
            lambda _: scope.find_element_by_css_selector(
                f':scope > fieldset:nth-of-type({i+1})'))

    def mr_del(self, scope, i, fs, term):
        """Delete a fieldset of a multi-row section."""
        fsid = fs.get_attribute('id')
        logger.debug("Removing %s %d", term, i+1)
        fs.find_element_by_id(f'arbm_{fsid}').click()
        self.wait_until(
            lambda _: ('display', 'none') in get_inline_styles(fs))

    def set_multirow(self, scope, items, set_fn, term):
        """Set multi-row data."""
        rows = scope.find_elements_by_tag_name('fieldset')
        num_items = len(items)
        num_rows = len(rows)
        # Populate data, adding new rows as needed
        row = None
        for i, item in enumerate(items):
            row = rows[i] if i < num_rows else self.mr_add(scope, i, row, term)
            set_fn(scope, i, row, item)
        # Delete extra rows
        for i in range(num_items, num_rows):
            self.mr_del(scope, i, rows[i], term)

    digits = frozenset('0123456789')
    rn_digits = frozenset('ivxlcdm')

    def guess_page_type(self, num):
        """Guess the page type from a given page number value."""
        num_chars = set(num.lower())
        if num_chars <= self.digits:
            return '1,2,3,...', '0'
        if num_chars <= self.rn_digits:
            return 'i,ii,iii,...', '1'
        return 'other', '4'

    def set_pagination(self, scope, i, fieldset, num):
        """Set a pagination item."""
        count_elt = fieldset.find_element_by_css_selector(
            'input[name="pagecount"]')
        type_elt = Select(fieldset.find_element_by_tag_name('select'))
        if not num:
            # Clear fieldset
            if count_elt.get_attribute('value'):
                logger.debug("Clearing pagination %d", i+1)
                count_elt.clear()
            return
        if count_elt.get_attribute('value') != num:
            logger.debug("Setting pagination %d to %r", i+1, num)
            count_elt.clear()
            count_elt.send_keys(num)
        pt_name, pt_value = self.guess_page_type(num)
        select_by_value(type_elt, pt_value,
                        "Setting type of pagination %d to %r (%s)",
                        i+1, pt_name, pt_value)

    def set_paginations(self, pages):
        """Set pagination."""
        parent = self.driver.find_element_by_id('bookedit_pages')
        pagenums = [p.strip() for p in (pages or '').split(';')]
        self.set_multirow(parent, pagenums, self.set_pagination, 'pagination')

    def get_dim_unit(self, dim):
        """Get the unit of a dimension."""
        _, unit = dim.split()
        if unit in ('inch', 'inches'):
            return 'inch', '0'
        if unit == 'cm':
            return 'cm', '1'
        raise ValueError(f"Unknown unit: {unit!r}")

    def set_dimension(self, scope, i, fs, hlt):
        """Set a dimension item."""
        fsid = fs.get_attribute('id')
        height, length, thickness = hlt
        # Set or clear dimension text fields
        for dim, pfx in ((height, 'pdh'), (length, 'pdl'), (thickness, 'pdt')):
            num, _ = dim.split() if dim else ('', None)
            set_text(fs, f'{pfx}_{fsid}', num)
        dim = height or length or thickness
        if dim:
            # Set dimension units
            unit, uvalue = self.get_dim_unit(dim)
            select = Select(fs.find_element_by_id(f'pdu_{fsid}'))
            select_by_value(select, uvalue,
                            "Setting unit of dimension %d to %r (%s)",
                            i+1, unit, uvalue)

    def set_dimensions(self, height, length, thickness):
        """Set dimensions."""
        parent = self.driver.find_element_by_id('bookedit_phys_dims')
        dimensions = [(height, length, thickness)]
        self.set_multirow(parent, dimensions, self.set_dimension, 'dimension')

    def get_weight_unit(self, unit):
        """Get a unit of weight."""
        if unit in ('pound', 'pounds'):
            return 'pounds', '0'
        if unit == 'kg':
            return 'kg', '1'
        raise ValueError(f"Unknown unit: {unit!r}")

    def set_weight(self, scope, i, fs, wstr):
        """Set a weight item."""
        weight_elt = fs.find_element_by_css_selector('input[name="weight"]')
        if not wstr:
            # Clear value field
            if weight_elt.get_attribute('value'):
                logger.debug("Clearing weight %d", i+1)
                weight_elt.clear()
            return
        # Set value field
        num, unit = wstr.split()
        if weight_elt.get_attribute('value') != num:
            logger.debug("Setting weight %d to %r", i+1, num)
            weight_elt.clear()
            weight_elt.send_keys(num)
        # Set unit
        uname, uvalue = self.get_weight_unit(unit)
        unit_elt = Select(fs.find_element_by_tag_name('select'))
        select_by_value(unit_elt, uvalue,
                        "Setting unit of weight %d to %r (%s)",
                        i+1, uname, uvalue)

    def set_weights(self, weight_str):
        """Set weights."""
        parent = self.driver.find_element_by_id('bookedit_weights')
        weights = [w.strip() for w in (weight_str or '').split(';')]
        self.set_multirow(parent, weights, self.set_weight, 'weight')

    def set_language(self, term, elt_id, lang, lang_code):
        """Set a language field specified by id."""
        parent = self.driver.find_element_by_id(elt_id)
        select = Select(parent.find_element_by_tag_name('select'))
        if not lang:
            select_by_value(select, '', "Clearing %s language", term)
            return
        if lang_code not in (opt.get_attribute('value')
                             for opt in select.options):
            # Didn't find the language code, try switching to all langauges
            logger.debug("Clicking 'show all languages' link")
            parent.find_element_by_css_selector('.bookEditHint > a').click()
            select = Select(self.wait_until(
                lambda wd: parent.find_element_by_tag_name('select')))
        select_by_value(select, lang_code,
                        "Selecting %s language %r (%s)", term, lang, lang_code)

    def set_reading_dates(self, date_started, date_finished):
        """Set reading dates."""
        parent = self.driver.find_element_by_id('startedfinished')
        rows = parent.find_elements_by_css_selector(
            'table.startedfinished > tbody > tr:not(.hidden)')
        set_text(parent, 'dr_start_1', date_started)
        set_text(parent, 'dr_end_1', date_finished)
        for i in range(1, len(rows)):
            set_text(parent, f'dr_start_{i+1}', None)
            set_text(parent, f'dr_end_{i+1}', None)

    def parse_from_where(self, scope):
        """Find the current "From where?" value and "change"/"edit" link."""
        outer_div = scope.find_element_by_css_selector(
            ':scope > div[class="location"]')
        # Three possible variants
        # - No location: text with one 'a' tag
        # - Free-text location: div containing one 'a' tag
        # - Venue: div containing two 'a' tags
        inner_div, = outer_div.find_elements_by_tag_name('div') or [None]
        if inner_div:
            anchors = inner_div.find_elements_by_tag_name('a')
            if len(anchors) == 1:
                # Free text location
                change_link = anchors[0]
                location = inner_div.text[:len(change_link.text) + 3]
            elif len(anchors) == 2:
                # Venue
                location = anchors[0].text
                change_link = anchors[1]
            else:
                raise RuntimeError("Unable to parse location field")
        else:
            # No location
            location = ''
            change_link = scope.find_element_by_tag_name('a')

        return location, change_link

    def open_location_popup(self, change_link):
        """Open the location editing popup."""
        logger.debug("Clicking location %r link", change_link.text)
        change_link.click()
        return self.wait_until(
            EC.presence_of_element_located((By.ID, "pickrecommendations")))

    def clear_location(self, popup):
        """Remove the current location value."""
        # Unfortunately this element has no distinguishing id or class
        # attributes so we have to specify it by position in the tree
        remove_link = popup.find_element_by_css_selector(
            ':scope > p:nth-of-type(3) > a')
        logger.debug("Clicking location remove link")
        remove_link.click()

    def select_already_used_location(self, popup, from_where):
        """Select a location from the already used location list."""
        locations = popup.find_elements_by_css_selector(
            '#locationlist > p > a:nth-of-type(1)')
        for anchor in locations:
            if anchor.text == from_where:
                logger.debug("Selecting already used venue %r", from_where)
                anchor.click()
                self.wait_until(EC.staleness_of(popup))
                return True
        return False

    def venue_search(self, popup, from_where):
        """Search for a venue by name."""
        logger.debug("Choosing 'Venue search' tab")
        popup.find_element_by_id('lbtabchromemenu1').click()
        form = popup.find_element_by_id('venuesearchform')
        search_field = form.find_element_by_css_selector('input[name="query"]')
        logger.debug("Populating venue search field")
        search_field.clear()
        search_field.send_keys('"')
        search_field.send_keys(from_where)
        search_field.send_keys('"')
        submit_button = form.find_element_by_css_selector(
            'input[name="Submit"]')
        logger.debug("Clicking search button")
        submit_button.click()
        results = popup.find_element_by_id('venuelist')
        self.wait_until(lambda _: 'updating' not in get_class_list(results))
        venues = results.find_elements_by_css_selector(
            ':scope > p > a:nth-of-type(1)')
        for anchor in venues:
            if anchor.text == from_where:
                logger.debug("Selecting venue %r", from_where)
                anchor.click()
                self.wait_until(EC.staleness_of(popup))
                return True
        return False

    def set_from_where_free_text(self, popup, from_where):
        """Enter a free-text location value."""
        logger.debug("Choosing 'Free text' tab")
        popup.find_element_by_id('lbtabchromemenu2').click()
        form = popup.find_element_by_id('freetextform')
        set_text(form, 'textareacomments', from_where)
        submit_button = form.find_element_by_css_selector(
            'input[name="Submit"]')
        logger.debug("Saving location")
        submit_button.click()

    def set_location(self, popup, from_where):
        """Use the location editing pop-up to set a location."""
        # Check if venue is already used
        if self.select_already_used_location(popup, from_where):
            return
        # Search for venue by name
        # TODO: Make this optional with config flag
        if self.search_for_venue(popup, from_where):
            return
        # Enter location as free text
        self.set_from_where_free_text(popup, from_where)

    def set_from_where(self, from_where):
        """Set the "From where?" field."""
        parent = self.driver.find_element_by_id('bookedit_datestarted')
        location, change_link = self.parse_from_where(parent)
        if not from_where:
            if location:
                popup = self.open_location_popup(change_link)
                self.clear_location(popup)
                self.wait_until(EC.staleness_of(popup))
            return
        if location != from_where:
            popup = self.open_location_popup(change_link)
            self.set_location(popup, from_where)
            self.wait_until(EC.staleness_of(popup))

    def set_physical_description(self, physical_description):
        """Set the physical description field."""
        try:
            set_text(self.driver, 'phys_summary', physical_description)
        except NoSuchElementException:
            # Add books form doesn't have this field
            # See https://www.librarything.com/topic/330379
            if physical_description:
                logger.warning("Unable to set physical description")

    def set_barcode(self, barcode):
        """Set the barcode."""
        parent = self.driver.find_element_by_id('bookedit_barcode')
        text_field = set_text(parent, 'item_inventory_barcode_1', barcode)
        # Barcode field has an onblur event to check for duplicate book
        defocus(text_field)
        # We don't currently use the warning but we need to wait for it to
        # appear or it may interfere with saving the form.
        warning = parent.find_element_by_id('barcode_warning_1')
        self.wait_until(lambda _: 'updating' not in get_class_list(warning))

    def set_bcid(self, bcid):
        """Set the BCID."""
        id1, id2 = bcid.split('-') if bcid else ('', '')
        set_text(self.driver, 'form_bcid_1', id1)
        set_text(self.driver, 'form_bcid_2', id2)

    def save_changes(self):
        """Save book edits."""
        html = self.driver.find_element_by_tag_name('html')
        self.driver.find_element_by_id('book_editTabTextSave2').click()
        self.wait_until(EC.staleness_of(html))

    def add_book(self, book_id, book_data):
        """Add a new book using the manual entry form."""
        logger.info("Adding book %s: %s", book_id, book_data['title'])

        self.driver.get('https://www.librarything.com/addnew.php')

        # Title
        set_text(self.driver, 'form_title', book_data['title'])

        # Sort character
        set_select(self.driver, 'sortcharselector',
                   # default selection has value "999"
                   book_data.get('sortcharacter', '999'))

        # Primary author
        authors = book_data.get('authors')
        pauthor = authors[0] if authors else None
        self.set_author(self.driver, 'form_authorunflip', 'person_role--1',
                        pauthor)

        # Tags
        self.set_tags(book_data.get('tags'))

        # Collections
        # TODO

        # Rating
        self.set_rating(book_data.get('rating', 0))

        # Review
        review = book_data.get('review')
        set_text(self.driver, 'form_review', review)
        self.set_review_language(book_data.get('reviewlang'))

        # Other authors
        sauthors = authors[1:] if authors else []
        self.set_other_authors(sauthors)

        # Format
        self.set_format(get_path(book_data, 'format', 0))

        # Publication details
        set_text(self.driver, 'form_date', book_data.get('date'))
        set_text(self.driver, 'form_publication', book_data.get('publication'))
        set_text(self.driver, 'form_ISBN', book_data.get('originalisbn'))

        # Physical description
        set_text(self.driver, 'numVolumes', book_data.get('volumes'))
        set_text(self.driver, 'form_copies', book_data.get('copies'))
        self.set_paginations(book_data.get('pages'))
        self.set_dimensions(book_data.get('height'), book_data.get('length'),
                            book_data.get('thickness'))
        self.set_weights(book_data.get('weight'))

        # Languages
        self.set_language('primary', 'bookedit_lang',
                          get_path(book_data, 'language', 0),
                          get_path(book_data, 'language_codeA', 0))
        self.set_language('secondary', 'bookedit_lang2',
                          get_path(book_data, 'language', 1),
                          get_path(book_data, 'language_codeA', 1))
        self.set_language('original', 'bookedit_lang_original',
                          get_path(book_data, 'originallanguage', 0),
                          get_path(book_data, 'originallanguage_codeA', -1))

        # Reading dates
        self.set_reading_dates(book_data.get('datestarted'),
                               book_data.get('dateread'))

        # Date acquired
        set_text(self.driver, 'form_datebought', book_data.get('dateacquired'))

        # From where
        self.set_from_where(book_data.get('fromwhere'))

        # Classification
        set_text(self.driver, 'form_lccallnumber',
                 get_path(book_data, 'lcc', 'code'))
        set_text(self.driver, 'form_dewey',
                 get_path(book_data, 'ddc', 'code', 0))
        set_text(self.driver, 'form_btc_callnumber',
                 get_path(book_data, 'callnumber', 0))

        # Comments
        set_text(self.driver, 'form_comments', book_data.get('comment'))
        set_text(self.driver, 'form_privatecomment',
                 book_data.get('privatecomment'))

        # Summary
        # TODO: Make these optional via command-line flags
        self.set_physical_description(book_data.get('physical_description'))
        set_text(self.driver, 'form_summary', book_data.get('summary'))

        # Barcode
        # TODO: Set book id as barcode if none specified
        # TODO: Check for existing book
        self.set_barcode(get_path(book_data, 'barcode', '1'))
        self.set_bcid(book_data.get('bcid'))

        # JSON does not correctly indicate whether a book is private
        if False:  # TODO: Command-line flag for this
            set_checkbox(self.driver, 'books_private', True)

        self.save_changes()


def main(data):
    """Import JSON data into LibraryThing."""
    success = False

    with webdriver.Firefox() as driver:
        # TODO: Improve error handling
        ltdriver = LibraryThingDriver(driver)
        try:
            ltdriver.login()
            for book_id, book_data in data.items():
                time.sleep(1)
                ltdriver.add_book(book_id, book_data)
            success = True
        except KeyboardInterrupt as exc:
            sys.stderr.writelines(traceback.format_exception_only(
                type(exc), exc))
        except Exception:
            traceback.print_exc()
        finally:
            print("Press enter to exit")
            input()

    return success


if __name__ == '__main__':
    with open(sys.argv[1]) as f:
        data = json.load(f)
    logging.basicConfig(level=logging.INFO)
    # TODO: Should be configurable
    logger.setLevel(logging.DEBUG)
    success = main(data)
    exit(0 if success else 1)
