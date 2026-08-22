# Test Suite for Gsub

This directory contains comprehensive tests for the Gsub application:
43 test files with roughly 990 test functions, covering pure logic (models,
parsers, commands, batch operations) as well as real GTK/libadwaita widget
tests where a display is available.

## Test Structure

Tests are grouped by what they exercise — run `ls tests/test_*.py` for the
authoritative list. The main groups:

| Group | Files (examples) | What they cover |
|---|---|---|
| Models & core | `test_models.py`, `test_edge_cases.py` | `TimeCode`, `SubtitleEntry`, `SubtitleDocument`, boundary conditions |
| Parsers | `test_parsers.py`, `test_parse_document.py`, `test_parser_coverage.py`, `test_sample_file_parser.py`, `test_encoding.py` | SRT/ASS parsing, serialization round-trips, encoding detection |
| Commands | `test_commands.py`, `test_ass_commands.py`, `test_style_commands.py`, `test_bulk_style_commands.py`, `test_command_gaps.py` | Undo/redo command pattern |
| ASS features | `test_ass_tags.py`, `test_ass_validator.py`, `test_style_sanitize.py`, `test_glyph_coverage.py`, `test_font_list.py` | Override tags, compatibility checks, styles |
| Extraction & media | `test_extractors.py`, `test_ffmpeg_fallback.py`, `test_audio_peaks.py`, `test_video_player.py` | Track extraction, waveform peaks, mpv player |
| UI (need a display) | `test_window.py`, `test_editor_panel.py`, `test_home_screen.py`, `test_subtitle_list_view.py`, `test_timeline_widget.py`, `test_tag_editor.py`, `test_track_selection_dialog.py`, `test_ass_styles_dialog.py`, `test_style_widgets.py`, `test_style_props_editor.py`, `test_compatibility_panel.py`, `test_batch_operations_panel.py`, `test_shortcuts.py`, `test_video_open_flow.py`, `test_timeline_model.py`, `test_subtitle_list_logic.py` | Real widgets from the gresource templates |
| Integration & misc | `test_integration.py`, `test_batch_logic.py`, `test_format_converter.py`, `test_main.py`, `test_logger.py`, `test_desktop_file.py` | End-to-end workflows and packaging contracts |

Support files: `conftest.py` (shared fixtures), `sample_subtitle_file.ass`
(120-entry sample document), `__init__.py`.

## Running Tests

### Install Dependencies

```bash
pip install -r requirements-dev.txt   # test + lint tooling
pip install -e .                      # runtime dependencies
```

### Run All Tests

```bash
make test          # or: pytest
make test-fast     # parallel run (pytest -n auto)
```

### Run Specific Tests

```bash
# Run only one file
pytest tests/test_models.py

# Run a specific test class / method
pytest tests/test_models.py::TestTimeCode
pytest tests/test_models.py::TestTimeCode::test_timecode_initialization

# Run tests matching a pattern
pytest -k "timecode"
```

### Run Tests by Marker

```bash
pytest -m unit
pytest -m integration
pytest -m parser
pytest -m command
pytest -m models
```

### Run with Coverage

A line-coverage report is printed on every run. For the full HTML report:

```bash
make coverage
xdg-open htmlcov/index.html
```

## Headless Environments

Widget tests import GTK and require a display; they are skipped
automatically when none is available. To run them on a headless machine,
use Xvfb:

```bash
xvfb-run -a pytest
```

## Fixtures

The test suite uses pytest fixtures defined in `conftest.py`:

- `sample_timecode`: A sample TimeCode object
- `sample_entry`: A sample SubtitleEntry
- `sample_srt_document`: A sample SRT document with multiple entries
- `sample_ass_document`: A sample ASS document with styles and entries
- `sample_ass_style`: A sample ASSStyle object
- `sample_srt_content`: Sample SRT file content as string
- `sample_ass_content`: Sample ASS file content as string
- `sample_ass_file_path`: Path to the large sample ASS test file
- `sample_ass_file_content`: Content of the large sample ASS test file

## Writing New Tests

### Test Naming Convention

- Test files: `test_<module>.py`
- Test classes: `Test<ClassName>`
- Test methods: `test_<description>`

### Using Markers

Mark your tests appropriately (`--strict-markers` is enabled, so only the
registered markers below may be used):

- `unit`: Unit tests for individual components
- `integration`: Integration tests for multiple components
- `parser`: Parser tests for subtitle formats
- `command`: Command pattern tests
- `models`: Data model tests

```python
@pytest.mark.unit
@pytest.mark.models
def test_something(sample_fixture):
    obj = MyFeature()
    result = obj.do_something()
    assert result == expected_value
```

## Contributing

When adding new features:

1. Write tests first (TDD approach recommended)
2. Ensure all existing tests pass (`make test`)
3. Add tests for edge cases
4. Update this README if adding a new test group
5. Maintain test coverage above 80% (`make coverage`)

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest-cov Documentation](https://pytest-cov.readthedocs.io/)
- [Python Testing Best Practices](https://docs.python-guide.org/writing/tests/)
