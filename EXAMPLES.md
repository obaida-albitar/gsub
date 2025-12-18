# Usage Examples

This document provides practical examples of using the GNOME Subtitle Editor, both through the UI and programmatically.

## UI Usage Examples

### Example 1: Creating Subtitles from Scratch

**Scenario**: You have a video and want to create subtitles for it.

1. **Start the application**:
   ```bash
   subtitle-editor
   ```

2. **Create a new document**: The app starts empty, ready for a new document

3. **Add first subtitle** (Ctrl+N):
   - Text: "Welcome to our video!"
   - Start: 00:00:00,000
   - End: 00:00:02,000

4. **Continue adding subtitles**: Press Ctrl+N for each new subtitle

5. **Save** (Ctrl+S):
   - Choose filename: `my_video.srt`
   - Format is determined by extension

### Example 2: Fixing Timing Issues

**Scenario**: All subtitles appear 2 seconds too early.

1. **Open the file**:
   ```bash
   subtitle-editor subtitles.srt
   ```

2. **Open Time Shift dialog**: Menu → Time Shift…

3. **Enter offset**: `+2000` (2000 milliseconds = 2 seconds)

4. **Select scope**: "All subtitles"

5. **Click Apply**

6. **Save** (Ctrl+S)

### Example 3: Adjusting a Single Subtitle

**Scenario**: One subtitle needs different timing.

1. **Select the subtitle** in the left list

2. **Adjust timing** in the right panel:
   - Modify hours/minutes/seconds/milliseconds
   - Changes are applied immediately

3. **Edit text** if needed

4. **Save** (Ctrl+S)

### Example 4: Reordering Subtitles

**Scenario**: You added subtitles out of order.

**Method 1** - Manual reordering:
1. Select subtitle to move
2. Press Ctrl+Up or Ctrl+Down to reorder
3. Repeat as needed

**Method 2** - Sort by time:
1. Menu → Sort by Time
2. All subtitles ordered by start time automatically

### Example 5: Converting SRT to ASS

**Scenario**: You want to add styling capabilities.

1. **Open SRT file**: `subtitle-editor movie.srt`

2. **Save As** (Ctrl+Shift+S):
   - Change extension to `.ass`
   - New filename: `movie.ass`

3. **File is now in ASS format** with default style

## Programmatic Usage Examples

### Example 1: Simple SRT Creation

```python
from subtitle_editor.models import SubtitleDocument, SubtitleEntry, TimeCode, SubtitleFormat
from subtitle_editor.parsers import SRTParser

# Create new document
doc = SubtitleDocument(format=SubtitleFormat.SRT)

# Add subtitles
subtitles = [
    ("Welcome!", 0, 2000),
    ("This is a demo.", 2500, 5000),
    ("Enjoy the video!", 5500, 8000),
]

for i, (text, start_ms, end_ms) in enumerate(subtitles, 1):
    entry = SubtitleEntry(
        index=i,
        start_time=TimeCode.from_milliseconds(start_ms),
        end_time=TimeCode.from_milliseconds(end_ms),
        text=text
    )
    doc.entries.append(entry)

# Save to file
output = SRTParser.serialize(doc)
with open('output.srt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Created {len(doc.entries)} subtitles")
```

### Example 2: Batch Processing - Time Shift

```python
from subtitle_editor.parsers import SRTParser

# Load file
with open('input.srt', 'r', encoding='utf-8') as f:
    doc = SRTParser.parse(f.read())

# Shift all subtitles forward by 1.5 seconds
offset_ms = 1500

for entry in doc.entries:
    entry.shift_time(offset_ms)

# Save
output = SRTParser.serialize(doc)
with open('output.srt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Shifted {len(doc.entries)} subtitles by {offset_ms}ms")
```

### Example 3: Extracting Text from Subtitles

```python
from subtitle_editor.parsers import SRTParser

# Load file
with open('movie.srt', 'r', encoding='utf-8') as f:
    doc = SRTParser.parse(f.read())

# Extract all text
all_text = []
for entry in doc.entries:
    all_text.append(entry.text)

# Save to text file
with open('transcript.txt', 'w', encoding='utf-8') as f:
    f.write('\n\n'.join(all_text))

print(f"Extracted {len(all_text)} subtitle texts")
```

### Example 4: Creating ASS with Custom Style

