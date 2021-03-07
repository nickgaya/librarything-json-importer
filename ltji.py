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


def get_driver(scope):
    return scope if isinstance(scope, WebDriver) else scope.parent


def get_class_list(elt):
    value = elt.get_attribute('class')
    return value.split() if value else []


def get_parent(elt):
    return elt.find_element_by_xpath('./..')


def focus(elt):
    get_driver(elt).execute_script("arguments[0].focus()", elt)


def defocus(elt):
    get_driver(elt).execute_script("arguments[0].blur()", elt)


def login(driver):
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


def set_text(scope, elt_id, value):
    elt = scope.find_element_by_id(elt_id)
    if value:
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
    if select.first_selected_option.get_attribute('value') != value:
        logger.debug(log_msg, *log_args)
        select.select_by_value(value)


def set_select(scope, elt_id, value, name=None):
    select = Select(scope.find_element_by_id(elt_id))
    if name:
        select_by_value(select, value,
                        "Setting selection %r to %r (%s)", elt_id, name, value)
    else:
        select_by_value(select, value,
                        "Setting selection %r to %s", elt_id, value)
    return select


def set_checkbox(scope, elt_id, selected):
    checkbox = scope.find_element_by_id(elt_id)
    if checkbox.is_selected() != selected:
        logger.debug("%s checkbox %r",
                     'Selecting' if selected else 'Deselecting', elt_id)
        checkbox.click()
    return checkbox


def set_author_role(scope, elt_id, text):
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
        logger.debug("Setting author role %r to custom value %r", elt_id, text)
        select.select_by_value('xxxOTHERxxx')
        time.sleep(0.1)
        alert = get_driver(scope).switch_to.alert
        alert.send_keys(text)
        alert.accept()


def set_author(scope, name_id, role_id, author):
    author = author or {}
    set_text(scope, name_id, author.get('lf'))
    set_author_role(scope, role_id, author.get('role'))


def set_other_authors(driver, sauthors):
    sauthors = sauthors or []
    num_authors = len(sauthors)

    # Find relevant form elements
    parent = driver.find_element_by_id('bookedit_roles')
    num_rows = len(parent.find_elements_by_class_name('bookPersonName'))
    add_row_link = (parent.find_element_by_id('addPersonControl')
                    .find_element_by_tag_name('a'))

    idx = 0
    for idx, author in enumerate(sauthors):
        # Add rows as needed
        if idx >= num_rows:
            logger.debug("Clicking 'add another author'")
            add_row_link.click()
            time.sleep(0.1)
        set_author(parent, f'person_name-{idx}', f'person_role-{idx}', author)

    # Clear any extra rows
    for idx in range(num_authors, num_rows):
        set_author(parent, f'person_name-{idx}', f'person_role-{idx}', None)


def set_tags(driver, tags):
    # TODO: Make extra tag configurable
    field = set_text(driver, 'form_tags', ','.join((tags or []) + ['ltji']))
    defocus(field)  # Defocus text field to avoid/dismiss autocomplete popup


def set_rating(driver, rating):
    star = math.ceil(rating) or 1  # Which star to click on
    target = str(int(rating * 2))
    # Click up to 3 times until rating reaches desired value
    for _ in range(3):
        rating_elt = driver.find_element_by_id('form_rating')
        if rating_elt.get_attribute('value') == target:
            break
        star_elt = get_parent(rating_elt).find_element_by_css_selector(
            f':scope > img:nth-of-type({star})')
        logger.debug("Clicking rating star %d", star)
        star_elt.click()
        time.sleep(0.1)
    else:
        rating_elt = driver.find_element_by_id('form_rating')
        if rating_elt.get_attribute('value') != target:
            raise RuntimeError("Failed to set rating")


langs = {}  # Map of language strings to selection values


def set_review_language(driver, lang):
    if not lang:
        return
    parent_elt = driver.find_element_by_id('ajax_choose_reviewlanguage')
    # Check if correct language is already set
    if lang in langs:
        lang_elt = parent_elt.find_element_by_css_selector(
            'input[name="language"]')
        if lang_elt.get_attribute('value') == langs[lang]:
            return
    # Click button to change language
    logger.debug("Clicking review language 'change' button")
    parent_elt.find_element_by_css_selector('a').click()
    time.sleep(0.1)
    # Select language
    # select = Select(parent_elt.find_element_by_css_selector('select'))
    select = Select(WebDriverWait(driver, 10).until(
        lambda wd: parent_elt.find_element_by_css_selector('select')))
    if not langs:
        logger.debug("Populating language code map")
        for opt in select.options[3:]:
            langs[opt.text] = opt.get_attribute('value')
    if lang in langs:
        value = langs[lang]
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


