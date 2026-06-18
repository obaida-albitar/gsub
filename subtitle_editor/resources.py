"""
Resource loading helpers for gsub.

The application bundles all UI templates, the stylesheet, and the icon into a
single gresource (compiled at build time by meson, see data/app.gsub.gresource.xml).
This module loads and registers that gresource once and exposes convenience
helpers for the rest of the codebase.

Resource base path: /app/gsub
Template resource paths follow the convention  /app/gsub/<name>.ui
"""

import os

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gio", "2.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gio, Gtk, Gdk

RESOURCE_BASE_PATH = "/app/gsub"

# Resource path of the compiled gresource file. When running from the meson
# build tree this resolves to the build dir; when installed it lives in the
# application's libdir. We search a few well-known locations.
_GRESOURCE_FILENAME = "app.gsub.gresource"

_registered = False


def _candidate_paths() -> list[str]:
    """Locations to search for the compiled gresource bundle."""
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)
    candidates = [
        # 1. Next to the running package (dev convenience / installed alongside).
        os.path.join(here, _GRESOURCE_FILENAME),
        # 2. meson build directories at the project root.
        os.path.join(project_root, _GRESOURCE_FILENAME),
        os.path.join(project_root, "builddir", _GRESOURCE_FILENAME),
        os.path.join(project_root, "build", _GRESOURCE_FILENAME),
        os.path.join(project_root, "_build", _GRESOURCE_FILENAME),
        # 3. Installed datadir (PREFIX/share/gsub) — the meson install location.
        os.path.join(project_root, "data", _GRESOURCE_FILENAME),
        os.path.join("/usr/share/gsub", _GRESOURCE_FILENAME),
        os.path.join("/usr/local/share/gsub", _GRESOURCE_FILENAME),
        os.path.join(os.path.expanduser("~/.local/share/gsub"), _GRESOURCE_FILENAME),
        # 4. Legacy libdir fallbacks.
        os.path.join("/usr/lib", _GRESOURCE_FILENAME),
        os.path.join("/usr/local/lib", _GRESOURCE_FILENAME),
        os.path.join(os.path.expanduser("~/.local/lib"), _GRESOURCE_FILENAME),
    ]
    return candidates


def register_resources() -> None:
    """Locate, load and register the gresource bundle exactly once.

    Safe to call multiple times. Raises RuntimeError if the gresource cannot be
    found in any known location — this usually means the app was not built with
    meson (see the project README / meson.build).
    """
    global _registered
    if _registered:
        return

    last_error = None
    for path in _candidate_paths():
        if not os.path.exists(path):
            continue
        try:
            resource = Gio.Resource.load(path)
            # Gio.resources_register is the static (module-level) API;
            # the per-instance register() is not bound in PyGObject.
            Gio.resources_register(resource)
            _registered = True
            return
        except Exception as exc:  # noqa: BLE001 - keep trying other paths
            last_error = exc

    raise RuntimeError(
        f"Could not load gresource '{_GRESOURCE_FILENAME}'. "
        f"Build the app with meson first (meson setup build && meson compile -C build). "
        f"Searched: {_candidate_paths()}. Last error: {last_error}"
    )


def template_resource_path(name: str) -> str:
    """Return the gresource path for a template, e.g. 'window' -> '/app/gsub/window.ui'."""
    return f"{RESOURCE_BASE_PATH}/{name}.ui"


def install_style_provider(display=None) -> None:
    """Load style.css from the gresource onto the given (or default) display."""
    provider = Gtk.CssProvider()
    provider.load_from_resource(f"{RESOURCE_BASE_PATH}/style.css")
    target = display or Gdk.Display.get_default()
    if target is not None:
        Gtk.StyleContext.add_provider_for_display(
            target, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
