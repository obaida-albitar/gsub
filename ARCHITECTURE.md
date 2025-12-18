# Architecture Documentation

## Overview

The GNOME Subtitle Editor is built with a modular, extensible architecture following SOLID principles and common design patterns. This document explains the key architectural decisions and component interactions.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Application Layer                        │
│  (main.py, window.py)                                       │
│  - Application lifecycle                                     │
│  - Window management                                         │
│  - Action handlers                                           │
└────────────────┬────────────────────────────────────────────┘
                 │
        ┌────────┴────────┐
        │                 │
┌───────▼────────┐  ┌────▼──────────────────────────────────┐
│  UI Widgets    │  │      Business Logic Layer             │
│  (widgets/)    │  │                                       │
│  - List View   │  │  ┌──────────────┐  ┌──────────────┐  │
│  - Editor      │  │  │   Models     │  │   Commands   │  │
│  - Dialogs     │  │  │  (models/)   │  │  (commands/) │  │
└────────────────┘  │  │              │  │              │  │
                    │  │ - Document   │  │ - Undo/Redo  │  │
                    │  │ - Entry      │  │ - Edit ops   │  │
                    │  │ - TimeCode   │  │ - Batch ops  │  │
                    │  └──────────────┘  └──────────────┘  │
                    │                                       │
                    │  ┌──────────────────────────────┐    │
                    │  │        Parsers               │    │
                    │  │      (parsers/)              │    │
                    │  │                              │    │
                    │  │  - SRTParser                 │    │
                    │  │  - ASSParser                 │    │
                    │  └──────────────────────────────┘    │
                    └───────────────────────────────────────┘