def select_format(select, format_data):
    format_code = format_data['code']
    value = custom_formats.get(format_code, format_code)
    if value not in (opt.get_attribute('value') for opt in select.options):
        return False
    select_by_value(select, value,
                    "Selecting media type %r (%s)", format_data['text'], value)
    return True


def select_custom_format(select, format_data):
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
                custom_formats[format_code] = value
                return True
    return False


def set_format(driver, format_data):
    parent = driver.find_element_by_id('mediatypemenus')
    complete = 'showmediatypeall' in get_class_list(parent)
    select = Select(parent.find_element_by_id(
        'mediatype_all' if complete else 'mediatype'))
    if not format_data:
        select_by_value(select, '', "Clearing media type")
        return
    if select_format(select, format_data):
        return
    if not complete:
        # Retry with complete list
        logger.debug("Selecting 'Show complete list' in media type menu")
        select.select_by_value('showcomplete')
        time.sleep(0.1)
        select = Select(parent.find_element_by_id('mediatype_all'))
        if select_format(select, format_data):
            return
    format_text = format_data['text']
    format_code = format_data['code']
    if '.X_m' in format_code and format_code not in custom_formats:
        # Try to find custom format by name
        if select_custom_format(select, format_data):
            return
        # Add new media type
        logger.debug("Selecting 'Add media' in media type menu")
        select.select_by_value('addmedia')
        time.sleep(0.1)
        set_text(parent, 'newmedia', format_text)
        set_select(parent, 'nestunder', format_code.rsplit('.', 1)[0])
    else:
        raise RuntimeError(f"Failed to set format {format_text!r} "
                           "({format_code})")


def set_multirow(scope, items, rows, set_fn, add_fn, delete_fn):
    num_items = len(items)
    num_rows = len(rows)
    # Populate data, adding new rows as needed
    row = None
    for i, item in enumerate(items):
        row = rows[i] if i < num_rows else add_fn(scope, i, row)
        set_fn(scope, i, row, item)
    # Delete extra rows
    for i in range(num_items, num_rows):
        delete_fn(scope, i, rows[i])


def set_multirow_fs(scope, items, set_fn, term):
    def add_fs(scope, i, fs):
        fsid = fs.get_attribute('id')
        logger.debug("Adding %s %d", term, i+1)
        fs.find_element_by_id(f'arb_{fsid}').click()
        time.sleep(0.1)
        return WebDriverWait(get_driver(scope), 10).until(
            lambda wd: scope.find_element_by_css_selector(
                f':scope > fieldset:nth-of-type({i+1})'))

    def del_fs(scope, i, fs):
        fsid = fs.get_attribute('id')
        logger.debug("Removing %s %d", term, i+1)
        fs.find_element_by_id(f'arbm_{fsid}').click()
        time.sleep(0.1)

    rows = scope.find_elements_by_tag_name('fieldset')
    set_multirow(scope, items, rows, set_fn, add_fs, del_fs)


digits = frozenset('0123456789')
rn_digits = frozenset('ivxlcdm')


def guess_page_type(num):
    num_chars = set(num.lower())
    if num_chars <= digits:
        return '1,2,3,...', '0'
    if num_chars <= rn_digits:
        return 'i,ii,iii,...', '1'
    return 'other', '4'


def set_pagination(scope, i, fieldset, num):
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
    pt_name, pt_value = guess_page_type(num)
    select_by_value(type_elt, pt_value,
                    "Setting type of pagination %d to %r (%s)",
                    i+1, pt_name, pt_value)


def set_paginations(driver, pages):
    parent = driver.find_element_by_id('bookedit_pages')
    pagenums = [p.strip() for p in (pages or '').split(';')]
    set_multirow_fs(parent, pagenums, set_pagination, 'pagination')


def get_dim_unit(dim):
    _, unit = dim.split()
    if unit in ('inch', 'inches'):
        return 'inch', '0'
    if unit == 'cm':
        return 'cm', '1'
    raise ValueError(f"Unknown unit: {unit!r}")


def set_dimension(scope, i, fs, hlt):
    fsid = fs.get_attribute('id')
    height, length, thickness = hlt
    # Set or clear dimension text fields
    for dim, pfx in ((height, 'pdh'), (length, 'pdl'), (thickness, 'pdt')):
        num, _ = dim.split() if dim else ('', None)
        set_text(fs, f'{pfx}_{fsid}', num)
    dim = height or length or thickness
    if dim:
        # Set dimension units
        unit, uvalue = get_dim_unit(dim)
        select = Select(fs.find_element_by_id(f'pdu_{fsid}'))
        select_by_value(select, uvalue,
                        "Setting unit of dimension %d to %r (%s)",
                        i+1, unit, uvalue)


