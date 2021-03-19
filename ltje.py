"""Script to enrich LibraryThing JSON book data by scraping book details."""
import argparse
import json
import logging
import os.path
import re

from selenium.webdriver.common.action_chains import ActionChains

from _common import (
    LibraryThingRobot,
    add_common_flags,
    init_logging,
    main_loop,
    parse_book_ids,
    try_find,
)

logger = logging.getLogger('ltje')


class LibraryThingScraper(LibraryThingRobot):
    """Class to scrape book data from LibraryThing."""

    def __init__(self, config, driver, extra):
        super(LibraryThingScraper, self).__init__(config, driver)
        self.extra = extra

    def get_secondary_authors(self):
        """Get list of secondary author names in order."""
        sa = []
        for elt in self.driver.find_elements_by_css_selector(
                '#bookedit_roles > div.bookeditPerson'):
            spans = elt.find_elements_by_css_selector(':scope > span')
            if len(spans) == 1:
                name = spans[0].text
                logger.debug("Found secondary author %r with blank role", name)
                sa.append({'lf': name})
            elif len(spans) == 2:
                name = spans[1].text
                # Trim ' -' after role name
                role = spans[0].text[:-2]
                logger.debug("Found secondary author %r with role %r",
                             name, role)
                sa.append({'lf': name, 'role': role})
            else:
                raise RuntimeError("Unable to parse secondary author")
        return sa

    def get_languages(self):
        """Get primary/secondary/original languages."""
        langs = {}
        for key, eid in (('primary', 'lang'),
                         ('secondary', 'lang2'),
                         ('original', 'lang_original')):
            elt = self.driver.find_element_by_id(f'bookedit_{eid}')
            if elt.is_displayed():
                lang = elt.text
                data_elt = self.driver.find_element_by_id(
                    f'bookedit_{eid}-data')
                # Use innerText attribute to get text content of hidden element
                lang_code = data_elt.get_attribute('innerText')
                langs[key] = {'name': lang, 'code': lang_code}
                logger.debug("Found %s language %r (%s)", key, lang, lang_code)
        return langs

    def check_cover_confirmed(self, div, anchor):
        # For some reason clicking on the anchor doesn't work; we have to click
        # on the image element
        icon = anchor.find_element_by_css_selector('img.icon')
        logger.debug("Clicking cover info button")
        self.driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", div)
        ActionChains(self.driver).move_to_element(div) \
            .move_to_element(icon).click(icon).perform()
        lb_content = self.wait_for_lb()
        confirmed = None
        confirm_div = try_find(lb_content.find_element_by_css_selector,
                               '.coverinfo > div.alwaysblue:nth-child(1)')
        if confirm_div:
            if try_find(confirm_div.find_element_by_id, 'changecover_confirm'):
                logger.debug("Found cover is not confirmed")
                confirmed = False
            elif try_find(confirm_div.find_element_by_css_selector,
                          'img.icon[src$="tick.png"]'):
                logger.debug("Found cover is confirmed")
                confirmed = True
        if confirmed is None:
            logger.warning("Unable to determine cover confirmation status")
        self.close_lb(lb_content, "Closing cover info lightbox")
        return confirmed

    cover_onclick_re = re.compile(r"si_info\('([^']*)'\)")

    def get_cover(self):
        """Get cover id."""
        div = self.driver.find_element_by_id('maincover')
        anchor = div.find_element_by_tag_name('a')
        match = self.cover_onclick_re.match(anchor.get_attribute('onclick'))
        cover_id = match.group(1)
        logger.debug("Found cover id %r", cover_id)
        cover_data = {'id': cover_id}
        if self.config.login:
            cover_data['confirmed'] = self.check_cover_confirmed(div, anchor)
        return cover_data

    def process_book(self, book_id, book_data):
        """Extract extra information about a book."""
        logger.info("Processing book %s: %s", book_id, book_data['title'])
        work_id = book_data.get('workcode', '')
        url = f'https://www.librarything.com/work/{work_id}/details/{book_id}'
        self.driver.get(url)
        if self.driver.current_url != url:
            logger.warning("Failed to get details for book %s", book_id)
            return

        extra = {}
        # Get secondary authors in correct order
        extra['secondary_authors'] = self.get_secondary_authors()
        # Get languages in a more convenient format than native export
        extra['languages'] = self.get_languages()
        # Get cover details
        extra['cover'] = self.get_cover()

        extra_data = self.extra.setdefault(book_id, {})
        extra_data['_extra'] = extra


def main(config, data, extra):
    """Import JSON data into LibraryThing."""

    def init_fn(driver):
        ltrobot = LibraryThingScraper(config, driver, extra)
        if config.login:
            ltrobot.login()
        else:
            driver.get('https://www.librarything.com')
            ltrobot.close_gdpr_banner()
        return ltrobot

    return main_loop(config, data, 'process', init_fn,
                     LibraryThingScraper.process_book)


def init_extra_data(config, data):
    """Initialize extra data."""
    # If --update is set and output file exists, read previous data
    if config.update and os.path.exists(config.outfile):
        with open(config.outfile) as f:
            return json.load(f)
    # If --merge is set, add extra data to book data
    elif config.merge:
        return data
    # Otherwise create an empty dict for extra data
    else:
        return {}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    add_common_flags(parser)
    parser.add_argument('-l', '--login', action='store_true',
                        help="Log in to LibraryThing to allow access to "
                        "private book information.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument('-m', '--merge', action='store_true',
                       help="Add extra data to book data")
    group.add_argument('-u', '--update', action='store_true',
                       help="Update output file instead of replacing")
    parser.add_argument('infile', help="Input file containing JSON book data.")
    parser.add_argument('outfile', help="Output file to write data")
    config = parser.parse_args()
    init_logging(config, 'ltje')
    parse_book_ids(config)
    with open(config.infile) as f:
        data = json.load(f)
    extra = init_extra_data(config, data)
    success = main(config, data, extra)
    if success:
        with open(config.outfile, 'w') as f:
            # Pretty-print
            json.dump(extra, f, indent=2)
            f.write('\n')
    exit(0 if success else 1)