```

## Core Components

### 1. Data Models (`models/`)

**Purpose**: Define the domain objects and business rules.

#### Key Classes:

- **`TimeCode`**: Immutable time representation with millisecond precision
  - Stores hours, minutes, seconds, milliseconds
  - Converts to/from total milliseconds
  - Formats for SRT and ASS

- **`SubtitleEntry`**: Individual subtitle with text and timing
  - Index, start/end times, text content
  - Optional style reference (for ASS)
  - Duration calculation
  - Time shifting

- **`ASSStyle`**: ASS subtitle style definition
  - Font properties, colors, positioning
  - Serialization to ASS format

- **`SubtitleDocument`**: Complete subtitle file
  - Format type (SRT/ASS)
  - List of entries
  - List of styles (for ASS)
  - Metadata dictionary
  - File path and modification state
  - Entry manipulation methods

**Design Notes**:
- Models are format-agnostic where possible
- Immutability used where appropriate (TimeCode)
- Business logic kept in models (e.g., `shift_time()`)

### 2. Parsers (`parsers/`)

**Purpose**: Convert between text formats and data models.

#### Strategy Pattern:

Each format has a dedicated parser with:
- `parse(content: str) -> SubtitleDocument`: String → Model
- `serialize(document: SubtitleDocument) -> str`: Model → String

#### Parsers:

**`SRTParser`**:
- Uses regex for timecode parsing
- Splits content by blank lines (subtitle blocks)
- Handles multi-line text
- Tolerant of minor format variations

**`ASSParser`**:
- Section-based parsing ([Script Info], [V4+ Styles], [Events])
- Dynamic format detection from Format: lines
- Preserves all metadata and styles
- Handles ASS text formatting (\\N for newlines)

**Design Notes**:
- Parsers are stateless (class methods only)
- Error tolerance: skip invalid entries rather than fail
- Separation allows easy addition of new formats

### 3. Command Pattern (`commands/`)

**Purpose**: Encapsulate all editing operations for undo/redo.

#### Base Classes:

**`Command`** (Abstract):
- `execute()`: Perform the action
- `undo()`: Reverse the action
- `redo()`: Re-perform (usually same as execute)
- `description()`: Human-readable description

**`CommandManager`**:
- Maintains undo and redo stacks
- Executes commands and tracks history
- Clears redo stack on new command
- Limits history size

#### Concrete Commands:

- **`AddEntryCommand`**: Add subtitle at position
- **`RemoveEntryCommand`**: Remove subtitle (stores removed entry)
- **`EditTextCommand`**: Modify text (stores old value)
- **`EditTimingCommand`**: Modify timing (stores old times)
- **`DuplicateEntryCommand`**: Create copy with adjusted timing
- **`MoveEntryCommand`**: Reorder subtitle
- **`TimeShiftCommand`**: Batch time adjustment
- **`BatchTimingCommand`**: Multiple timing adjustments

**Design Notes**:
- Each command is self-contained
- Commands store only necessary state for undo
- All document modifications go through commands
- Easy to add new operations

### 4. UI Widgets (`widgets/`)

**Purpose**: GTK 4 / libadwaita UI components.

#### Widget Hierarchy:

**`SubtitleListView`** (extends `Gtk.ScrolledWindow`):
- Displays all subtitles in a `Gtk.ListBox`
- Custom row rendering with index, timing, and text
- Selection management
- Signals: `entry-selected`, `entry-activated`
- Efficient updates: `refresh()` vs `refresh_entry()`

**`EditorPanel`** (extends `Gtk.Box`):
- Text editor with `Gtk.TextView`
- Timing controls with `Gtk.SpinButton`
- Duration display
- Signals: `text-changed`, `timing-changed`
- Prevents signal loops with `_updating` flag

**`TimeShiftDialog`** (extends `Adw.Window`):
- Offset input with presets
- Scope selection (all, selected, from selected)
- Creates and executes `TimeShiftCommand`

**Design Notes**:
- Widgets follow libadwaita patterns
- Use of `Adw.PreferencesGroup` for grouped controls
- Signals for loose coupling
- Widgets don't directly modify models

### 5. Main Window (`window.py`)

**Purpose**: Main application window and coordinator.

#### Responsibilities:

1. **UI Assembly**: Creates header bar, list, editor, menus
2. **Action Handling**: Implements all user actions (file, edit, etc.)
3. **Coordination**: Connects widgets to business logic
4. **File I/O**: Opens and saves files using parsers
5. **Command Execution**: Uses CommandManager for all edits
6. **State Management**: Tracks current document and file

#### Action System:

Uses GTK `Gio.SimpleAction`:
- Actions defined with names and callbacks
- Keyboard shortcuts via `set_accels_for_action`
- Actions connected to menu items and buttons

**Design Notes**:
- Window acts as mediator between components
- Minimal logic in window (delegates to commands)
- Clear separation of concerns

### 6. Application Entry (`main.py`)

**Purpose**: Application lifecycle management.

**`SubtitleEditorApplication`** (extends `Adw.Application`):
- Single-instance application
- Handles activation and file opening
- Creates main window

## Design Patterns Used

### 1. Command Pattern
- **Where**: `commands/`
- **Why**: Enables undo/redo, operation logging, macro recording
- **Benefit**: Complete edit history with minimal code

### 2. Strategy Pattern
- **Where**: Parsers
- **Why**: Different algorithms for different formats
- **Benefit**: Easy to add new formats

### 3. Model-View-Controller (MVC)
- **Model**: `models/` (data and business logic)
- **View**: `widgets/` (presentation)
- **Controller**: `window.py` (coordinates model and view)
- **Benefit**: Testability, maintainability

### 4. Observer Pattern
- **Where**: GTK signals
- **Why**: Loose coupling between components
- **Benefit**: Widgets don't need direct references

### 5. Factory Pattern (implicit)
- **Where**: Parser selection based on file extension
- **Why**: Create appropriate parser dynamically
- **Benefit**: Extensible file handling

## Data Flow

### Opening a File

```
User clicks Open → FileDialog
                      ↓
                  File selected
                      ↓
              window.open_file()
                      ↓
          Detect format by extension
                      ↓
        SRTParser.parse() or ASSParser.parse()
                      ↓
             SubtitleDocument created
                      ↓
      SubtitleListView.set_document()
                      ↓
                UI updated