def set_dimensions(driver, height, length, thickness):
    parent = driver.find_element_by_id('bookedit_phys_dims')
    dimensions = [(height, length, thickness)]
    set_multirow_fs(parent, dimensions, set_dimension, 'dimension')


def get_weight_unit(unit):
    if unit in ('pound', 'pounds'):
        return 'pounds', '0'
    if unit == 'kg':
        return 'kg', '1'
    raise ValueError(f"Unknown unit: {unit!r}")


def set_weight(scope, i, fs, wstr):
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
    uname, uvalue = get_weight_unit(unit)
    unit_elt = Select(fs.find_element_by_tag_name('select'))
    select_by_value(unit_elt, uvalue,
                    "Setting unit of weight %d to %r (%s)", i+1, uname, uvalue)


def set_weights(driver, weight_str):
    parent = driver.find_element_by_id('bookedit_weights')
    weights = [w.strip() for w in (weight_str or '').split(';')]
    set_multirow_fs(parent, weights, set_weight, 'weight')


def set_language(driver, term, elt_id, lang, lang_code):
    parent = driver.find_element_by_id(elt_id)
    select = Select(parent.find_element_by_tag_name('select'))
    if not lang:
        select_by_value(select, '', "Clearing %s language", term)
        return
    if lang_code not in (opt.get_attribute('value') for opt in select.options):
        # Didn't find the language code, so click the "show all languages" link
        logger.debug("Clicking 'show all languages' link")
        parent.find_element_by_css_selector('.bookEditHint > a').click()
        time.sleep(0.1)
        select = Select(parent.find_element_by_tag_name('select'))
    select_by_value(select, lang_code,
                    "Selecting %s language %r (%s)", term, lang, lang_code)


def set_reading_dates(driver, date_started, date_finished):
    parent = driver.find_element_by_id('startedfinished')
    rows = parent.find_elements_by_css_selector(
        'table.startedfinished > tbody > tr:not(.hidden)')
    set_text(parent, 'dr_start_1', date_started)
    set_text(parent, 'dr_end_1', date_finished)
    for i in range(1, len(rows)):
        set_text(parent, f'dr_start_{i+1}', None)
        set_text(parent, f'dr_end_{i+1}', None)


def parse_from_where(scope):
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


def set_from_where(driver, from_where):
    parent = driver.find_element_by_id('bookedit_datestarted')
    location, change_link = parse_from_where(parent)
    if not from_where:
        if location:
            logger.debug("Clicking location %r link", change_link.text)
            change_link.click()
            time.sleep(0.1)
            popup = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "pickrecommendations")))
            remove_link = popup.find_element_by_css_selector(
                ':scope > p:nth-of-type(3) > a')
            logger.debug("Clicking location remove link")
            remove_link.click()
            time.sleep(0.1)
        return
    if location != from_where:
        logger.debug("Clicking location %r link", change_link.text)
        change_link.click()
        time.sleep(0.1)
        popup = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "pickrecommendations")))
        # Check if venue is already used
        locations = popup.find_elements_by_css_selector(
            '#locationlist > p > a:nth-of-type(1)')
        for anchor in locations:
            if anchor.text == from_where:
                logger.debug("Selecting already used venue %r", from_where)
                anchor.click()
                time.sleep(0.1)
                return
        # Search for venue by name
        # TODO: Make this optional with config flag
        logger.debug("Choosing 'Venue search' tab")
        popup.find_element_by_id('lbtabchromemenu1').click()
        time.sleep(0.1)
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
        time.sleep(0.1)
        results = popup.find_element_by_id('venuelist')
        WebDriverWait(driver, 10).until(
            lambda _: 'updating' not in get_class_list(results))
        venues = results.find_elements_by_css_selector(
            ':scope > p > a:nth-of-type(1)')
        for anchor in venues:
            if anchor.text == from_where:
                logger.debug("Selecting venue %r", from_where)
                anchor.click()
                time.sleep(0.1)
                return
        # Enter location as free text
        logger.debug("Choosing 'Free text' tab")
        popup.find_element_by_id('lbtabchromemenu2').click()
        time.sleep(0.1)
        form = popup.find_element_by_id('freetextform')
        set_text(form, 'textareacomments', from_where)
        submit_button = form.find_element_by_css_selector(
            'input[name="Submit"]')
        logger.debug("Saving location")
        submit_button.click()
        time.sleep(0.1)


