# librarything-json-importer

Selenium script to import JSON book data to LibraryThing.

## Setup

1. Install the [Selenium driver][1] for your browser of choice.

2. Create a Python 3 [virtual environment][2].

    python3 -m venv venv/

3. Install the Python requirements.

    venv/bin/pip install -U -r requirements.txt

[1]: https://www.selenium.dev/documentation/en/webdriver/driver_requirements/
[2]: https://docs.python.org/3/library/venv.html

## Usage

### Import script

Execute `ltji.py` and specify the json file containing your book data.

    venv/bin/python3 ltji.py librarything_example.json

See `venv/bin/python3 ltji.py -h` for command-line options.

The script will open a new browser session to import the data. You will be
prompted to log in manually, after which the script will begin adding books to
your library.

If you set the `-c`/`--cookies` flag, the script will save cookies to file and
use them to bypass the login step on subsequent runs.

It is recommended to use the `-e`/`--errors` flag to record book ids that were
not imported successfully. This can be used to retry failures by re-running the
script with the `-i`/`--book-ids` flag.

### Export script

LibraryThing's JSON export functionality omits some information needed to fully
recreate a book (see https://www.librarything.com/topic/330435). As a
partial workaround, there is an optional script to collect additional book
details.

The export script, `ltje.py`, takes two positional arguments, an input book
data file and an output file to write the extra data collected.

    venv/bin/python3 ltje.py librarything_example.json extra.json

The extra data file can then be provided as an additional argument to `ltji.py`
to improve the fidelity of the import process.

Set the `-l`/`--login` flag to enable user login in the export script. This
enables access to private book details. Login is also required to determine
whether book covers were chosen by the user or automatically assigned.

See `venv/bin/python3 ltji.py -h` for a full list of command-line options.

The export script collects the following information:

* **Secondary author list**. This ensures that the secondary authors will
  be imported in the same order as the original book.

* **Book languages**. This is a workaround for quirks in how languages are
  handled in the native export.

* **Reading dates**. The native export only supports a single pair of reading
  start/end dates; the export script records the complete list.

* **Lexile value**. This field is omitted from the native export for some
  reason.

* **Dewey decimal call number**. This is used to determine whether the DDC
  value in the native export data has been confirmed by the user.

* **Summary autogenerated flag**. This is used to determine whether the summary
  field should be manually specified or left blank when importing.

* **From where? details**. The native export records the value of this field
  but does not indicate whether it is a venue or free-text string, leading to
  ambiguity.

* **Cover**. The native export does not indicate the selected cover.

## Known limitations

Limitations of the book data:

* The data does not specify pagination type so the script will attempt to
  guess based on the page count value (numbers, roman numerals, or "other").

* The data only contains a single set of dimensions (width/height/thickness).

* The data does not always clearly distinguish between user-specified values
  and work or autogenerated values, so in some cases the import script will
  manually specify a value that was originally auto-generated.

Limitations of the add/edit forms:

* LibraryThing does not allow editing some identifiers such as ASIN or LCCN.
  The script will log warnings if there are differences between the source data
  and the book created for these fields, but there is no way to correct them.

* The manual entry form does not have a physical description field
  (https://www.librarything.com/topic/330379), so the physical description will
  be auto-generated for manually added books.

* The "private" checkbox does not work when adding books manually
  (https://www.librarything.com/topic/330575).

* The script will log a warning if a book's work id differs from the source
  data, but there is no straightforward way to correct this.

Limitations of the import script:

* Inventory status is not currently supported.

* The process for adding data from sources is somewhat rough and has a
  possibility to select an incorrect work. To add all books manually use the
  `-s`/`--no-source` flag. Note that manually added books will not have EAN,
  UPC, ASIN, LCCN, or OCLC values, as these values cannot be entered manually.

* The script has only been tested with Firefox, so there may be unknown issues
  with other browsers.
