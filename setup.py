#!/usr/bin/env python3
"""
Setup script for Gsub.

This builds the GTK/Blueprint gresource bundle so the application is runnable
after ``pip install`` (the meson build does the same for system installs). It
requires the following tools on the build machine:

  * blueprint-compiler  (compiles data/blueprints/*.blp -> .ui)
  * glib-compile-resources (bundles the .ui files + style.css + icon)

    These are typically provided by your distribution's GTK4 / libadwaita dev
    packages. At runtime the app also needs PyGObject plus the system libraries
    libadwaita-1, gtk4 and libmpv (the ``[video]`` extra documents the libmpv
    requirement).
"""

import os
import shutil
import subprocess
import sys

from setuptools import setup, find_packages
from setuptools.command.build_py import build_py

HERE = os.path.abspath(os.path.dirname(__file__))
PACKAGE_DIR = os.path.join(HERE, "subtitle_editor")
GRESOURCE_FILENAME = "app.gsub.gresource"
GRESOURCE_TARGET = os.path.join(PACKAGE_DIR, GRESOURCE_FILENAME)


def _have(cmd):
    return shutil.which(cmd) is not None


def build_gresource():
    """Compile Blueprint templates and bundle them into the gresource.

    The resulting ``app.gsub.gresource`` is written into the subtitle_editor
    package directory so ``resources.register_resources()`` can locate it at
    runtime (it is the first candidate path searched).
    """
    if not (_have("blueprint-compiler") and _have("glib-compile-resources")):
        print(
            "WARNING: blueprint-compiler and/or glib-compile-resources not "
            "found; the gresource was not built. Install them and rebuild, or "
            "build with meson instead (`meson setup build && meson compile -C "
            "build`). The app will fail to start without it.",
            file=sys.stderr,
        )
        return

    blueprints_dir = os.path.join(HERE, "data", "blueprints")
    data_dir = os.path.join(HERE, "data")
    xml = os.path.join(data_dir, "app.gsub.gresource.xml")

    # Compile each .blp -> .ui alongside it.
    for name in os.listdir(blueprints_dir):
        if not name.endswith(".blp"):
            continue
        ui_path = os.path.join(blueprints_dir, name[:-4] + ".ui")
        subprocess.run(
            ["blueprint-compiler", "compile", "--output", ui_path,
             os.path.join(blueprints_dir, name)],
            check=True,
        )

    subprocess.run(
        ["glib-compile-resources",
         "--target", GRESOURCE_TARGET,
         "--sourcedir", blueprints_dir,
         "--sourcedir", data_dir,
         xml],
        check=True,
    )
    print(f"Built gresource: {GRESOURCE_TARGET}")


class BuildPyCommand(build_py):
    def run(self):
        build_gresource()
        super().run()


try:
    with open("README.md", "r", encoding="utf-8") as fh:
        long_description = fh.read()
except FileNotFoundError:
    long_description = ""

setup(
    name="gsub",
    version="0.4",
    author="Gsub Contributors",
    description="A modern subtitle editor for GNOME desktop",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/obaida-albitar/gsub",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Operating System :: POSIX :: Linux",
        "Environment :: X11 Applications :: GTK",
        "Intended Audience :: End Users/Desktop",
        "Topic :: Multimedia :: Video",
    ],
    python_requires=">=3.10",
    install_requires=[
        "PyGObject>=3.42",
        "pycairo>=1.20",
        # mpv (libmpv) powers video playback and subtitle rendering. The Python
        # bindings are pure ctypes; the actual libmpv shared library must be
        # installed on the system (e.g. the `mpv` / `libmpv` distribution package).
        "python-mpv>=1.0",
        # PyOpenGL bridges mpv's render context with the Gtk.GLArea's GL context.
        "PyOpenGL>=3.1",
        # PyAV bundles FFmpeg's shared libraries in its wheel, so subtitle
        # extraction works with no system FFmpeg installation required.
        "av>=11.0",
        # Best-effort detection of non-UTF-8 subtitle encodings (cp1252,
        # Shift-JIS, ...). Pure-Python; stdlib fallback if unavailable.
        "charset-normalizer>=3.0",
    ],
    extras_require={
        "video": [
            # python-mpv is the runtime binding; libmpv itself is a system
            # dependency (not pip-installable). Install e.g. `libmpv` via your
            # distribution's package manager.
            "python-mpv>=1.0",
            "PyOpenGL>=3.1",
        ],
    },
    entry_points={
        "console_scripts": [
            "gsub=subtitle_editor.main:main",
        ],
    },
    include_package_data=True,
    package_data={"subtitle_editor": [GRESOURCE_FILENAME]},
    data_files=[
        ("share/applications", ["data/app.gsub.desktop"]),
        ("share/icons/hicolor/scalable/apps", ["data/app.gsub.svg"]),
    ],
    cmdclass={"build_py": BuildPyCommand},
)
