"""Script to enrich LibraryThing JSON book data by scraping book details."""
import argparse
import json
import logging
import os.path

from _common import (
    LibraryThingRobot,
    add_common_flags,
    init_logging,
    main_loop,
    parse_book_ids,
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

    def process_book(self, book_id, book_data):
        logger.info("Processing book %s: %s", book_id, book_data['title'])
        work_id = book_data.get('workcode', '')
        url = f'https://www.librarything.com/work/{work_id}/details/{book_id}'
        self.driver.get(url)
        if self.driver.current_url != url:
            logger.warning("Failed to get details for book %s", book_id)
            return

        extra = {}
        extra['secondary_authors'] = self.get_secondary_authors()
        book_data = self.extra.setdefault(book_id, {})
        book_data['_extra'] = extra


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

    return main_loop(config, data, 'import', init_fn,
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