```python
from subtitle_editor.models import (
    SubtitleDocument, SubtitleEntry, TimeCode, 
    SubtitleFormat, ASSStyle
)
from subtitle_editor.parsers import ASSParser

# Create document
doc = SubtitleDocument(format=SubtitleFormat.ASS)
doc.metadata['Title'] = 'My Video'
doc.metadata['ScriptType'] = 'v4.00+'

# Create custom style
title_style = ASSStyle(
    name='Title',
    fontname='Arial',
    fontsize=28,
    primary_color='&H00FFFF00',  # Yellow
    bold=True,
    alignment=2  # Bottom center
)

default_style = ASSStyle(name='Default')

doc.styles.extend([default_style, title_style])

# Add subtitles with different styles
entries = [
    (1, 0, 3000, "Movie Title", 'Title'),
    (2, 4000, 7000, "Regular subtitle", 'Default'),
]

for idx, start_ms, end_ms, text, style in entries:
    entry = SubtitleEntry(
        index=idx,
        start_time=TimeCode.from_milliseconds(start_ms),
        end_time=TimeCode.from_milliseconds(end_ms),
        text=text,
        style=style
    )
    doc.entries.append(entry)

# Save
output = ASSParser.serialize(doc)
with open('styled.ass', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Created ASS file with {len(doc.styles)} styles")
```

### Example 5: Format Conversion

```python
from subtitle_editor.parsers import SRTParser, ASSParser
from subtitle_editor.models import SubtitleFormat

# Load SRT
with open('input.srt', 'r', encoding='utf-8') as f:
    doc = SRTParser.parse(f.read())

# Convert format
doc.format = SubtitleFormat.ASS

# Ensure at least one style exists for ASS
if not doc.styles:
    from subtitle_editor.models import ASSStyle
    doc.styles.append(ASSStyle())

# Save as ASS
output = ASSParser.serialize(doc)
with open('output.ass', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Converted {len(doc.entries)} subtitles from SRT to ASS")
```

### Example 6: Filtering Subtitles by Time Range

```python
from subtitle_editor.parsers import SRTParser
from subtitle_editor.models import SubtitleDocument, SubtitleFormat

# Load file
with open('full_movie.srt', 'r', encoding='utf-8') as f:
    doc = SRTParser.parse(f.read())

# Extract subtitles from 5:00 to 10:00
start_ms = 5 * 60 * 1000  # 5 minutes
end_ms = 10 * 60 * 1000   # 10 minutes

filtered_doc = SubtitleDocument(format=SubtitleFormat.SRT)

for entry in doc.entries:
    if start_ms <= entry.start_time.total_milliseconds <= end_ms:
        filtered_doc.entries.append(entry)

filtered_doc.reindex()

# Save filtered subtitles
output = SRTParser.serialize(filtered_doc)
with open('clip.srt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Extracted {len(filtered_doc.entries)} subtitles")
```

### Example 7: Merging Two Subtitle Files

```python
from subtitle_editor.parsers import SRTParser
from subtitle_editor.models import SubtitleDocument, SubtitleFormat

# Load both files
with open('part1.srt', 'r', encoding='utf-8') as f:
    doc1 = SRTParser.parse(f.read())

with open('part2.srt', 'r', encoding='utf-8') as f:
    doc2 = SRTParser.parse(f.read())

# Calculate offset for part2 (after part1 ends)
if doc1.entries:
    offset_ms = doc1.entries[-1].end_time.total_milliseconds + 1000  # 1s gap
else:
    offset_ms = 0

# Shift part2 timing
for entry in doc2.entries:
    entry.shift_time(offset_ms)

# Merge
merged_doc = SubtitleDocument(format=SubtitleFormat.SRT)
merged_doc.entries = doc1.entries + doc2.entries
merged_doc.reindex()

# Save
output = SRTParser.serialize(merged_doc)
with open('merged.srt', 'w', encoding='utf-8') as f:
    f.write(output)

print(f"Merged into {len(merged_doc.entries)} subtitles")
```

### Example 8: Using the Command Pattern

