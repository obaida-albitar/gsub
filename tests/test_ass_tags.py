"""Tests for the ASS override-tag parser, serializer and display helpers.

Covers the digit-prefixed colour/alpha tags, byte-exact parse -> serialize
round-trips (including the motivating real-world line), and the clean-text
helpers used by the list and the visual tag editor.
"""

import pytest
from subtitle_editor.parsers.ass_tags import (
    extract_override_tags,
    parse_override_block,
    parse_tag_segment,
    serialize_override_tags,
    split_leading_block,
    strip_override_blocks,
)

# A real line from a user's file; used verbatim as the motivating fixture.
EXAMPLE_LINE = (
    '{\\fnGeorgia\\fs12\\shad1\\blur1\\bord.1\\3c&HC85695&\\c&H25292D&'
    '\\4c&H5AF786&\\pos(338,103)}الحلقة 13'
)


def _assert_block_roundtrip(text: str) -> None:
    """Every {...} block body in ``text`` must survive parse -> serialize."""
    import re

    for match in re.finditer(r'\{([^{}]*)\}', text):
        body = match.group(1)
        assert serialize_override_tags(parse_override_block(body)) == body


@pytest.mark.unit
@pytest.mark.parser
class TestDigitPrefixedTags:
    def test_3c_tag_parses(self):
        tags = extract_override_tags('{\\3c&HC85695&}text')
        assert len(tags) == 1
        assert tags[0].name == '3c'
        assert tags[0].args == ['&HC85695&']
        assert tags[0].raw == '\\3c&HC85695&'

    @pytest.mark.parametrize('name', ['1c', '2c', '3c', '4c', '1a', '2a', '3a', '4a'])
    def test_all_digit_prefixed_variants_parse(self, name):
        tag = parse_tag_segment(name + '&HFF&')
        assert tag is not None
        assert tag.name == name
        assert tag.args == ['&HFF&']

    def test_example_line_parses_all_tags(self):
        tags = extract_override_tags(EXAMPLE_LINE)
        assert [t.name for t in tags] == [
            'fn', 'fs', 'shad', 'blur', 'bord', '3c', 'c', '4c', 'pos',
        ]
        assert tags[5].args == ['&HC85695&']
        assert tags[7].args == ['&H5AF786&']
        assert tags[8].args == ['338', '103']

    def test_letters_only_name_split(self):
        # \fs12 must split as name "fs" + args "12", never the name "fs12".
        tag = parse_tag_segment('fs12')
        assert tag.name == 'fs'
        assert tag.args == ['12']

    def test_fn_with_alphabetic_argument(self):
        tag = parse_tag_segment('fnGeorgia')
        assert tag.name == 'fn'
        assert tag.args == ['Georgia']

    def test_fscx_preferred_over_fs(self):
        tag = parse_tag_segment('fscx150')
        assert tag.name == 'fscx'
        assert tag.args == ['150']

    def test_doubled_backslash_is_not_a_tag(self):
        # "\fs12\\b1" contains an empty segment (doubled backslash) which is
        # kept as opaque content, not a tag; "\b1" still parses.
        assert [t.name for t in extract_override_tags('{\\fs12\\\\b1}x')] == ['fs', 'b']

    def test_junk_segments_still_skipped_by_extract(self):
        assert extract_override_tags('{\\123\\&H}x') == []
        assert extract_override_tags('{123}x') == []


@pytest.mark.unit
@pytest.mark.parser
class TestParenAwareSplitting:
    def test_transform_tag_is_one_tag(self):
        tags = extract_override_tags('{\\t(\\fs20,\\fs30,1)}text')
        assert len(tags) == 1
        assert tags[0].name == 't'
        assert tags[0].args == ['\\fs20', '\\fs30', '1']
        assert tags[0].raw == '\\t(\\fs20,\\fs30,1)'

    def test_nested_parens(self):
        tags = extract_override_tags('{\\t(0,1000,\\frz(30deg))}x')
        assert [t.name for t in tags] == ['t']
        assert tags[0].args == ['0', '1000', '\\frz(30deg)']

    def test_clip_drawing_mode(self):
        tags = extract_override_tags('{\\clip(m 0 0 l 100 0 100 100)}x')
        assert [t.name for t in tags] == ['clip']
        assert tags[0].args == ['m 0 0 l 100 0 100 100']


@pytest.mark.unit
@pytest.mark.parser
class TestSerializeRoundTrip:
    def test_example_line_roundtrips_byte_for_byte(self):
        block, rest = split_leading_block(EXAMPLE_LINE)
        assert block is not None
        assert rest == 'الحلقة 13'
        body = block[1:-1]
        assert serialize_override_tags(parse_override_block(body)) == body

    @pytest.mark.parametrize('text', [
        EXAMPLE_LINE,
        '{\\t(\\fs20,\\fs30,1)}text',
        '{\\p1}m 0 0 l 100 0{\p0}',
        '{note}text',
        '{\\bord.1}x',
        '{\\bord(2.5)}x',
        '{\\clip(m 0 0 l 100 0 100 100)}x',
        '{\\t(0,1000,\\frz(30deg))}x',
        '{\\pos(338,103)}x',
        '{\\fnGeorgia\\fs12}x',
        '{}e',
        '{\\fs12\\\\b1}z',          # doubled backslash
        '{note \\fs12}z',           # junk before the first tag
        '{\\FS12 UPPER}z',          # case preserved
        'no block at all',
        'text with {mid} block',
    ])
    def test_block_roundtrip(self, text):
        _assert_block_roundtrip(text)

    def test_serialize_modified_tag(self):
        body = '\\fs12\\pos(1,2)'
        pieces = parse_override_block(body)
        pieces[0].args = ['48']
        pieces[0].raw = '\\fs48'
        assert serialize_override_tags(pieces) == '\\fs48\\pos(1,2)'

    def test_serialize_empty_is_empty(self):
        assert serialize_override_tags([]) == ''
        assert parse_override_block('') == []


@pytest.mark.unit
@pytest.mark.parser
class TestStripOverrideBlocks:
    def test_example_line_strips_to_plain_text(self):
        assert strip_override_blocks(EXAMPLE_LINE) == 'الحلقة 13'

    def test_removes_all_complete_blocks(self):
        assert strip_override_blocks('{\\b1}bold{\\b0}plain') == 'boldplain'

    def test_no_blocks(self):
        assert strip_override_blocks('plain text') == 'plain text'

    def test_unbalanced_braces_left_alone(self):
        assert strip_override_blocks('{unclosed text') == '{unclosed text'
        assert strip_override_blocks('stray } brace') == 'stray } brace'

    def test_empty_string(self):
        assert strip_override_blocks('') == ''


@pytest.mark.unit
@pytest.mark.parser
class TestSplitLeadingBlock:
    def test_leading_block_split(self):
        block, rest = split_leading_block('{\\b1}hello')
        assert block == '{\\b1}'
        assert rest == 'hello'

    def test_example_line_split(self):
        block, rest = split_leading_block(EXAMPLE_LINE)
        assert block is not None
        assert block.startswith('{\\fnGeorgia')
        assert rest == 'الحلقة 13'

    def test_midline_block_is_not_leading(self):
        block, rest = split_leading_block('hello {\\b1}world')
        assert block is None
        assert rest == 'hello {\\b1}world'

    def test_unbalanced_is_not_a_block(self):
        block, rest = split_leading_block('{unclosed')
        assert block is None
        assert rest == '{unclosed'

    def test_empty_text(self):
        assert split_leading_block('') == (None, '')

    def test_empty_block_is_leading(self):
        assert split_leading_block('{}rest') == ('{}', 'rest')
