# librarything-json-importer

Selenium script to import JSON book data to LibraryThing.

## Setup

1. Install the [Selenium driver][1] for your browser of choice.

2. Create a Python 3 [virtual environment][2].

    python3 -m venv venv/

3. Install the Python requirements.

    pip install -U -r requirements.txt

[1]: https://www.selenium.dev/documentation/en/webdriver/driver_requirements/
[2]: https://docs.python.org/3/library/venv.html

## Usage

Execute ltji.py and specify the json file containing your book data.

    python3 ltji.py librarything_example.json

See `python3 ltji.py -h` for command-line options.

The script will open a new browser session to import the data. You will be
prompted to log in manually, after which the script will begin adding books to
your library.

If you set the `-c`/`--cookies` flag, the script will save cookies to file and
use them to bypass the login step on subsequent runs.

It is recommended to use the `-e`/`--errors` flag to record book ids that were
not imported successfully. This can be used to retry failures by re-running the
script with the `-i`/`--book-ids` flag.

## Known limitations

* The JSON data does not include cover id, inventory status, or Lexile measure,
  so the importer does not set these properties.

* The JSON data does not indicate whether books are private. To import all
  books as private, use the `-p`/`--private` flag.

* The JSON data does not specify pagination type so the script will attempt to
  guess based on the page count value (numbers, roman numerals, or "other")

* The JSON data only does not support more than one set of dimension values
  (width/height/thickness).

* The JSON data only includes the most recent pair of reading dates.

* The JSON data does not indicate whether the "From where?" field refers to a
  venue. The script will attempt to search for a venue matching the name and
  choose the first result, otherwise it will enter the venue as free text. The
  search step can be disabled using the `--no-venue-search` flag.

* The JSON data does not indicate whether the Summary and Physical description
  fields have been set manually. Additionally, physical description cannot be
  specified when adding a new book using the manual entry form. By default the
  script leaves these fields blank to allow LibraryThing to auto-generate
  values. You can use the `--summary` and `--physical-summary` flags to change
  this behavior.

* The process for adding data from sources is somewhat rough and has a chance
  to select an incorrect work. To add all books manually use the
  `-s`/`--no-add-from-source` flag. Note that manually added books will not
  have EAN, UPC, ASIN, LCCN, or OCLC values, as these values cannot be entered
  manually.

* The script has only been tested with Firefox, so there may be unknown issues
  with other browsers.
