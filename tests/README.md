# Test Suite for gsub

This directory contains comprehensive tests for the gsub application.

## Test Structure

```
tests/
├── __init__.py              # Test package initialization
├── conftest.py              # Pytest fixtures and configuration
├── test_models.py           # Tests for data models (TimeCode, SubtitleEntry, etc.)
├── test_parsers.py          # Tests for SRT and ASS parsers
├── test_commands.py         # Tests for command pattern and subtitle commands
├── test_ass_commands.py     # Tests for ASS-specific commands
├── test_style_commands.py   # Tests for style editing commands
├── test_integration.py      # Integration tests and workflows
├── test_edge_cases.py       # Edge cases, stress tests, and boundary conditions
└── README.md                # This file
```

## Running Tests

### Install Dependencies

```bash
pip install -r requirements-dev.txt
```

### Run All Tests

```bash
pytest
```

### Run Specific Test Files

```bash
# Run only model tests
pytest tests/test_models.py

# Run only parser tests
pytest tests/test_parsers.py

# Run only integration tests
pytest tests/test_integration.py
```

### Run Tests by Marker

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run only parser tests
pytest -m parser

# Run only command tests
pytest -m command
```

### Run with Coverage

```bash
# Generate coverage report
pytest --cov=subtitle_editor --cov-report=html

# View coverage report
open htmlcov/index.html  # On macOS
xdg-open htmlcov/index.html  # On Linux
```

### Run Specific Tests

```bash
# Run a specific test class
pytest tests/test_models.py::TestTimeCode

# Run a specific test method
pytest tests/test_models.py::TestTimeCode::test_timecode_initialization

# Run tests matching a pattern
pytest -k "timecode"
```

## Test Categories

### Unit Tests (`test_models.py`, `test_parsers.py`, `test_commands.py`)

These tests focus on individual components in isolation:

- **Models**: Test data structures like `TimeCode`, `SubtitleEntry`, `SubtitleDocument`, and `ASSStyle`
- **Parsers**: Test SRT and ASS format parsing and serialization
- **Commands**: Test command pattern implementation and individual command classes

### Integration Tests (`test_integration.py`)

These tests verify that components work correctly together:

- Complete workflows (parse → edit → serialize)
- Complex operation sequences
- Edge cases and error handling
- Performance with large documents
- Unicode and special character handling

## Test Coverage

The test suite aims for comprehensive coverage of:

1. **Core Functionality**
   - TimeCode conversion and arithmetic
   - Subtitle entry manipulation
   - Document operations (add, remove, sort, reindex)
   - Style management for ASS format

2. **Parsers**
   - SRT format parsing and serialization
   - ASS format parsing and serialization
   - Handling of malformed content
   - Roundtrip testing (parse → serialize → parse)

3. **Command Pattern**
   - Command execution
   - Undo/redo functionality
   - Command history management
   - Complex command sequences

4. **ASS-Specific Features**
   - Metadata management
   - Style operations (create, update, rename, remove)
   - Entry style assignments
   - Aegisub project garbage handling

5. **Edge Cases**
   - Empty documents
   - Invalid input data
   - Boundary conditions (zero duration, negative shifts)
   - Unicode and special characters
   - Large documents (performance)

## Fixtures

The test suite uses pytest fixtures defined in `conftest.py`:

- `sample_timecode`: A sample TimeCode object
- `sample_entry`: A sample SubtitleEntry
- `sample_srt_document`: A sample SRT document with multiple entries
- `sample_ass_document`: A sample ASS document with styles and entries
- `sample_ass_style`: A sample ASSStyle object
- `sample_srt_content`: Sample SRT file content as string
- `sample_ass_content`: Sample ASS file content as string

## Writing New Tests

### Test Naming Convention

- Test files: `test_<module>.py`
- Test classes: `Test<ClassName>`
- Test methods: `test_<description>`

### Using Markers

Mark your tests appropriately:

```python
@pytest.mark.unit
@pytest.mark.models
def test_something(self):
    # Test code
```

Available markers:
- `unit`: Unit tests for individual components
- `integration`: Integration tests for multiple components
- `parser`: Parser tests for subtitle formats
- `command`: Command pattern tests
- `models`: Data model tests

### Example Test Structure

```python
class TestMyFeature:
    """Tests for MyFeature class."""

    @pytest.mark.unit
    def test_basic_functionality(self, sample_fixture):
        """Test basic functionality."""
        # Arrange
        obj = MyFeature()
        
        # Act
        result = obj.do_something()
        
        # Assert
        assert result == expected_value

    @pytest.mark.unit
    def test_edge_case(self):
        """Test edge case handling."""
        # Test code
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines. Ensure all tests pass before submitting pull requests.

## Troubleshooting

### GTK/GObject Import Errors

Some modules import GTK components, which may not be available in test environments. The core logic tests avoid these dependencies, but integration with UI components may require a display server.

### Coverage Not Generated

Make sure `pytest-cov` is installed:

```bash
pip install pytest-cov
```

### Tests Run Slowly

Use pytest-xdist for parallel execution:

```bash
pip install pytest-xdist
pytest -n auto
```

## Contributing

When adding new features:

1. Write tests first (TDD approach recommended)
2. Ensure all existing tests pass
3. Add tests for edge cases
4. Update this README if adding new test categories
5. Maintain test coverage above 80%

## Test Metrics

Current test statistics:
- **Total test files**: 7
- **Test categories**: Unit, Integration, Parser, Command, Models
- **Target coverage**: 80%+
- **Fixtures**: 7 shared fixtures

## Resources

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest-cov Documentation](https://pytest-cov.readthedocs.io/)
- [Python Testing Best Practices](https://docs.python-guide.org/writing/tests/)
