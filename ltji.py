"""Script to import JSON book data to LibraryThing using Selenium."""
import argparse
import json
import logging
import math
import re
from urllib.parse import urlparse

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select

from _common import (
    LibraryThingRobot,
    add_common_flags,
    defocus,
    get_class_list,
    get_inline_styles,
    get_parent,
    get_path,
    init_logging,
    main_loop,
    normalize_newlines,
    page_loaded_condition,
    parse_book_ids,
    parse_list,
)

parse_book_ids

logger = logging.getLogger('ltji')


def set_text_elt(elt, value, desc, *args):
    if value:
        value = normalize_newlines(value)
        if elt.get_attribute('value') != value:
            if elt.tag_name == 'textarea':
                logger.debug(f"Setting {desc}", *args)
            else:
                logger.debug(f"Setting {desc} to value %r", *args, value)
            elt.clear()
            elt.send_keys(value)
    else:
        if elt.get_attribute('value'):
            logger.debug(f"Clearing {desc}", *args)
            elt.clear()
            elt.send_keys('')


def set_text(scope, elt_id, value):
    """Set the value of a text element by id."""
    elt = scope.find_element_by_id(elt_id)
    set_text_elt(elt, value, "text field %r", elt_id)
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


class LibraryThingImporter(LibraryThingRobot):
    """Class to add books to LibraryThing."""

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
        tags = tags or []
        if self.config.tag:
            tags.append(self.config.tag)
        field = set_text(self.driver, 'form_tags', ", ".join(tags))
        defocus(field)  # Defocus text field to avoid autocomplete popup

    def parse_collections(self, scope):
        """Parse the list of collection checkboxes."""
        cbs = {}
        for div in scope.find_elements_by_css_selector('div.cb'):
            if not div.is_displayed():
                continue
            cb = div.find_element_by_css_selector('input[type="checkbox"]')
            label = div.find_element_by_css_selector('span.lab')
            cbs[label.text] = cb
        return cbs

    def show_all_collections(self, scope):
        buttons = scope.find_elements_by_css_selector(
            '.collectionListFooter .ltbtn')
        if len(buttons) != 2:
            raise RuntimeError(f"Unexpected button count: {len(buttons)}")
        show_button = buttons[0]
        sbpid = get_parent(show_button).get_attribute('id')
        assert sbpid.startswith('collsa_')
        cb_div = scope.find_element_by_id(sbpid[7:])
        logger.debug("Clicking 'show all' collections button")
        show_button.click()
        self.wait_until(
            lambda _: ('overflow', 'visible') in get_inline_styles(cb_div))

    def add_collections(self, scope, to_add):
        """Create new collections."""
        buttons = scope.find_elements_by_css_selector(
            '.collectionListFooter .ltbtn')
        if len(buttons) != 2:
            raise RuntimeError(f"Unexpected button count: {len(buttons)}")
        logger.debug("Clicking 'edit collections' button")
        buttons[1].click()
        lb_content = self.wait_for_lb()
        add_button = lb_content.find_element_by_id('addnewcollectionButton')
        for i, cname in enumerate(to_add, 1):
            logger.debug("Clicking 'Add new collection' button")
            add_button.click()
            self.wait_until(
                lambda _: len(lb_content.find_elements_by_css_selector(
                    'input[id^="name_-"]')) == i)
            elt = lb_content.find_element_by_css_selector(
                'input[id^="name_-"]')
            logger.debug("Setting new collection name to %r", cname)
            elt.clear()
            elt.send_keys(cname)
        save_button = lb_content.find_element_by_css_selector(
            ':scope > div:nth-of-type(1) > .ltbtn')
        logger.debug("Saving new collections")
        save_button.click()
        self.wait_until(EC.staleness_of(lb_content))
        self.wait_until(page_loaded_condition)
        for cname in to_add:
            logger.info("Created collection %r", cname)

    def set_collections(self, cnames):
        """Set collections."""
        cnames = set(cnames)
        for _ in range(2):
            # Collections section has the same id as tags, perhaps due to a
            # copy-paste error in the website source
            _, parent = self.driver.find_elements_by_id('bookedit_tags')
            cbs = self.parse_collections(parent)
            if not cnames <= cbs.keys():
                self.show_all_collections(parent)
                cbs = self.parse_collections(parent)
            if cnames <= cbs.keys():
                break
            to_add = cnames - cbs.keys()
            self.add_collections(parent, to_add)
        else:
            raise RuntimeError(f"Missing collections: {to_add!r}")
        assert cnames <= cbs.keys()
        for cname, cb in cbs.items():
            if cb.is_selected() != (cname in cnames):
                logger.debug("%s collection %r",
                             "Selecting" if cname in cnames else "Deselecting",
                             cname)
                cb.click()

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
        num_chars = set(num.casefold())
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
        height, length, thickness = hlt
        # Set or clear dimension text fields
        for dim, name in ((height, 'height'),
                          (length, 'length_dim'),
                          (thickness, 'thickness')):
            num, _ = dim.split() if dim else ('', None)
            # Element ids are different in add/edit book form
            elt = fs.find_element_by_css_selector(f'input[name="{name}"]')
            set_text_elt(elt, num, "dimension %d", i+1)
        dim = height or length or thickness
        if dim:
            # Set dimension units
            unit, uvalue = self.get_dim_unit(dim)
            select = Select(fs.find_element_by_css_selector(
                'select[name="d-unit"]'))
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
        if not lang or not lang_code:
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

    def set_original_language(self, book_data):
        oname = get_path(book_data, 'originallanguage', 0)
        if not oname:
            self.set_language('original', 'bookedit_lang_original', None, None)
            return
        # The original language code field contains the primary, secondary,
        # and original language codes, deduplicated. This makes it difficult to
        # figure out which code actually corresponds to the original language.
        #
        # First we check if the original language matches the primary or
        # secondary language. If so we can use the same language code.
        #
        # Otherwise, we use the last value in the list.
        for n, c in zip(book_data.get('language', ()),
                        book_data.get('language_codeA', ())):
            if oname == n:
                ocode = c
                break
        else:
            ocode = get_path(book_data, 'originallanguage_codeA', -1)
        self.set_language('original', 'bookedit_lang_original', oname, ocode)

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
        div = scope.find_element_by_css_selector(
            ':scope > div[class="location"]')
        anchors = div.find_elements_by_tag_name('a')
        if len(anchors) == 1:
            # Free text location or no location
            change_link = anchors[0]
            location = div.text[:-(len(change_link.text) + 2)].strip()
        elif len(anchors) == 2:
            # Venue
            location = anchors[0].text
            change_link = anchors[1]
        else:
            raise RuntimeError("Unable to parse location field")

        return location, change_link

    def open_location_popup(self, change_link):
        """Open the location editing popup."""
        logger.debug("Clicking location %r link", change_link.text)
        change_link.click()
        self.wait_for_lb()
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

    def search_for_venue(self, popup, from_where):
        """Search for a venue by name."""
        if self.config.no_venue_search:
            return False
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

    def set_physical_summary(self, physical_description):
        """Set the physical summary field."""
        if self.config.physical_summary == 'auto':
            physical_description = None
        try:
            set_text(self.driver, 'phys_summary', physical_description)
        except NoSuchElementException:
            # Add books form doesn't have this field
            # See https://www.librarything.com/topic/330379
            if physical_description:
                logger.warning("Unable to set physical description")

    def set_summary(self, summary):
        """Set the summary field."""
        if self.config.summary == 'auto':
            summary = None
        set_text(self.driver, 'form_summary', summary)

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

    def check_identifier(self, elt, expected, name):
        """Check if the given text element contains the expected value."""
        value = elt.get_attribute('value')
        if expected:
            if not value:
                logger.warning("Book has no %s value, expected %r",
                               name, expected)
            elif value != expected:
                logger.warning("Book has %s value %r, expected %r",
                               name, value, expected)
        else:
            if value:
                logger.warning("Book has %s value %r, expected no value")

    def check_immutable_identifiers(self, ean, upc, asin, lccn, oclc):
        """Check immutable identifier fields."""
        driver = self.driver
        self.check_identifier(driver.find_element_by_css_selector(
            'input[name="form_ean"]'), ean, 'EAN')
        # ASIN element has same name as UPC, probably a copy-paste error
        upc_elt, asin_elt = driver.find_elements_by_css_selector(
            'input[name="form_upc"]')
        self.check_identifier(upc_elt, upc, 'UPC')
        self.check_identifier(asin_elt, asin, 'ASIN')
        self.check_identifier(driver.find_element_by_css_selector(
            'input[name="form_lccn"]'), lccn, 'LCCN')
        self.check_identifier(driver.find_element_by_css_selector(
            'input[name="form_oclc"]'), oclc, 'OCLC')

    def save_changes(self):
        """Save book edits."""
        save_button = self.driver.find_element_by_id('book_editTabTextSave2')
        self.click_link(save_button, 'Clicking save button')

    def set_book_fields(self, book_id, book_data):
        """Populate the fields of the add/edit book form and save changes."""
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
        self.set_collections(book_data['collections'])

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
        self.set_original_language(book_data)

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
        self.set_physical_summary(book_data.get('physical_description'))
        self.set_summary(book_data.get('summary'))

        # Identifiers
        # TODO: Set book id as barcode if none specified
        # TODO: Check for existing book
        self.set_barcode(get_path(book_data, 'barcode', '1'))
        self.set_bcid(book_data.get('bcid'))
        self.check_immutable_identifiers(
            ean=get_path(book_data, 'ean', 0),
            upc=get_path(book_data, 'upc', 0),
            asin=book_data.get('asin'),
            lccn=book_data.get('lccn'),
            oclc=book_data.get('oclc'),
        )

        # JSON does not correctly indicate whether a book is private
        # We allow the user to specify this by a config flag
        if self.config.private:
            set_checkbox(self.driver, 'books_private', True)

        self.save_changes()

    def parse_source_list(self, scope):
        """Parse the list of available sources in the add books form."""
        rbs = {}
        for rb in scope.find_elements_by_css_selector(
                'input[type="radio"][name="libraryChoice"]'):
            name = get_parent(rb).find_element_by_tag_name('label').text
            rbs[name.casefold()] = rb, name
        return rbs

    # Maps of lowercase source names to link text
    featured_sources = {}
    all_sources = {}

    def parse_sources(self, section, sources):
        logger.debug("Parsing sources in section %r",
                     section.get_attribute('id'))
        for link in section.find_elements_by_css_selector('a[data-source-id]'):
            ltext = link.text
            sources[ltext.casefold()] = ltext

    def add_source_in_section(self, scope, section, sources, lsource):
        """Add a source in a given section of the add sources lightbox."""
        if not sources:
            self.parse_sources(section, sources)
        ltext = sources.get(lsource)
        if not ltext:
            return False
        link = section.find_element_by_link_text(ltext)
        if link.get_attribute('data-library-added') != '1':
            logger.debug("Adding source %r", ltext)
            link.click()
            self.wait_until(
                lambda _: link.get_attribute('data-library-added-new') == '1')
            self.wait_until(
                lambda _: 'updating' not in get_class_list(scope))
        return True

    def add_source_lb(self, scope, lb_content, lsource, have_overcat):
        # Short-circuit if the specified source is already known to be absent
        if (self.featured_sources and self.all_sources
                and lsource not in self.featured_sources
                and lsource not in self.all_sources):
            # Make sure Overcat is available
            if not have_overcat:
                featured_section = lb_content.find_element_by_id(
                    'section_featured')
                self.add_source_in_section(
                    scope, featured_section, self.featured_sources, 'overcat')
            return False
        # Look in featured sources section
        featured_section = lb_content.find_element_by_id('section_featured')
        if self.add_source_in_section(
                scope, featured_section, self.featured_sources, lsource):
            return True
        # Look in all sources section
        allsources_section = lb_content.find_element_by_id(
            'section_allsources')
        logger.debug("Clicking 'All sources' link")
        lb_content.find_element_by_id('menu_allsources').click()
        self.wait_until(EC.visibility_of(allsources_section))
        if self.add_source_in_section(
                scope, allsources_section, self.all_sources, lsource):
            return True
        # Didn't find source; make sure Overcat is available
        if not have_overcat:
            logger.debug("Clicking 'Featured' link")
            lb_content.find_element_by_id('menu_featured').click()
            self.wait_until(EC.visibility_of(featured_section))
            self.add_source_in_section(
                scope, featured_section, self.featured_sources, 'overcat')
        return False

    def add_source(self, scope, lsource, have_overcat):
        """Add a source."""
        add_link = scope.find_element_by_css_selector(
            ':scope > div > a:nth-of-type(2)')
        logger.debug("Opening add source popup")
        add_link.click()
        lb_content = self.wait_for_lb()
        found = self.add_source_lb(scope, lb_content, lsource, have_overcat)
        # Close lightbox
        logger.debug("Closing add source popup")
        self.driver.find_element_by_id('LT_LT_closebutton').click()
        self.wait_until(EC.invisibility_of_element(lb_content))
        return found

    def select_source(self, source):
        lsource = source.casefold()
        parent = self.driver.find_element_by_id('yourlibrarylist')
        rbs = self.parse_source_list(parent)
        found = lsource in rbs
        if not found:
            found = self.add_source(parent, lsource, 'overcat' in rbs)
            parent = self.driver.find_element_by_id('yourlibrarylist')
            self.wait_until(
                lambda _: 'updating' not in get_class_list(parent))
            rbs = self.parse_source_list(parent)
        if found:
            rb, rb_name = rbs[lsource]
        else:
            logger.debug("Source %r not found, trying Overcat", source)
            rb, rb_name = rbs['overcat']
        if not rb.is_selected():
            logger.debug("Selecting source %r", rb_name)
            rb.click()
        return found

    # Map from identifier names to book data paths
    id_keys = {
        'ean': ('ean', 0),
        'upc': ('upc', 0),
        'asin': 'asin',
        'lccn': 'lccn',
        'oclc': 'oclc',
        'isbn': 'originalisbn',
    }

    def get_identifier(self, book_data):
        """Get a search identifier for a book."""
        for identifier in self.config.search_by:
            key_or_path = self.id_keys[identifier]
            if isinstance(key_or_path, str):
                value = book_data.get(key_or_path)
            else:
                value = get_path(book_data, *key_or_path)
            if value:
                return identifier, value
        return None, None

    def add_from_source(self, book_id, book_data, source):
        """Add a new book from the given source."""
        self.driver.get('https://www.librarything.com/addbooks')
        identifier, value = self.get_identifier(book_data)
        if not value:
            return False
        self.select_source(source)
        search_elt = self.driver.find_element_by_id('form_find')
        logger.debug("Setting search field to value %r (%s)",
                     value, identifier)
        search_elt.clear()
        search_elt.send_keys(value)
        # Set tag here so book will be locatable in case of editing failure
        if self.config.tag:
            tags_elt = self.driver.find_element_by_css_selector(
                'input[name="form_tags"]')
            set_text_elt(tags_elt, self.config.tag, "tags to add")
            defocus(tags_elt)
        logger.debug("Clicking search button")
        self.driver.find_element_by_id('search_btn').click()
        self.wait_until(EC.invisibility_of_element_located(
            (By.ID, 'addbooks_ajax_status')), 30)
        bookframe = self.driver.find_element_by_id('bookframe')
        self.wait_until(
            lambda _: bookframe.find_element_by_css_selector('.resultsfrom'))
        # TODO: Scan results for match rather than just choosing first one?
        # TODO: Fallback if not found
        first_result = bookframe.find_element_by_css_selector(
            'td.result > div.addbooks_title > a')
        logger.debug("Clicking search result %r", first_result.text)
        first_result.click()
        self.wait_until(EC.invisibility_of_element_located(
            (By.ID, 'addbooks_ajax_status')))
        bookframe = self.driver.find_element_by_id('bookframe')
        self.wait_until(
            lambda _: ('opacity', '1') in get_inline_styles(bookframe))
        last_added_book = self.driver.find_element_by_css_selector(
            '#bookframe .booklist .book')
        edit_link = last_added_book.find_element_by_css_selector(
            '.icons > div:nth-of-type(1) > a')
        self.click_link(edit_link, "Clicking edit link for last added book")
        self.set_book_fields(book_id, book_data)
        return True

    def add_manually(self, book_id, book_data):
        """Add a new book using the manual entry form."""
        self.driver.get('https://www.librarything.com/addnew.php')
        self.set_book_fields(book_id, book_data)

    book_url_path_re = re.compile('/work/([0-9]+)/book/([0-9]+)')

    def check_work_id(self, expected_work_id):
        """Check the work id of a newly created book."""
        assert (self.driver.current_url ==
                'https://www.librarything.com/addbooks')
        self.wait_until(EC.visibility_of_element_located((By.ID, 'bookframe')))
        last_added_book = self.driver.find_element_by_css_selector(
            '#bookframe .booklist .book')
        anchor = last_added_book.find_element_by_css_selector(
            ':scope > h2 > a')
        path = urlparse(anchor.get_attribute('href')).path
        match = self.book_url_path_re.match(path)
        work_id = match.group(1)
        book_id = match.group(2)
        logger.info("Created book with id %s, work id %s", book_id, work_id)
        if expected_work_id and work_id != expected_work_id:
            logger.warning("Book id %s has work id %s, expected %s",
                           book_id, work_id, expected_work_id)

    def add_book(self, book_id, book_data):
        """Add a new book."""
        logger.info("Adding book %s: %s", book_id, book_data['title'])
        source = book_data.get('source')
        added = False
        if source and source != 'manual entry' and not config.no_source:
            added = self.add_from_source(book_id, book_data, source)
        if not added:
            self.add_manually(book_id, book_data)
        self.check_work_id(book_data.get('workcode'))


