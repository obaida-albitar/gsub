# Testing Guide

## Running Tests

### Quick Import Test

```bash
python3 -c "from subtitle_editor.models import *; from subtitle_editor.parsers import *; from subtitle_editor.commands import *; print('✅ All imports successful')"
```

### Test with Example Files

```bash
# Test SRT parsing
python3 -c "
from subtitle_editor.parsers import SRTParser
with open('examples/sample.srt') as f:
    doc = SRTParser.parse(f.read())
    print(f'Parsed {len(doc.entries)} SRT subtitles')
"

# Test ASS parsing
python3 -c "
from subtitle_editor.parsers import ASSParser
with open('examples/sample.ass') as f:
    doc = ASSParser.parse(f.read())
    print(f'Parsed {len(doc.entries)} ASS subtitles')
"
```

### Test the Application UI

```bash
# Run the application
subtitle-editor

# Or run with an example file
subtitle-editor examples/sample.srt
```

## Manual Testing Checklist

### File Operations
- [ ] Create new document (Menu → New)
- [ ] Open SRT file (Menu → Open, select sample.srt)
- [ ] Open ASS file (Menu → Open, select sample.ass)
- [ ] Save file (Ctrl+S)
- [ ] Save As to new file (Ctrl+Shift+S)

### Basic Editing
- [ ] Select a subtitle from the list
- [ ] Edit subtitle text in the editor panel
- [ ] Adjust start time using spin buttons
- [ ] Adjust end time using spin buttons
- [ ] Verify duration updates automatically

### Adding/Removing Subtitles
- [ ] Add new subtitle (Ctrl+N)
- [ ] Remove selected subtitle (Delete)
- [ ] Duplicate subtitle (Ctrl+D)
- [ ] Verify indices update correctly

### Moving Subtitles
- [ ] Move subtitle up (Ctrl+Up)
- [ ] Move subtitle down (Ctrl+Down)
- [ ] Verify list updates

### Batch Operations
- [ ] Open Time Shift dialog (Menu → Time Shift)
- [ ] Test positive offset (+1000ms)
- [ ] Test negative offset (-1000ms)
- [ ] Test "Selected subtitle only" scope
- [ ] Test "From selected to end" scope
- [ ] Test "All subtitles" scope
- [ ] Use quick preset buttons

### Undo/Redo
- [ ] Make several edits
- [ ] Undo all changes (Ctrl+Z repeatedly)
- [ ] Redo changes (Ctrl+Shift+Z)
- [ ] Verify all operations are reversible

### Keyboard Shortcuts
- [ ] Ctrl+S (Save)
- [ ] Ctrl+Shift+S (Save As)
- [ ] Ctrl+Z (Undo)
- [ ] Ctrl+Shift+Z (Redo)
- [ ] Ctrl+N (New subtitle)
- [ ] Delete (Remove subtitle)
- [ ] Ctrl+D (Duplicate)
- [ ] Ctrl+Up/Down (Move)
- [ ] Ctrl+? (Show shortcuts)

### Format Compatibility
- [ ] Open SRT, edit, save, reopen (verify no data loss)
- [ ] Open ASS, edit text, save, verify styles preserved
- [ ] Create new SRT, add subtitles, save
- [ ] Create new ASS, add subtitles, save

### UI/UX
- [ ] Verify native GNOME look and feel
- [ ] Test light mode (GNOME Settings → Appearance → Light)
- [ ] Test dark mode (GNOME Settings → Appearance → Dark)
- [ ] Verify window title shows filename and modification state
- [ ] Verify status bar shows subtitle count and format
- [ ] Test window resizing
- [ ] Test paned divider adjustment

### Edge Cases
- [ ] Open empty file
- [ ] Open malformed SRT file (should skip invalid entries)
- [ ] Open malformed ASS file
- [ ] Edit subtitle to empty text
- [ ] Set end time before start time
- [ ] Create 100+ subtitles (performance test)
- [ ] Undo/redo 50+ times (history limit test)

## Automated Testing (Future)

### Unit Tests Structure

```python
# tests/test_models.py
def test_timecode_conversion():
    tc = TimeCode(1, 30, 45, 500)
    assert tc.total_milliseconds == 5445500

def test_subtitle_entry_duration():
    entry = SubtitleEntry(
        1, 
        TimeCode(0, 0, 0, 0),
        TimeCode(0, 0, 2, 500),
        "Test"
    )
    assert entry.duration_ms == 2500

# tests/test_parsers.py
def test_srt_parse_basic():
    content = "1\n00:00:00,000 --> 00:00:02,000\nTest"
    doc = SRTParser.parse(content)
    assert len(doc.entries) == 1
    assert doc.entries[0].text == "Test"

def test_srt_roundtrip():
    # Parse → Serialize → Parse should yield same result
    pass

# tests/test_commands.py
def test_add_undo_redo():
    doc = SubtitleDocument(format=SubtitleFormat.SRT)
    manager = CommandManager()
    entry = SubtitleEntry(...)
    
    cmd = AddEntryCommand(doc, entry)
    manager.execute(cmd)
    assert len(doc.entries) == 1
    
    manager.undo()
    assert len(doc.entries) == 0
    
    manager.redo()
    assert len(doc.entries) == 1
```

### Running Tests (when implemented)

```bash
# Install pytest
pip3 install pytest

# Run all tests
pytest tests/

# Run with coverage
pytest --cov=subtitle_editor tests/
```

## Performance Testing

### Large File Test

Create a large subtitle file:

```python
from subtitle_editor.models import *
from subtitle_editor.parsers import SRTParser

doc = SubtitleDocument(format=SubtitleFormat.SRT)

for i in range(10000):
    entry = SubtitleEntry(
        i+1,
        TimeCode.from_milliseconds(i * 2000),
        TimeCode.from_milliseconds(i * 2000 + 1500),
        f"Subtitle number {i+1}"
    )
    doc.entries.append(entry)

content = SRTParser.serialize(doc)
with open('large_test.srt', 'w') as f:
    f.write(content)

print(f"Created test file with {len(doc.entries)} subtitles")
```

Test with:
```bash
subtitle-editor large_test.srt
```

Verify:
- Application starts quickly
- Scrolling is smooth
- Editing is responsive
- Save/load is reasonable

## Bug Reporting

If you find a bug:

1. Check if it's already reported
2. Create a minimal example that reproduces it
3. Include:
   - Operating system and version
   - GNOME version
   - GTK version
   - Python version
   - Steps to reproduce
   - Expected vs actual behavior
   - Error messages (if any)

## Contributing Tests

When adding new features:

1. Add manual test cases to this document
2. Consider adding automated tests
3. Test on both light and dark themes
4. Test keyboard navigation
5. Test with assistive technologies if possible
