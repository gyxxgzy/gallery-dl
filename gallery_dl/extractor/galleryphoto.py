# -*- coding: utf-8 -*-

# Copyright 2026 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://gallery.photo/ galleries"""

import re
from .common import Extractor, Message
from .. import text

BASE_PATTERN = r"(?:https?://)?([\w-]+)\.gallery\.photo"


class GalleryphotoExtractor(Extractor):
    """Base class for gallery.photo extractors"""
    category = "galleryphoto"
    root = ""
    directory_fmt = ("{category}", "{subdomain}", "{gallery_slug}")
    filename_fmt = "{filename}.{extension}"
    archive_fmt = "{file_id}"
    request_interval = (0.5, 1.5)

    def __init__(self, match):
        self.subdomain = match.group(1)
        if not self.root:
            self.root = f"https://{self.subdomain}.gallery.photo"
        Extractor.__init__(self, match)

    def _init(self):
        pass

    def _fetch_rsc(self, url):
        """Fetch page and extract RSC payload"""
        html = self.request(url).text

        chunks = []
        prefix = 'self.__next_f.push([1,"'
        pos = 0
        while True:
            idx = html.find(prefix, pos)
            if idx == -1:
                break
            start = idx + len(prefix)
            end = html.find('"])<', start)
            if end == -1:
                break
            raw = html[start:end]
            try:
                decoded = raw.encode().decode("unicode_escape")
            except Exception:
                decoded = raw
            chunks.append(decoded)
            pos = end + 4

        return "".join(chunks)

    def _extract_media(self, rsc):
        """Extract CDN base, fileKeys and filenames from RSC payload"""
        cdn = text.extr(rsc, ':HC"', '"')
        if not cdn:
            cdn = "https://storage.vigbo.tech"

        file_keys = re.findall(
            r'"fileKey":"(gallery-photo/[^"]+)"', rsc)
        names = re.findall(
            r'"name":"([^"]+)","contentType"', rsc)

        return cdn, file_keys, names

    def _yield_photos(self, cdn, file_keys, names, gallery_slug):
        """Yield Message.Url for each photo"""
        base = {
            "subdomain": self.subdomain,
            "gallery_slug": gallery_slug,
            "count": len(file_keys),
            "cdn": cdn,
        }

        for num, (file_key, name) in enumerate(
                zip(file_keys, names), 1):
            file_data = {
                "file_id": text.extr(
                    file_key, "/original/", "") or str(num),
                "file_key": file_key,
                "filename": name,
                "num": num,
            }
            text.nameext_from_url(
                f"https://example.com/{name}", file_data)
            file_data.update(base)

            url = f"{cdn}/p/w5000/{file_key}"
            yield Message.Directory, "", file_data
            yield Message.Url, url, file_data


class GalleryphotoGalleryExtractor(GalleryphotoExtractor):
    """Extractor for a gallery.photo gallery"""
    subcategory = "gallery"
    pattern = BASE_PATTERN + r"/gallery/([\w-]+)/?(?:$|\?|#)"
    example = "https://maximkravchenko.gallery.photo/gallery/photos-xdojvm/"

    def __init__(self, match):
        GalleryphotoExtractor.__init__(self, match)
        self.gallery_slug = match.group(2)

    def items(self):
        url = f"{self.root}/gallery/{self.gallery_slug}/"
        rsc = self._fetch_rsc(url)
        cdn, file_keys, names = self._extract_media(rsc)

        if not file_keys:
            self.log.warning(
                "No photos found in gallery '%s'", self.gallery_slug)
            return

        yield from self._yield_photos(
            cdn, file_keys, names, self.gallery_slug)