def main(config, data):
    """Import JSON data into LibraryThing."""

    def init_fn(driver):
        ltrobot = LibraryThingImporter(config, driver)
        ltrobot.login()
        return ltrobot

    return main_loop(config, data, 'import', init_fn,
                     LibraryThingImporter.add_book)


def parse_search_by(config):
    search_by = []
    for identifier in parse_list(config.search_by):
        if identifier not in LibraryThingImporter.id_keys:
            raise ValueError("Invalid search identifier: %r", identifier)
        search_by.append(identifier.lower())
    config.search_by = search_by or list(LibraryThingImporter.id_keys)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    add_common_flags(parser)
    parser.add_argument('-s', '--no-source', action='store_true',
                        help="Ignore source field, add books manually")
    parser.add_argument('--search-by', help="Comma-separated list of search "
                        "identifiers to use when adding from source, in "
                        "priority order. Valid values: "
                        f"{', '.join(LibraryThingImporter.id_keys)}")
    parser.add_argument('-t', '--tag',
                        help="Tag to add to all imported books.")
    parser.add_argument('--no-venue-search', action='store_true',
                        help="Don't search for venues when setting the "
                        "'From where?' field")
    parser.add_argument('--physical-summary', choices=('auto', 'json'),
                        default='auto', help="How to set the 'Physical "
                        "summary' field: 'auto', leave blank for LibraryThing "
                        "to auto-generate; 'json', use the value from the "
                        "JSON data")
    parser.add_argument('--summary', choices=('auto', 'json'),
                        default='auto', help="How to set the 'Summary' field: "
                        "'auto', leave blank for LibraryThing to auto-"
                        "generate; 'json', use the value from the JSON data")
    parser.add_argument('-p', '--private', action='store_true',
                        help="Create private books")
    parser.add_argument('file', help="File containing JSON book data.")
    config = parser.parse_args()
    init_logging(config, 'ltji')
    parse_book_ids(config)
    parse_search_by(config)
    with open(config.file) as f:
        data = json.load(f)
    success = main(config, data)
    exit(0 if success else 1)
