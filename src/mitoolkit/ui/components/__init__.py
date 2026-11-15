"""Reusable interface components, independent of any one window.

- buttons, button_row, selector: buttons (with icons and state colours), a row of equal buttons, and
  the selector bar used for tabs and ranges
- charts: line charts, ring gauges and sparklines
- skeleton: shimmering loading placeholders
- scroll_page: a page that scrolls and keeps a readable width
- shapes, render: drawing helpers (rounded cards, anti-aliased images with Pillow)

Windows and dialogs (the things built *from* these) live one level up, in mitoolkit.ui.
"""
