"""Tests for font-family dropdown helpers.

These cover the regression where a style whose font is not installed on the
user's machine was silently replaced by the first installed font (and lost on
save). The helpers are GTK-free so they run headlessly.
"""

import pytest
from subtitle_editor.utils import merge_font_families, is_font_installed


@pytest.mark.unit
class TestFontHelpers:
    @pytest.mark.unit
    def test_installed_fonts_are_detected(self):
        installed = ["Arial", "DejaVu Sans", "Sansation"]
        assert is_font_installed("Arial", installed) is True
        assert is_font_installed("sansation", installed) is False
        assert is_font_installed("", installed) is False
        assert is_font_installed(None, installed) is False

    @pytest.mark.unit
    def test_merge_keeps_installed_sorted(self):
        installed = ["DejaVu Sans", "Arial"]
        result = merge_font_families(installed, [])
        assert result == ["Arial", "DejaVu Sans"]

    @pytest.mark.unit
    def test_merge_appends_uninstalled_style_fonts(self):
        installed = ["Arial", "DejaVu Sans"]
        style_fonts = ["Sansation", "Arial", "Comic Neue"]
        result = merge_font_families(installed, style_fonts)
        # Installed first (sorted), then uninstalled style fonts (sorted, deduped).
        assert result == ["Arial", "DejaVu Sans", "Comic Neue", "Sansation"]
        # The real (uninstalled) font names are preserved, not dropped.
        assert "Sansation" in result
        assert "Comic Neue" in result

    @pytest.mark.unit
    def test_merge_does_not_duplicate_installed(self):
        installed = ["Arial", "Sansation"]
        # Sansation already installed -> must not appear twice.
        result = merge_font_families(installed, ["Sansation"])
        assert result.count("Sansation") == 1
        assert result == ["Arial", "Sansation"]

    @pytest.mark.unit
    def test_merge_ignores_empty_font_names(self):
        installed = ["Arial"]
        result = merge_font_families(installed, ["", None, "Arial"])
        assert result == ["Arial"]
