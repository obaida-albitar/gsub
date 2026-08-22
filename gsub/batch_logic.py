"""
Pure, GTK-free logic for batch operations.

These helpers encapsulate the decision-making and document mutation for batch
operations (shared styles, resolution, font-size/resolution application) so the
logic can be unit-tested without instantiating GTK widgets. The GUI layer
(`gsub/widgets/batch_operations_panel.py` and the batch handlers in
`gsub/window.py`) delegates to these functions.
"""

import dataclasses
import os
from typing import Iterable, Optional

from gsub.models import ASSStyle, SubtitleDocument, SubtitleFormat

_ASS_FORMATS = (SubtitleFormat.ASS, SubtitleFormat.SSA)

# ASSStyle fields that batch property edits may set, derived from the model so
# it stays in sync. The name is excluded: it identifies the style to match and
# is never a batch-editable property.
_ASS_STYLE_FIELDS = {f.name for f in dataclasses.fields(ASSStyle)} - {'name'}


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


def apply_style_properties(doc: SubtitleDocument, style_names: Iterable[str], props: dict) -> bool:
    """Set the given ASSStyle fields on matching styles in an ASS/SSA document.

    Returns ``True`` if any style was updated. Non-ASS docs, unknown field
    names, and missing style names are no-ops.
    """
    if doc.format not in _ASS_FORMATS:
        return False

    fields = {key: value for key, value in props.items() if key in _ASS_STYLE_FIELDS}
    if not fields:
        return False

    names = set(style_names)
    applied = False
    for style in doc.styles:
        if style.name in names:
            for field_name, value in fields.items():
                setattr(style, field_name, value)
            applied = True
    return applied


def apply_font_size(doc: SubtitleDocument, new_size: int, target_style: Optional[str]) -> bool:
    """Set ``fontsize`` for the matching style in an ASS/SSA document.

    Returns ``True`` if a style was updated. Non-ASS docs and a missing target
    style are no-ops (``False``).
    """
    if not target_style:
        return False
    return apply_style_properties(doc, [target_style], {'fontsize': new_size})


def apply_resolution(doc: SubtitleDocument, width: int, height: int) -> bool:
    """Set PlayResX/PlayResY metadata for an ASS/SSA document.

    Returns ``True`` if applied; non-ASS docs are no-ops (``False``).
    """
    if doc.format not in _ASS_FORMATS:
        return False

    doc.metadata["PlayResX"] = str(width)
    doc.metadata["PlayResY"] = str(height)
    return True


def expand_output_name(pattern: str, original_filename: str) -> str:
    """Expand a ``{name}`` naming pattern for a single file name.

    Every ``{name}`` placeholder is replaced with the original file's stem
    (name without extension); the original extension is always kept and
    appended. An empty pattern keeps the original name. Path separators in
    the result are replaced with underscores so the name can't escape the
    chosen output directory.
    """
    stem, ext = os.path.splitext(original_filename)
    if not stem:
        stem = "subtitle"

    pattern = pattern.strip()
    if not pattern:
        pattern = '{name}'

    name = pattern.replace('{name}', stem).replace('/', '_').strip()
    if not name:
        name = stem
    return name + ext


def expand_output_names(pattern: str, filenames) -> list:
    """Expand a batch-save naming pattern into one output name per file.

    Two modes:

    - The pattern contains ``{name}``: per-file substitution via
      :func:`expand_output_name` (e.g. ``{name}_fixed`` -> ``ep01_fixed.srt``).
    - Otherwise the pattern is the base name shared by every file and the
      files are numbered after it (e.g. ``test file`` -> ``test file 01.srt``,
      ``test file 02.srt``, ...). An empty pattern keeps the original names.
    """
    filenames = list(filenames)
    pattern = pattern.strip()

    if not pattern or '{name}' in pattern:
        return [expand_output_name(pattern, name) for name in filenames]

    base = pattern.replace('/', '_').strip() or "subtitle"
    width = max(2, len(str(len(filenames))))
    names = []
    for i, original in enumerate(filenames, start=1):
        ext = os.path.splitext(original)[1]
        names.append(f"{base} {i:0{width}d}{ext}")
    return names
