"""Render scientific Markdown as an offline browser page."""

from html import escape
from pathlib import Path

from latex2mathml.converter import convert
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin


def render_document(text, path):
    def render_math(content, options):
        display = "block" if options["display_mode"] else "inline"
        return convert(content, display=display)

    markdown = MarkdownIt("commonmark", {"html": False})
    markdown.enable("table")
    markdown.use(dollarmath_plugin, renderer=render_math)
    body = markdown.render(text)
    base = escape(Path(path).resolve().parent.as_uri() + "/", quote=True)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="{base}">
<title>HMBreach scientific documentation</title>
<style>
body {{ max-width: 960px; margin: 2em auto; padding: 0 2em; color: #24292f;
       font: 16px/1.6 system-ui, sans-serif; }}
h1, h2 {{ border-bottom: 1px solid #d0d7de; padding-bottom: .3em; }}
img {{ max-width: 100%; height: auto; }}
pre, code {{ background: #f6f8fa; border-radius: 4px; }}
pre {{ padding: 1em; overflow-x: auto; }}
code {{ padding: .1em .3em; }}
table {{ border-collapse: collapse; }}
td, th {{ border: 1px solid #d0d7de; padding: .4em .8em; }}
.math.block {{ overflow-x: auto; overflow-y: hidden; margin: 1em 0; padding: .3em 0; }}
a {{ color: #0969da; }}
</style></head><body>
<p>Some links to solver source files may not be included in this package.</p>
{body}
</body></html>"""