```python
from subtitle_editor.models import SubtitleDocument, SubtitleEntry, TimeCode, SubtitleFormat
from subtitle_editor.commands import (
    CommandManager, AddEntryCommand, EditTextCommand, TimeShiftCommand
)

# Create document and command manager
doc = SubtitleDocument(format=SubtitleFormat.SRT)
manager = CommandManager()

# Add subtitle with undo support
entry = SubtitleEntry(
    index=1,
    start_time=TimeCode(0, 0, 0, 0),
    end_time=TimeCode(0, 0, 2, 0),
    text="First subtitle"
)

cmd1 = AddEntryCommand(doc, entry)
manager.execute(cmd1)
print(f"Added subtitle. Count: {len(doc.entries)}")

# Edit text with undo support
cmd2 = EditTextCommand(doc, 0, "Modified subtitle")
manager.execute(cmd2)
print(f"Text: {doc.entries[0].text}")

# Shift time with undo support
cmd3 = TimeShiftCommand(doc, 1000)  # +1 second
manager.execute(cmd3)
print(f"Start time: {doc.entries[0].start_time}")

# Undo everything
while manager.can_undo():
    manager.undo()
    print(f"Undone. Entries: {len(doc.entries)}")

# Redo everything
while manager.can_redo():
    manager.redo()
    print(f"Redone. Entries: {len(doc.entries)}")
```

### Example 9: Statistics and Analysis

```python
from subtitle_editor.parsers import SRTParser
from statistics import mean, median

# Load file
with open('movie.srt', 'r', encoding='utf-8') as f:
    doc = SRTParser.parse(f.read())

# Calculate statistics
durations = [entry.duration_ms for entry in doc.entries]
text_lengths = [len(entry.text) for entry in doc.entries]

print(f"Total subtitles: {len(doc.entries)}")
print(f"Average duration: {mean(durations):.0f}ms")
print(f"Median duration: {median(durations):.0f}ms")
print(f"Average text length: {mean(text_lengths):.1f} chars")
print(f"Total duration: {sum(durations)/1000:.1f} seconds")

# Find longest subtitle
longest = max(doc.entries, key=lambda e: e.duration_ms)
print(f"\nLongest subtitle ({longest.duration_ms}ms):")
print(f"  \"{longest.text}\"")

# Find shortest gap between subtitles
gaps = []
for i in range(len(doc.entries) - 1):
    gap = (doc.entries[i+1].start_time.total_milliseconds - 
           doc.entries[i].end_time.total_milliseconds)
    gaps.append(gap)

if gaps:
    print(f"\nAverage gap: {mean(gaps):.0f}ms")
    print(f"Shortest gap: {min(gaps)}ms")
```

## Tips and Tricks

### Quick Timing Adjustments

Use the Time Shift presets for common adjustments:
- `-5s`, `-1s`, `-100ms` for delays
- `+100ms`, `+1s`, `+5s` for advances

### Multi-line Subtitles

In the text editor, simply press Enter to create multi-line subtitles. They'll be preserved in both SRT and ASS formats.

### Efficient Workflow

1. Open file
2. Use keyboard to navigate (Arrow keys select subtitles)
3. Tab to switch between controls
4. Type to edit
5. Ctrl+N to add, Delete to remove
6. Ctrl+S often!

### ASS Styling Preservation

When editing ASS files, all styles are preserved even if you only edit text. The application maintains the complete style definitions.

### Bulk Operations

For operations on many files, use the Python API in scripts rather than the UI.

## Common Patterns

### Pattern: Safe File Modification

```python
from subtitle_editor.parsers import SRTParser
import shutil

# Backup original
shutil.copy('original.srt', 'original.srt.backup')

# Load and modify
with open('original.srt', 'r', encoding='utf-8') as f:
    doc = SRTParser.parse(f.read())

# Make changes...
for entry in doc.entries:
    entry.shift_time(500)

# Save
output = SRTParser.serialize(doc)
with open('original.srt', 'w', encoding='utf-8') as f:
    f.write(output)
```

### Pattern: Processing Multiple Files

```python
from pathlib import Path
from subtitle_editor.parsers import SRTParser

for srt_file in Path('.').glob('*.srt'):
    print(f"Processing {srt_file}...")
    
    with open(srt_file, 'r', encoding='utf-8') as f:
        doc = SRTParser.parse(f.read())
    
    # Process...
    for entry in doc.entries:
        entry.shift_time(1000)
    
    # Save to new directory
    output_file = Path('adjusted') / srt_file.name
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(SRTParser.serialize(doc))
```

## Troubleshooting

### File Won't Open

- Check encoding (should be UTF-8)
- Verify format (SRT or ASS/SSA)
- Look for syntax errors in the file

### Changes Not Saving

- Check file permissions
- Verify disk space
- Look for error messages in console

### Timing Issues

- Remember: time shift uses milliseconds
- Negative values move subtitles earlier
- Positive values move subtitles later

---

For more examples, check the `examples/` directory and the test files in `TESTING.md`.
