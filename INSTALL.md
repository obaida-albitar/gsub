# Installation Guide

## System Requirements

- **Operating System**: Linux with GNOME desktop environment
- **GNOME Version**: 42 or later
- **Python**: 3.10 or later
- **GTK**: 4.6 or later
- **libadwaita**: 1.0 or later

## Dependencies

### Ubuntu/Debian

```bash
sudo apt update
sudo apt install python3 python3-pip python3-gi python3-gi-cairo \
                 gir1.2-gtk-4.0 gir1.2-adwaita-1 libadwaita-1-dev \
                 python3-dev pkg-config
```

### Fedora

```bash
sudo dnf install python3 python3-pip python3-gobject gtk4 \
                 libadwaita python3-devel
```

### Arch Linux

```bash
sudo pacman -S python python-pip python-gobject gtk4 libadwaita
```

## Installation Methods

### Method 1: Development Installation (Recommended for Testing)

```bash
# Clone the repository
git clone https://gitlab.gnome.org/gnome-subtitle-editor.git
cd gnome-subtitle-editor

# Install in development mode
pip3 install --user -e .
```

This creates a link to the source directory, so changes are immediately reflected.

### Method 2: User Installation

```bash
# Install for current user only
pip3 install --user .
```

### Method 3: System-wide Installation

```bash
# Install system-wide (requires root)
sudo pip3 install .
```

## Running the Application

After installation, run:

```bash
subtitle-editor
```

Or open a file directly:

```bash
subtitle-editor examples/sample.srt
```

### Running from Source (Without Installation)

```bash
python3 -m subtitle_editor.main
```

## Troubleshooting

### ImportError: No module named 'gi'

Install PyGObject:
```bash
pip3 install --user PyGObject
```

### GTK or Adwaita not found

Make sure GObject Introspection bindings are installed:
```bash
# Ubuntu/Debian
sudo apt install gir1.2-gtk-4.0 gir1.2-adwaita-1

# Fedora
sudo dnf install gtk4 libadwaita
```

### Application won't start

Check Python version:
```bash
python3 --version  # Should be 3.10 or later
```

## Uninstallation

```bash
pip3 uninstall gnome-subtitle-editor
```

## Building from Source (Alternative)

For a more integrated GNOME experience, you can use Meson (future enhancement):

```bash
meson setup build
meson compile -C build
meson install -C build
```