def set_physical_description(driver, physical_description):
    try:
        set_text(driver, 'phys_summary', physical_description)
    except NoSuchElementException:  # Add books form doesn't have this field
        if physical_description:
            logger.warning("Unable to set physical description")


def set_barcode(driver, barcode):
    parent = driver.find_element_by_id('bookedit_barcode')
    text_field = set_text(parent, 'item_inventory_barcode_1', barcode)
    # Barcode field has an onblur event to check for duplicate book
    defocus(text_field)
    warning = parent.find_element_by_id('barcode_warning_1')
    WebDriverWait(driver, 10).until(
        lambda _: 'updating' not in get_class_list(warning))


def set_bcid(driver, bcid):
    id1, id2 = bcid.split('-') if bcid else ('', '')
    set_text(driver, 'form_bcid_1', id1)
    set_text(driver, 'form_bcid_2', id2)


def add_book(driver, book_id, book_data):
    logger.info("Adding book %s: %s", book_id, book_data['title'])

    driver.get('https://www.librarything.com/addnew.php')

    # Title
    set_text(driver, 'form_title', book_data['title'])

    # Sort character
    set_select(driver, 'sortcharselector',
               # default selection has value "999"
               book_data.get('sortcharacter', '999'))

    # Primary author
    authors = book_data.get('authors')
    pauthor = authors[0] if authors else None
    set_author(driver, 'form_authorunflip', 'person_role--1', pauthor)

    # Tags
    set_tags(driver, book_data.get('tags'))

    # Collections
    # TODO

    # Rating
    set_rating(driver, book_data.get('rating', 0))

    # Review
    review = book_data.get('review')
    set_text(driver, 'form_review', review)
    set_review_language(driver, book_data.get('reviewlang'))

    # Other authors
    sauthors = authors[1:] if authors else []
    set_other_authors(driver, sauthors)

    # Format
    set_format(driver, get_path(book_data, 'format', 0))

    # Publication details
    set_text(driver, 'form_date', book_data.get('date'))
    set_text(driver, 'form_publication', book_data.get('publication'))
    set_text(driver, 'form_ISBN', book_data.get('originalisbn'))

    # Physical description
    set_text(driver, 'numVolumes', book_data.get('volumes'))
    set_text(driver, 'form_copies', book_data.get('copies'))
    set_paginations(driver, book_data.get('pages'))
    set_dimensions(driver, book_data.get('height'), book_data.get('length'),
                   book_data.get('thickness'))
    set_weights(driver, book_data.get('weight'))

    # Languages
    set_language(driver, 'primary', 'bookedit_lang',
                 get_path(book_data, 'language', 0),
                 get_path(book_data, 'language_codeA', 0))
    set_language(driver, 'secondary', 'bookedit_lang2',
                 get_path(book_data, 'language', 1),
                 get_path(book_data, 'language_codeA', 1))
    set_language(driver, 'original', 'bookedit_lang_original',
                 get_path(book_data, 'originallanguage', 0),
                 get_path(book_data, 'originallanguage_codeA', -1))

    # Reading dates
    set_reading_dates(driver, book_data.get('datestarted'),
                      book_data.get('dateread'))

    # Date acquired
    set_text(driver, 'form_datebought', book_data.get('dateacquired'))

    # From where
    set_from_where(driver, book_data.get('fromwhere'))

    # Classification
    set_text(driver, 'form_lccallnumber',
             get_path(book_data, 'lcc', 'code'))
    set_text(driver, 'form_dewey',
             get_path(book_data, 'ddc', 'code', 0))
    set_text(driver, 'form_btc_callnumber',
             get_path(book_data, 'callnumber', 0))

    # Comments
    set_text(driver, 'form_comments', book_data.get('comment'))
    set_text(driver, 'form_privatecomment', book_data.get('privatecomment'))

    # Summary
    # TODO: Make these optional via command-line flags
    set_physical_description(driver, book_data.get('physical_description'))
    set_text(driver, 'form_summary', book_data.get('summary'))

    # Barcode
    # TODO: Set book id as barcode if none specified
    # TODO: Check for existing book
    set_barcode(driver, get_path(book_data, 'barcode', '1'))
    set_bcid(driver, book_data.get('bcid'))

    # JSON does not correctly indicate whether a book is private
    if False:  # TODO: Command-line flag for this
        set_checkbox(driver, 'books_private', True)

    driver.find_element_by_id('book_editTabTextSave2').click()


def main(data):
    success = False

    with webdriver.Firefox() as driver:
        try:
            driver.get('https://www.librarything.com/')
            login(driver)
            for book_id, book_data in data.items():
                time.sleep(1)
                add_book(driver, book_id, book_data)
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
