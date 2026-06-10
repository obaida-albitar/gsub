"""
Home screen widget with action cards for single-file or batch workflows.
"""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GObject


class HomeScreenView(Adw.Bin):
    """Landing page with two action cards: Open File and Batch Operations."""

    __gsignals__ = {
        'open-file': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'open-batch': (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self):
        super().__init__()
        self._build_ui()

    def _build_ui(self):
        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer_box.set_halign(Gtk.Align.CENTER)
        outer_box.set_valign(Gtk.Align.CENTER)
        outer_box.set_hexpand(True)
        outer_box.set_vexpand(True)
        outer_box.set_margin_start(24)
        outer_box.set_margin_end(24)
        outer_box.set_margin_top(24)
        outer_box.set_margin_bottom(24)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(480)
        clamp.set_tightening_threshold(360)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        title_stack = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title_stack.set_halign(Gtk.Align.CENTER)

        icon = Gtk.Image.new_from_icon_name("accessories-text-editor-symbolic")
        icon.set_pixel_size(64)
        icon.set_opacity(0.5)
        title_stack.append(icon)

        title = Gtk.Label(label="Subtitle Editor")
        title.add_css_class("title-1")
        title_stack.append(title)

        subtitle = Gtk.Label(label="Create, edit, and process subtitle files")
        subtitle.add_css_class("body")
        subtitle.add_css_class("dim-label")
        title_stack.append(subtitle)

        content_box.append(title_stack)

        cards_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        cards_box.set_margin_top(12)

        open_card = self._make_action_card(
            icon_name="document-open-symbolic",
            title="Open a Subtitle File",
            description="Edit a single file with video preview and undo/redo.",
            button_label="Open File",
            css_class="suggested-action",
            callback=lambda: self.emit('open-file')
        )
        cards_box.append(open_card)

        batch_card = self._make_action_card(
            icon_name="folder-multiple-symbolic",
            title="Batch Operations",
            description="Apply time shifts, font, or resolution changes to multiple files.",
            button_label="Start Batch",
            css_class="",
            callback=lambda: self.emit('open-batch')
        )
        cards_box.append(batch_card)

        content_box.append(cards_box)
        clamp.set_child(content_box)
        outer_box.append(clamp)
        self.set_child(outer_box)

    def _make_action_card(self, icon_name, title, description, button_label, css_class, callback):
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        card.add_css_class("card")
        card.add_css_class("background")
        card.set_margin_start(12)
        card.set_margin_end(12)
        card.set_margin_top(6)
        card.set_margin_bottom(6)

        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.set_margin_start(12)
        icon_box.set_margin_top(14)
        icon_box.set_margin_bottom(14)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(40)
        icon_box.append(icon)
        card.append(icon_box)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text_box.set_hexpand(True)
        text_box.set_valign(Gtk.Align.CENTER)
        text_box.set_margin_top(14)
        text_box.set_margin_bottom(14)

        card_title = Gtk.Label(label=title)
        card_title.set_halign(Gtk.Align.START)
        card_title.add_css_class("heading")
        text_box.append(card_title)

        card_desc = Gtk.Label(label=description)
        card_desc.set_halign(Gtk.Align.START)
        card_desc.add_css_class("body")
        card_desc.add_css_class("dim-label")
        card_desc.set_wrap(True)
        text_box.append(card_desc)

        card.append(text_box)

        button_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        button_box.set_valign(Gtk.Align.CENTER)
        button_box.set_margin_end(12)
        button_box.set_margin_top(14)
        button_box.set_margin_bottom(14)
        button = Gtk.Button(label=button_label)
        if css_class:
            button.add_css_class(css_class)
        button.connect('clicked', lambda b: callback())
        button_box.append(button)
        card.append(button_box)

        return card
