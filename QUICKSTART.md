# Quick Start Guide

## Installation (2 minutes)

```bash
# Install dependencies (Ubuntu/Debian)
sudo apt install python3 python3-pip python3-gi gir1.2-gtk-4.0 gir1.2-adwaita-1

# Install the application
pip3 install --user -e .

# Run it!
subtitle-editor
```

## First Steps

### 1. Open an Example File

```bash
subtitle-editor examples/sample.srt
```

You'll see:
- **Left panel**: List of all subtitles with timing
- **Right panel**: Editor for selected subtitle

### 2. Edit a Subtitle

1. Click on any subtitle in the left list
2. Edit the text in the right panel
3. Adjust timing using the spin buttons
4. Changes are saved automatically to the document

### 3. Try Common Operations

| Action | Shortcut | What it does |
|--------|----------|--------------|
| Add subtitle | `Ctrl+N` | Creates new subtitle after current |
| Remove subtitle | `Delete` | Deletes selected subtitle |
| Duplicate | `Ctrl+D` | Copies selected subtitle |
| Move up/down | `Ctrl+Up/Down` | Reorders subtitles |
| Undo | `Ctrl+Z` | Undo last change |
| Redo | `Ctrl+Shift+Z` | Redo undone change |
| Save | `Ctrl+S` | Save file |

### 4. Batch Time Shift

Need to sync all subtitles?

1. Menu → **Time Shift…**
2. Enter offset (e.g., `+1000` for 1 second forward)
3. Choose scope (all, selected, or from selected)
4. Click **Apply**

### 5. Save Your Work

- `Ctrl+S` - Save to current file
- `Ctrl+Shift+S` - Save as new file

## Supported Formats

### SRT (SubRip)
- Simple text-based format
- Good for basic subtitles
- Example: `examples/sample.srt`

### ASS/SSA (Advanced SubStation Alpha)
- Advanced format with styles
- Supports fonts, colors, effects
- Example: `examples/sample.ass`

## Tips

- **Modified indicator**: Window title shows `•` when file has unsaved changes
- **Duration**: Automatically calculated when you change timing
- **Multiple lines**: Press Enter in text editor for multi-line subtitles
- **Sort by time**: Menu → Sort by Time to reorder chronologically
- **Keyboard navigation**: Use Tab to move between controls

## What's Next?

- Read [README.md](README.md) for full feature list
- Check [ARCHITECTURE.md](ARCHITECTURE.md) to understand the code
- See [TESTING.md](TESTING.md) for testing guide
- Visit [INSTALL.md](INSTALL.md) for detailed installation

## Getting Help

- Press `Ctrl+?` to see all keyboard shortcuts
- Menu → About for version info
- Check examples/ directory for sample files

## Common Workflows

### Creating Subtitles from Scratch

1. File → New (or `Ctrl+N` when no file is open)
2. Add first subtitle: `Ctrl+N`
3. Set timing and type text
4. Keep adding with `Ctrl+N`
5. Save: `Ctrl+S`

### Fixing Timing Issues

1. Open subtitle file
2. Select first subtitle
3. Menu → Time Shift
4. Enter offset (positive to delay, negative to advance)
5. Choose "All subtitles"
6. Apply

### Converting Between Formats

1. Open file (e.g., SRT)
2. File → Save As
3. Change extension to `.ass` or `.srt`
4. Save

---

**Enjoy editing! 🎬**
