#!/usr/bin/env python3
"""
Setup script for Gsub.

All package metadata lives in pyproject.toml; this file only adds the custom
build step that compiles the GTK/Blueprint gresource bundle so the application
is runnable after ``pip install`` (the meson build does the same for system
installs). It requires the following tools on the build machine:

  * blueprint-compiler  (compiles data/blueprints/*.blp -> .ui)
  * glib-compile-resources (bundles the .ui files + style.css + icon)

These are typically provided by your distribution's GTK4 / libadwaita dev
packages. At runtime the app also needs PyGObject plus the system libraries
libadwaita-1, gtk4 and libmpv (python-mpv bundles only the ctypes bindings;
libmpv itself is not pip-installable).
"""

import os
import shutil
import subprocess
import sys

from setuptools import setup
from setuptools.command.build_py import build_py

HERE = os.path.abspath(os.path.dirname(__file__))
PACKAGE_DIR = os.path.join(HERE, "gsub")
GRESOURCE_FILENAME = "gsub.gresource"
GRESOURCE_TARGET = os.path.join(PACKAGE_DIR, GRESOURCE_FILENAME)


def _have(cmd):
    return shutil.which(cmd) is not None


def build_gresource():
    """Compile Blueprint templates and bundle them into the gresource.

    The resulting ``gsub.gresource`` is written into the gsub package
    directory so ``resources.register_resources()`` can locate it at runtime
    (it is the first candidate path searched).
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
    xml = os.path.join(data_dir, "gsub.gresource.xml")

    # Compile each .blp -> .ui alongside it.
    for name in sorted(os.listdir(blueprints_dir)):
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


setup(
    package_data={"gsub": [GRESOURCE_FILENAME]},
    data_files=[
        ("share/applications", ["data/io.github.obaida-albitar.gsub.desktop"]),
        ("share/icons/hicolor/scalable/apps", ["data/io.github.obaida-albitar.gsub.svg"]),
    ],
    cmdclass={"build_py": BuildPyCommand},
)
