# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Write an extractor's text content to a Markdown file"""

from .common import PostProcessor
from .. import formatter, text, util
import os
import re


class PosttextPP(PostProcessor):
    """Write the text content of a post to a '.md' file

    The file is created once the whole post has been downloaded and is
    named after the directory that post was downloaded into, so that
    every post ends up in its own folder with a matching text file.
    """

    def __init__(self, job, options):
        PostProcessor.__init__(self, job)

        self._formatters = {}

        directory = options.get("directory")
        if isinstance(directory, str):
            directory = [directory]
        self.directory_segments = directory

        self.title = options.get("title", "{title}")
        self.separator = options.get("separator", "\n\n")
        self.encoding = options.get("encoding", "utf-8")
        self.newline = options.get("newline")
        self.empty = options.get("empty", False)

        fields = options.get("fields")
        if isinstance(fields, str):
            fields = fields.split(",")
        self.fields = tuple(fields) if fields else self.FIELDS_DEFAULT

        # content of fields that hold HTML
        html = options.get("html")
        if isinstance(html, str):
            html = html.split(",")
        self.html = frozenset(html) if html else self.HTML_DEFAULT

        filename = options.get("filename")
        self.filename = filename if filename else None

        events = options.get("event", "finalize")
        if isinstance(events, str):
            events = events.split(",")
        job.register_hooks({event: self.run for event in events}, options)

    def run(self, pathfmt):
        kwdict = pathfmt.kwdict
        content = self._content(kwdict)
        if not content and not self.empty:
            return
        path = self._path(pathfmt, kwdict, content)
        try:
            self._write(path, content)
        except FileNotFoundError:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                self._write(path, content)
            except OSError as exc:
                self.log.warning("Unable to write '%s' (%s: %s)",
                                 path, exc.__class__.__name__, exc)
        except OSError as exc:
            self.log.warning("Unable to write '%s' (%s: %s)",
                             path, exc.__class__.__name__, exc)
        else:
            self.log.debug("Wrote '%s'", path)

    def _write(self, path, content):
        with open(path, "w", encoding=self.encoding,
                  newline=self.newline) as fp:
            fp.write(content)

    def _path(self, pathfmt, kwdict, content):
        # directory + name of the downloaded files' folder
        directory = self._directory(pathfmt, kwdict)

        if self.filename:
            name = self._clean(pathfmt, self._format(self.filename, kwdict))
        else:
            name = os.path.basename(directory.rstrip(os.sep)) or "post"

        if name in (os.curdir, os.pardir):
            name = "post"
        filename = self._clean(pathfmt, name + ".md")

        if self._absolute(filename):
            return filename
        return os.path.join(directory, filename)

    def _directory(self, pathfmt, kwdict):
        realdir = pathfmt.realdirectory
        if self.directory_segments is None:
            return realdir or (os.curdir + os.sep)

        segments = [
            self._clean(pathfmt, self._format(fmt, kwdict))
            for fmt in self.directory_segments
        ]
        segments = [segment for segment in segments if segment]
        if not segments:
            return realdir or (os.curdir + os.sep)
        return os.path.join(pathfmt.basedirectory, *segments) + os.sep

    def _clean(self, pathfmt, name):
        name = pathfmt.clean_segment(pathfmt.clean_path(name))
        return name.strip().rstrip(" .")

    def _absolute(self, path):
        return (os.path.isabs(path) or
                (util.WINDOWS and path[:1] == os.sep))

    def _format(self, fmt, kwdict):
        return self._formatters.setdefault(
            fmt, _parse_format(fmt))(kwdict)

    def _content(self, kwdict):
        parts = []

        title = self._text(self.title, kwdict)
        if title:
            parts.append(f"# {title}")

        for field in self.fields:
            value = self._text(f"{{{field}}}", kwdict)
            if value:
                if field in self.html:
                    value = _html_to_text(value)
                if value:
                    parts.append(value)

        text_content = self.separator.join(parts)
        if text_content:
            text_content += "\n"
        return text_content

    def _text(self, fmt, kwdict):
        try:
            value = self._format(fmt, kwdict)
        except Exception as exc:
            self.log.debug("format string %r: %s: %s",
                           fmt, exc.__class__.__name__, exc)
            return ""
        if not value:
            return ""
        if not isinstance(value, str):
            value = util.to_string(value)
        return value.strip()

    FIELDS_DEFAULT = ("content",)
    HTML_DEFAULT = frozenset(("content",))


# --------------------------------------------------------------------
# internals

_BLOCK_END = re.compile(
    r"</?(?:p|div|br|hr|li|ul|ol|tr|td|th|h[1-6]|blockquote|pre|section|"
    r"article|figure|figcaption)\b[^>]*>",
    re.IGNORECASE,
)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_BLANK = re.compile(r"\n{3,}")


def _parse_format(fmt):
    return formatter.parse(fmt, util.NONE).format_map


def _html_to_text(html):
    """Convert a HTML fragment to plain text"""
    html = _BR.sub("\n", html)
    html = _BLOCK_END.sub("\n", html)
    # NOTE: 'sep' and 'repl' have to be empty, otherwise remove_html()
    #       collapses all whitespace, including the newlines added above
    content = text.remove_html(html, "", "")
    content = text.unescape(content).replace("\xa0", " ")
    content = re.sub(r"[ \t]*\n[ \t]*", "\n", content)
    content = re.sub(r"[ \t]+([.,;:!?)\]])", r"\1", content)
    content = re.sub(r"[ \t]{2,}", " ", content)
    content = _BLANK.sub("\n\n", content)
    return content.strip()


__postprocessor__ = PosttextPP
