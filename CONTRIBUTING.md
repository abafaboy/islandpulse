# Contributing

Thanks for helping. A few ground rules:

- **No runtime dependencies.** islandpulse uses only the Python standard library.
- **No network in tests.** Use the fake opener in `tests/fakes.py`. If you capture a new
  real API response, add it to `tests/fixtures/` unmodified and say when you captured it.
- **Say what is verified.** If you add behaviour based on an assumption about the API
  (a parameter, a limit), document it as unverified in the README.
- **Archived values are never rewritten.** Changes to the archive format must keep existing
  CSV files readable and must not change existing rows, except to fill empty cells.

Run the tests with:

```sh
pip install -e . pytest
pytest
```

Open an issue before large changes. Bug reports with the exact command, the output and
the API response (if you have it) are the most useful.
