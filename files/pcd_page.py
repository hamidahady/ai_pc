"""
pcd_page.py — assembles the dashboard HTML from CSS + HTML + JS modules.

The original PAGE constant was 1,000+ lines because it inlined every byte of
CSS and JavaScript. That made the file painful to scan or diff. The content
is now split:

    pcd_page_css.py   ~ 185 lines  CSS rules (dark theme, layout, tiles, chat)
    pcd_page_html.py  ~ 140 lines  body structure: cards, sliders, chat panel
    pcd_page_js.py    ~ 670 lines  refresh loop, control bindings, AI chat, recorder

This file just stitches them together. PLAIN STRING CONCATENATION is used
(NOT f-strings) because the JS contains ${...} template literals that would
otherwise be misinterpreted by Python.
"""

from pcd_page_css import CSS
from pcd_page_html import BODY_HTML
from pcd_page_js import JS


PAGE = (
    '<!doctype html>\n'
    '<html><head><meta charset="utf-8"><title>System Dashboard</title>\n'
    '<style>\n'
    + CSS +
    '\n</style></head>\n'
    '<body>\n'
    + BODY_HTML +
    '\n<script>\n'
    + JS +
    '\n</script>\n'
    '</body></html>'
)
