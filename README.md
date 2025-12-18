# GNOME Subtitle Editor

A modern, native subtitle editor for the GNOME desktop environment built with GTK 4 and libadwaita.

![GNOME Subtitle Editor](https://via.placeholder.com/800x450?text=GNOME+Subtitle+Editor)

## Features

### Format Support
- **SRT (SubRip)**: Full read/write support with text and timing
- **ASS/SSA (Advanced SubStation Alpha)**: Complete support including styles, colors, fonts, and effects

### Editing Capabilities
- ✏️ **Inline Editing**: Edit subtitle text and timing with millisecond precision
- ➕ **Add/Remove**: Create new subtitles or remove existing ones
- 📋 **Duplicate**: Copy subtitles with automatic timing adjustment
- ⬆️⬇️ **Reorder**: Move subtitles up or down in the list
- ⏱️ **Time Shift**: Batch adjust timing for all or selected subtitles
- ↩️ **Undo/Redo**: Full history support for all editing operations

### User Interface
- 🎨 **Native GNOME Design**: Follows GNOME Human Interface Guidelines
- 🌓 **Light/Dark Mode**: Automatic theme support via libadwaita
- ⌨️ **Keyboard Shortcuts**: Efficient workflow with comprehensive shortcuts
- 📱 **Responsive Layout**: Adaptive design that works on different screen sizes

## Architecture

The application is built with a clean separation of concerns:

### Core Components

```
subtitle_editor/
├── models/              # Data models
│   └── subtitle.py      # SubtitleEntry, SubtitleDocument, TimeCode, ASSStyle
├── parsers/             # Format parsers
│   ├── srt_parser.py    # SRT format handler
│   └── ass_parser.py    # ASS/SSA format handler
├── commands/            # Command pattern for undo/redo
│   ├── command.py       # Base Command and CommandManager
│   └── subtitle_commands.py  # Concrete command implementations
├── widgets/             # GTK UI widgets
│   ├── subtitle_list.py # List view of subtitles
│   ├── editor_panel.py  # Text and timing editor
│   └── dialogs.py       # Dialog windows
├── window.py            # Main application window
└── main.py              # Application entry point
```

### Design Patterns

1. **Command Pattern**: All editing operations are encapsulated as command objects, enabling comprehensive undo/redo functionality.

2. **Model-View Separation**: Data models are independent of UI, making it easy to add new formats or views.

3. **Parser Strategy**: Each subtitle format has its own parser, making it straightforward to add new formats.

4. **Signal-Based Communication**: GTK signals connect UI components, keeping them loosely coupled.

### Key Design Decisions

- **Python + GTK 4**: Chosen for rapid development, excellent GNOME integration, and native performance
- **Libadwaita Widgets**: Ensures consistency with GNOME design language and automatic theme support
- **Millisecond Precision**: TimeCode model supports precise timing control
- **Extensible Architecture**: Designed to accommodate future features like video playback

## Requirements

### System Requirements
- GNOME 42 or later
- GTK 4.6+
- libadwaita 1.0+
- Python 3.10+

### Python Dependencies
- PyGObject (python3-gi)
- GTK 4 bindings
- Libadwaita bindings

## Installation

### From Source

1. **Install dependencies** (Ubuntu/Debian):
```bash
sudo apt install python3 python3-pip python3-gi python3-gi-cairo \
                 gir1.2-gtk-4.0 gir1.2-adwaita-1 libadwaita-1-dev
```

For Fedora:
```bash
sudo dnf install python3 python3-pip python3-gobject gtk4 libadwaita
```

2. **Clone and install**:
```bash
git clone https://gitlab.gnome.org/gnome-subtitle-editor.git
cd gnome-subtitle-editor
pip3 install --user -e .
```

3. **Run the application**:
```bash
subtitle-editor
```

Or run directly:
```bash
python3 -m subtitle_editor.main
```

### Opening Files

You can open subtitle files from the command line:
```bash
subtitle-editor examples/sample.srt
```

Or use the Open dialog within the application.

## Usage

### Keyboard Shortcuts

#### File Operations
- `Ctrl+S` - Save
- `Ctrl+Shift+S` - Save As

#### Editing
- `Ctrl+Z` - Undo
- `Ctrl+Shift+Z` - Redo
- `Ctrl+N` - Add new subtitle
- `Delete` - Remove selected subtitle
- `Ctrl+D` - Duplicate selected subtitle
- `Ctrl+Up` - Move subtitle up
- `Ctrl+Down` - Move subtitle down

#### View
- `Ctrl+?` - Show keyboard shortcuts

### Workflow

1. **Open a subtitle file** or create a new one
2. **Select a subtitle** from the list on the left
3. **Edit text** in the text editor on the right
4. **Adjust timing** using the time spinners
5. **Use batch operations** from the menu for time shifting
6. **Save your work** with Ctrl+S

### Time Shift Dialog

Access via the menu to shift timing for:
- All subtitles
- Selected subtitle only
- From selected subtitle to the end

Useful for syncing subtitles with video.

## Testing

Example subtitle files are provided in the `examples/` directory:
- `sample.srt` - Demonstrates SRT format features
- `sample.ass` - Demonstrates ASS format with styles

## Future Enhancements

The architecture is designed to support:

- **Video Playback Integration**: Sync subtitle editing with video playback
- **Real-time Preview**: See subtitles rendered on video
- **Translation Mode**: Side-by-side editing for subtitle translation
- **Spell Check**: Integrated spell checking for subtitle text
- **Style Editor**: Visual editor for ASS styles
- **Search and Replace**: Find and replace text across all subtitles

## Contributing

Contributions are welcome! Please follow GNOME contribution guidelines:

1. Fork the repository
2. Create a feature branch
3. Follow the existing code style
4. Add tests for new features
5. Submit a merge request

## Code Quality

- **Type Hints**: Used throughout for better IDE support and documentation
- **Docstrings**: All classes and public methods are documented
- **Clean Architecture**: Separation of concerns and single responsibility
- **Error Handling**: Graceful error handling with user-friendly messages

## License

This project is licensed under the GNU General Public License v3.0 or later. See LICENSE file for details.

## Credits

Built with:
- [GTK 4](https://gtk.org/) - The GUI toolkit
- [Libadwaita](https://gnome.pages.gitlab.gnome.org/libadwaita/) - GNOME design patterns
- [PyGObject](https://pygobject.readthedocs.io/) - Python bindings for GTK

Inspired by the GNOME Human Interface Guidelines and existing subtitle editors.

## Support

For bugs and feature requests, please use the issue tracker at:
https://gitlab.gnome.org/gnome-subtitle-editor/issues

---

**Made with ❤️ for the GNOME community**
