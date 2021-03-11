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
