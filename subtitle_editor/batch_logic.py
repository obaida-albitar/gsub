"""
Pure, GTK-free logic for batch operations.

These helpers encapsulate the decision-making and document mutation for batch
operations (shared styles, resolution, font-size/resolution application) so the
logic can be unit-tested without instantiating GTK widgets. The GUI layer
(`subtitle_editor/widgets/batch_operations_panel.py` and the batch handlers in
`subtitle_editor/window.py`) delegates to these functions.
"""

from typing import Iterable, Optional

from subtitle_editor.models import SubtitleDocument, SubtitleFormat

_ASS_FORMATS = (SubtitleFormat.ASS, SubtitleFormat.SSA)


def _ass_docs(docs: Iterable[SubtitleDocument]) -> list[SubtitleDocument]:
    """Filter to ASS/SSA documents only."""
    return [doc for doc in docs if doc.format in _ASS_FORMATS]


def compute_shared_styles(docs: Iterable[SubtitleDocument]) -> list[str]:
    """Intersection of style names across all ASS/SSA docs, sorted.

    Returns the styles that exist in *every* loaded ASS/SSA file (the styles the
    user can safely resize in a batch). With a single document this is simply
    all of its styles. Non-ASS docs (e.g. SRT) are ignored.
    """
    ass = _ass_docs(docs)
    if not ass:
        return []

    shared = {style.name for style in ass[0].styles}
    for doc in ass[1:]:
        shared &= {style.name for style in doc.styles}
    return sorted(shared)


def collect_style_font_sizes(docs: Iterable[SubtitleDocument]) -> dict[str, Optional[int]]:
    """Map each style name to its current font size across ASS/SSA docs.

    If a style's font size differs between files it maps to ``None`` so the UI
    can avoid implying a single "current" value.
    """
    sizes: dict[str, set[int]] = {}
    for doc in _ass_docs(docs):
        for style in doc.styles:
            sizes.setdefault(style.name, set()).add(style.fontsize)
    return {
        name: (next(iter(values)) if len(values) == 1 else None)
        for name, values in sizes.items()
    }


def common_resolution(docs: Iterable[SubtitleDocument]) -> tuple[Optional[int], Optional[int]]:
    """Return (width, height) if every ASS/SSA doc shares the same PlayResX/PlayResY.

    Returns ``(None, None)`` when there are no ASS/SSA docs, when the values
    differ between files, or when the stored metadata is missing/non-numeric.
    """
    ass = _ass_docs(docs)
    if not ass:
        return (None, None)

    try:
        widths = {int(doc.metadata["PlayResX"]) for doc in ass if doc.metadata.get("PlayResX")}
        heights = {int(doc.metadata["PlayResY"]) for doc in ass if doc.metadata.get("PlayResY")}
    except (ValueError, TypeError):
        return (None, None)

    if len(widths) == 1 and len(heights) == 1:
        return (next(iter(widths)), next(iter(heights)))
    return (None, None)


def apply_font_size(doc: SubtitleDocument, new_size: int, target_style: Optional[str]) -> bool:
    """Set ``fontsize`` for the matching style in an ASS/SSA document.

    Returns ``True`` if a style was updated. Non-ASS docs and a missing target
    style are no-ops (``False``).
    """
    if doc.format not in _ASS_FORMATS or not target_style:
        return False

    applied = False
    for style in doc.styles:
        if style.name == target_style:
            style.fontsize = new_size
            applied = True
    return applied


def apply_resolution(doc: SubtitleDocument, width: int, height: int) -> bool:
    """Set PlayResX/PlayResY metadata for an ASS/SSA document.

    Returns ``True`` if applied; non-ASS docs are no-ops (``False``).
    """
    if doc.format not in _ASS_FORMATS:
        return False

    doc.metadata["PlayResX"] = str(width)
    doc.metadata["PlayResY"] = str(height)
    return True
