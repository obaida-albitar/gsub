"""
Unit tests for the pure batch-operation logic in ``subtitle_editor.batch_logic``.

These do not require GTK/a display, so they run anywhere (including headless CI).
"""

from subtitle_editor.batch_logic import (
    apply_font_size,
    apply_resolution,
    apply_style_properties,
    collect_style_font_sizes,
    common_resolution,
    compute_shared_styles,
)
from subtitle_editor.models import ASSStyle, SubtitleDocument, SubtitleFormat


def _ass_doc(styles, playres=None):
    doc = SubtitleDocument(format=SubtitleFormat.ASS)
    doc.styles = [ASSStyle(name=name, fontsize=size) for name, size in styles]
    if playres is not None:
        doc.metadata["PlayResX"] = str(playres[0])
        doc.metadata["PlayResY"] = str(playres[1])
    return doc


def _srt_doc():
    return SubtitleDocument(format=SubtitleFormat.SRT)


# --- compute_shared_styles -------------------------------------------------

def test_shared_styles_single_doc_returns_all():
    doc = _ass_doc([("Default", 20), ("Sign", 75), ("ED1-Romaji-L0", 69)])
    assert compute_shared_styles([doc]) == ["Default", "ED1-Romaji-L0", "Sign"]


def test_shared_styles_intersection_across_docs():
    a = _ass_doc([("Default", 20), ("Sign", 75), ("ED1-Romaji-L0", 69)])
    b = _ass_doc([("Default", 20), ("Sign", 75), ("ED1-English-L0", 69)])
    assert compute_shared_styles([a, b]) == ["Default", "Sign"]


def test_shared_styles_no_common_returns_empty():
    a = _ass_doc([("Default", 20)])
    b = _ass_doc([("Sign", 75)])
    assert compute_shared_styles([a, b]) == []


def test_shared_styles_ignores_srt():
    ass = _ass_doc([("Default", 20), ("Sign", 75)])
    srt = _srt_doc()
    assert compute_shared_styles([ass, srt]) == ["Default", "Sign"]


def test_shared_styles_empty_styles_returns_empty():
    assert compute_shared_styles([_ass_doc([])]) == []


def test_shared_styles_no_ass_docs_returns_empty():
    assert compute_shared_styles([_srt_doc()]) == []


# --- collect_style_font_sizes ---------------------------------------------

def test_font_sizes_consistent():
    a = _ass_doc([("Default", 20), ("Sign", 40)])
    b = _ass_doc([("Default", 20), ("Sign", 40)])
    sizes = collect_style_font_sizes([a, b])
    assert sizes == {"Default": 20, "Sign": 40}


def test_font_sizes_inconsistent_is_none():
    a = _ass_doc([("Default", 20)])
    b = _ass_doc([("Default", 30)])
    sizes = collect_style_font_sizes([a, b])
    assert sizes["Default"] is None


# --- common_resolution ------------------------------------------------------

def test_common_resolution_agreement():
    a = _ass_doc([], playres=(1920, 1080))
    b = _ass_doc([], playres=(1920, 1080))
    assert common_resolution([a, b]) == (1920, 1080)


def test_common_resolution_disagreement():
    a = _ass_doc([], playres=(1920, 1080))
    b = _ass_doc([], playres=(1280, 720))
    assert common_resolution([a, b]) == (None, None)


def test_common_resolution_missing_metadata():
    a = _ass_doc([])
    b = _ass_doc([])
    assert common_resolution([a, b]) == (None, None)


def test_common_resolution_non_numeric_metadata():
    doc = _ass_doc([])
    doc.metadata["PlayResX"] = "not-a-number"
    doc.metadata["PlayResY"] = "1080"
    assert common_resolution([doc]) == (None, None)


def test_common_resolution_ignores_srt():
    assert common_resolution([_srt_doc()]) == (None, None)


# --- apply_font_size --------------------------------------------------------

def test_apply_font_size_updates_matching_style():
    doc = _ass_doc([("Default", 20), ("Sign", 75)])
    assert apply_font_size(doc, 50, "Sign") is True
    assert doc.styles[1].fontsize == 50
    assert doc.styles[0].fontsize == 20


def test_apply_font_size_missing_style_noop():
    doc = _ass_doc([("Default", 20)])
    assert apply_font_size(doc, 50, "Nope") is False
    assert doc.styles[0].fontsize == 20


def test_apply_font_size_skips_srt():
    doc = _srt_doc()
    assert apply_font_size(doc, 50, "Default") is False


# --- apply_style_properties --------------------------------------------------

def test_apply_style_properties_updates_matching_styles():
    doc = _ass_doc([("Default", 20), ("Sign", 75), ("ED", 60)])
    assert apply_style_properties(doc, ["Default", "Sign"], {
        "fontsize": 33,
        "bold": True,
        "primary_color": "&H0000FF00",
    }) is True
    for idx in (0, 1):
        assert doc.styles[idx].fontsize == 33
        assert doc.styles[idx].bold is True
        assert doc.styles[idx].primary_color == "&H0000FF00"
    # The untargeted style is untouched
    assert doc.styles[2].fontsize == 60
    assert doc.styles[2].bold is False


def test_apply_style_properties_skips_srt():
    doc = _srt_doc()
    doc.styles = [ASSStyle(name="Default", fontsize=20)]
    assert apply_style_properties(doc, ["Default"], {"fontsize": 50}) is False
    assert doc.styles[0].fontsize == 20


def test_apply_style_properties_missing_style_noop():
    doc = _ass_doc([("Default", 20)])
    assert apply_style_properties(doc, ["Nope"], {"fontsize": 50}) is False
    assert doc.styles[0].fontsize == 20


def test_apply_style_properties_ignores_unknown_fields():
    doc = _ass_doc([("Default", 20)])
    assert apply_style_properties(doc, ["Default"], {"bogus": 1, "fontsize": 40}) is True
    assert doc.styles[0].fontsize == 40
    assert not hasattr(doc.styles[0], "bogus")


def test_apply_style_properties_cannot_rename():
    doc = _ass_doc([("Default", 20)])
    assert apply_style_properties(doc, ["Default"], {"name": "Hijacked"}) is False
    assert doc.styles[0].name == "Default"


def test_apply_font_size_delegation_regression():
    doc = _ass_doc([("Default", 20), ("Sign", 75)])
    assert apply_font_size(doc, 50, "Sign") is True
    assert doc.styles[1].fontsize == 50
    assert doc.styles[0].fontsize == 20
    assert apply_font_size(doc, 50, "Nope") is False
    assert apply_font_size(doc, 50, None) is False
    assert apply_font_size(doc, 50, "") is False


# --- apply_resolution --------------------------------------------------------

def test_apply_resolution_sets_metadata():
    doc = _ass_doc([])
    assert apply_resolution(doc, 1280, 720) is True
    assert doc.metadata["PlayResX"] == "1280"
    assert doc.metadata["PlayResY"] == "720"


def test_apply_resolution_skips_srt():
    doc = _srt_doc()
    assert apply_resolution(doc, 1280, 720) is False
    assert "PlayResX" not in doc.metadata


# --- end-to-end via parsed file (regression for intersection bug) -----------

def test_shared_styles_from_parsed_ass(sample_ass_content):
    from subtitle_editor.parsers import ASSParser

    doc = ASSParser.parse(sample_ass_content)
    # The sample has a single Default style -> intersection yields it.
    assert compute_shared_styles([doc]) == ["Default"]