```

### Editing Text

```
User types in editor → TextView buffer changed
                             ↓
                 EditorPanel._on_text_buffer_changed()
                             ↓
                 Emits 'text-changed' signal
                             ↓
              Window._on_text_changed()
                             ↓
           Creates EditTextCommand
                             ↓
        CommandManager.execute()
                             ↓
         Command.execute() → modifies document
                             ↓
      SubtitleListView.refresh_entry()
```

### Undo/Redo

```
User presses Ctrl+Z → Undo action
                          ↓
              CommandManager.undo()
                          ↓
        Last command popped from undo stack
                          ↓
               Command.undo() → reverts change
                          ↓
         Command moved to redo stack
                          ↓
              UI refreshed
```

## Extensibility Points

### Adding a New Subtitle Format

1. Create parser in `parsers/new_format_parser.py`
2. Implement `parse()` and `serialize()`
3. Add format to `SubtitleFormat` enum
4. Update format detection in `window.py`
5. Add file filter in open/save dialogs

### Adding a New Editing Operation

1. Create command class in `commands/subtitle_commands.py`
2. Implement `execute()`, `undo()`, and `description()`
3. Add action in `window.py._setup_actions()`
4. Add keyboard shortcut if appropriate
5. Add menu item or button in UI

### Adding Video Playback (Future)

1. Create `VideoPlayer` widget in `widgets/video_player.py`
2. Add video backend (GStreamer via GStreamer-Python)
3. Create `VideoDocument` that wraps `SubtitleDocument`
4. Add time synchronization between player and subtitles
5. Add `SyncCommand` for adjusting subtitle timing to video

## Testing Strategy

### Unit Tests (Recommended)

- **Models**: Test time conversions, entry manipulation
- **Parsers**: Test with various valid/invalid inputs
- **Commands**: Test execute/undo/redo cycles

### Integration Tests

- **File I/O**: Round-trip parse/serialize tests
- **Command Manager**: Complex undo/redo sequences

### UI Tests

- **Manual Testing**: Use example files
- **Screenshot Tests**: Verify GNOME HIG compliance

## Performance Considerations

1. **Large Files**: List view uses GTK's efficient `ListBox`
2. **Parsing**: Regex-based parsing is fast for subtitle files (typically < 10,000 entries)
3. **Undo Stack**: Limited to 100 commands by default
4. **Updates**: Individual entry updates avoid full refresh

## Security Considerations

1. **File Input**: Parsers handle malformed input gracefully
2. **Path Handling**: Use `Gio.File` for safe file operations
3. **Character Encoding**: UTF-8 assumed, with error handling

## Accessibility

- Standard GTK widgets provide built-in accessibility
- Keyboard navigation fully supported
- Screen reader compatible (via GTK's accessibility layer)

## Internationalization (i18n)

Ready for i18n (not yet implemented):
- All user-facing strings in one place
- Use gettext for translation
- Follow GNOME translation workflow

## Build System

- **setup.py**: Standard Python packaging
- **pip**: Install in development mode with `-e`
- **Future**: Consider Meson for GNOME integration

## Dependencies

### Required:
- Python 3.10+ (for type hints and pattern matching)
- GTK 4.6+ (for modern widgets)
- libadwaita 1.0+ (for GNOME design)
- PyGObject (Python bindings)

### Optional (Future):
- GStreamer (for video playback)
- Enchant (for spell checking)

## Conclusion

This architecture provides:
- ✅ Clean separation of concerns
- ✅ Extensible design
- ✅ Full undo/redo support
- ✅ Format-agnostic core
- ✅ Native GNOME integration
- ✅ Testable components
- ✅ Room for future features

The modular design ensures that new features can be added without major refactoring, and the use of established design patterns makes the codebase easy to understand and maintain.
