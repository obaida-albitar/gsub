#!/usr/bin/env python3
"""
Setup script for GNOME Subtitle Editor.
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="gnome-subtitle-editor",
    version="1.0.0",
    author="GNOME Subtitle Editor Contributors",
    description="A modern subtitle editor for GNOME desktop",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://gitlab.gnome.org/",
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
    ],
    extras_require={
        "video": [
            "PyGObject>=3.42",  # Includes GStreamer bindings
        ],
    },
    entry_points={
        "console_scripts": [
            "subtitle-editor=subtitle_editor.main:main",
        ],
    },
    include_package_data=True,
)
