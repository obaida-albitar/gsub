# Gsub

A modern subtitle editor for the GNOME desktop, built with GTK 4 and
libadwaita. Gsub makes it easy to edit, transform, and proofread SRT and
ASS/SSA subtitle files — with an optional video preview so you can see your
timing and styling in context.

> **Note:** This project was mainly vibe-coded. Contributions, bug reports, and
> feedback are very welcome as the code matures.

## Features

- **SRT & ASS/SSA support** — full parsing and serialization for both formats,
  including round-trip fidelity for ASS override tags and section metadata.
- **Undo/redo** — every edit goes through a command stack, so you can always
  step backward and forward safely.
- **ASS style editing** — create, rename, update, and remove styles, and
  assign them to entries.
- **Batch operations** — shift timings, resize fonts per style, and bulk-apply
  styles across one or many files at once.
- **Video preview** — a libmpv-powered player renders your subtitles over the
  video so you can check timing and appearance live.
- **Subtitle extraction & conversion** — pull subtitle tracks out of video
  files (via PyAV) and convert between formats.
- **Encoding detection** — best-effort auto-detection of non-UTF-8 subtitle
  encodings (cp1252, Shift-JIS, …) with a stdlib fallback.

## Screenshot

<!-- Add a screenshot at docs/screenshot.png and uncomment the line below. -->
<!-- ![Gsub screenshot](docs/screenshot.png) -->

## Dependencies

### System libraries and tools

- `libadwaita-1` >= 1.8
- `gtk4` >= 4.14
- `glib-2.0`
- `blueprint-compiler` (compiles the `.blp` UI templates)
- `glib-compile-resources` (bundles the UI into a gresource)
- `libmpv` (powers video playback and subtitle rendering)

### Python packages

Installed automatically from `setup.py`/`requirements-dev.txt`:

- `PyGObject` >= 3.42
- `pycairo` >= 1.20
- `python-mpv` >= 1.0 (runtime binding for libmpv)
- `PyOpenGL` >= 3.1
- `av` >= 11.0 (bundles FFmpeg for extraction; no system FFmpeg needed)
- `charset-normalizer` >= 3.0

## Installation

### Option A — From source with meson (system install)

```bash
meson setup build
meson compile -C build
meson install -C build
```

This installs the app, its icon, the desktop file, and refreshes the icon and
desktop caches.

### Option B — Editable install with pip / Makefile

```bash
pip install -e .
make build-resources      # compiles .blp -> .ui and bundles the gresource
make install              # installs desktop file + icon under ~/.local
```

Or simply run `make install`, which performs both steps (plus the desktop/icon
install). After installation, launch **Gsub** from the GNOME app grid or run:

```bash
gsub
```

You can also open subtitle files directly: `gsub path/to/file.srt`.

## Usage

1. Launch Gsub and open an SRT or ASS/SSA file from the home screen (or pass a
   file path as an argument).
2. Edit entries, adjust timings, and tweak ASS styles in the editor panel.
3. Use the batch operations panel for bulk changes across styles or files.
4. Optionally load a video to preview your subtitles with the built-in player.
5. Save your work — all edits are undoable/redoable.

## Development

Clone the repository and install the development dependencies:

```bash
pip install -r requirements-dev.txt
```

Build the UI resources (needed to run the app from the source tree):

```bash
make build-resources
```

Run the application from the source tree:

```bash
python -m subtitle_editor.main
```

### Running the tests

The test suite uses `pytest` and aims for broad coverage of the parsers,
models, command stack, and converters.

```bash
pip install -r requirements-dev.txt
pytest
```

Generate an HTML coverage report with:

```bash
pytest --cov=subtitle_editor --cov-report=html
xdg-open htmlcov/index.html
```

See [`tests/README.md`](tests/README.md) for details on the test layout,
markers, and fixtures.

## Project structure

```
gsub/
├── data/                 # desktop file, icon, gresource manifest, blueprints
│   └── blueprints/       # GTK Blueprint UI templates (.blp)
├── subtitle_editor/      # application source
│   ├── commands/         # undo/redo command pattern
│   ├── converters/       # format conversion
│   ├── extractors/       # subtitle extraction from video
│   ├── models/           # data models (TimeCode, SubtitleEntry, …)
│   ├── parsers/          # SRT / ASS parsers + encoding detection
│   └── widgets/          # GTK widget glue
├── tests/                # pytest suite
├── setup.py              # pip/setuptools build
└── meson.build           # system (meson) build
```

## License

Gsub is free software, released under the **GNU General Public License v3.0 or
later**. See the [`LICENSE`](LICENSE) file for the full text.
