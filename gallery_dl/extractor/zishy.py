# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://www.zishy.com/"""

from .common import GalleryExtractor, Extractor, Message
from .. import text, util
import re

BASE_PATTERN = r"(?:https?://)?(?:www\.)?zishy\.com"


class ZishyAlbumExtractor(GalleryExtractor):
    """Extractor for zishy.com photo/video albums"""
    category = "zishy"
    subcategory = "album"
    root = "https://www.zishy.com"
    directory_fmt = ("{category}", "{album_id} {title}")
    filename_fmt = "{category}_{album_id}_{num:>03}.{extension}"
    archive_fmt = "{album_id}_{num}"
    cookies_domain = ".zishy.com"
    cookies_names = ("user_credentials", "_balder_session")
    request_interval = 0.5
    pattern = BASE_PATTERN + r"/albums/(\d+)(?:-[^/?#]*)?"
    example = "https://www.zishy.com/albums/2689-sophie-la-sage-wears-befree"

    def __init__(self, match):
        GalleryExtractor.__init__(self, match)
        self.page_url = self.url

    def _init(self):
        self._want_zip = self.config("zip", False)
        self._want_video = self.config("videos", True)

    def metadata(self, page):
        self._is_video = bool(re.search(r'<video[>\s]|<source\s', page))

        title = text.extr(
            page, "font-weight:bold; font-size:40px", "</span>")
        title = text.remove_html(title)
        if title:
            title = text.unescape(title)
            pos = title.find(">")
            if pos >= 0:
                title = title[pos+1:]
        else:
            title = text.extr(
                page,
                'font-weight:bold; font-size:40px;text-decoration:none;'
                'white-space: nowrap">\n',
                '</span>')
        title = title.strip()

        date = text.extr(page, 'font-size:20px;', '</span>')
        date = text.remove_html(date)
        if date:
            pos = date.find(">")
            if pos >= 0:
                date = date[pos+1:]
            date = date.strip()
            if date.startswith("added on "):
                date = date[9:].strip()

        description = text.extr(
            page, '<div id="descrip"', '</div>')
        if description:
            description = text.remove_html(description)
            pos = description.find(">")
            if pos >= 0:
                description = description[pos+1:].strip()

        tags = []
        for tag_url in text.extract_iter(
                page, '/albums?tag_id=', '"'):
            tag_name = text.extr(tag_url, '>#', '<')
            if not tag_name:
                tag_name = text.extr(tag_url, '>', '<')
            if tag_name:
                tags.append(tag_name)

        count = 0
        pid = self.groups[0]

        match = re.search(
            r'<strong[^>]*>\s*(\d+)\s*</strong>\s*(?:<br[^>]*>)?\s*'
            r'(?:pics|photos?)\s+in\s+full\s+gallery',
            page)
        if match:
            count = int(match.group(1))

        if not count:
            match = re.search(
                r'(?:to view the full|SUBSCRIBE[^<]*view the full)\s*'
                r'<strong[^>]*>\s*(\d+)\s*</strong>\s*(?:photos?|pics)',
                page, re.DOTALL)
            if match:
                count = int(match.group(1))

        if not count:
            match = re.search(
                r'<strong[^>]*>\s*(\d+)\s*</strong>\s*'
                r'(?:photos?|pics)\s+in\s+this\s+gallery',
                page)
            if match:
                count = int(match.group(1))

        if not count and self._is_video:
            match = re.search(
                r'<strong[^>]*>\s*(\d+)\s*</strong>\s*video',
                page)
            if match:
                count = int(match.group(1))
            else:
                count = 1

        data = {
            "album_id": text.parse_int(pid),
            "title": title,
            "date": date,
            "description": description,
            "tags": tags,
            "count": count,
        }

        if self._is_video:
            data["type"] = "video"
            match = re.search(
                r"<source\s+src='([^']+)'", page)
            if match:
                self._video_url = self.root + match.group(1)
            else:
                match = re.search(
                    r'<a\s+href="([^"]+\.mp4[^"]*)"[^>]*>'
                    r'Download MP4</a>',
                    page)
                if match:
                    self._video_url = self.root + match.group(1)
                else:
                    self._video_url = None
        else:
            data["type"] = "photos"

        self._data = data
        return data

    def images(self, page):
        if self._is_video and not self._want_video:
            return []

        find_urls = re.compile(
            r'<a\s+(?:[^>]*\s)?href="'
            r'(/uploads/(?:full|thumbs)/[^"]+/(?:full|single)_\d+_\d+\.jpg)'
            r'"'
        ).findall

        urls = find_urls(page)
        if not urls:
            find_urls = re.compile(
                r"<a\s+(?:[^>]*\s)?href='"
                r"(/uploads/(?:full|thumbs)/[^']+/(?:full|single)_\d+_\d+\.jpg)"
                r"'"
            ).findall
            urls = find_urls(page)

        result = []
        seen = set()
        for url in urls:
            url = text.unquote(url)
            if url in seen:
                continue
            seen.add(url)

            url = url.replace("/thumbs/", "/full/").replace(
                "single_", "full_")
            result.append((self.root + url, None))

        self._data["count"] = max(len(result), self._data.get("count", 0))
        return result

    def assets(self, page):
        if self._is_video and self._want_video and \
                hasattr(self, '_video_url') and self._video_url:
            yield {
                "type": "video",
                "extension": "mp4",
                "url": self._video_url,
            }

        if self._want_zip:
            match = re.search(r'href="(/galzip/(\d+))"', page)
            if match:
                yield {
                    "type": "archive",
                    "extension": "zip",
                    "url": self.root + match.group(1),
                }

    @staticmethod
    def parse_datetime(date_string):
        return text.parse_datetime(date_string, "%b %d, %Y")


class ZishyAlbumsExtractor(Extractor):
    """Extractor for zishy.com album listings"""
    category = "zishy"
    subcategory = "albums"
    root = "https://www.zishy.com"
    pattern = (BASE_PATTERN +
               r"(?:/(?:albums|girls))?"
               r"(?:/page/(\d+))?"
               r"/?(?:\?([^#]*))?$")
    example = "https://www.zishy.com/albums"

    def items(self):
        data = {"_extractor": ZishyAlbumExtractor}

        if "page=" in self.url:
            page_num = text.parse_int(
                re.search(r'page=(\d+)', self.url).group(1), 1)
        else:
            page_num = 1

        find_albums = re.compile(
            r'<a\s+href="(albums/\d+-[^"]+)"').findall

        while True:
            if page_num == 1:
                url = self.root + "/albums"
            else:
                url = f"{self.root}/albums?page={page_num}"

            page = self.request(url).text
            paths = find_albums(page)
            if not paths:
                return

            for path in paths:
                yield Message.Queue, self.root + "/" + path, data

            page_num += 1
