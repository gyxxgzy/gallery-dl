# -*- coding: utf-8 -*-

# Copyright 2026 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://wfolio.pro/ disk galleries"""

import json
import re
from html import unescape
from .common import Extractor, Message
from .. import text

BASE_PATTERN = (
    r"(?:https?://)?(?:([\w-]+)\.wfolio\.pro|(dmitrykrapivin\.ru))")


class WfolioExtractor(Extractor):
    """Base class for wfolio disk extractors"""
    category = "wfolio"
    root = ""
    directory_fmt = ("{category}", "{subdomain}", "{project_slug}",
                     "{folder_path}")
    filename_fmt = "{filename}.{extension}"
    archive_fmt = "{piece_id}"
    request_interval = (0.5, 1.5)

    def __init__(self, match):
        if match.group(1):
            self.subdomain = match.group(1)
            if not self.root:
                self.root = f"https://{self.subdomain}.wfolio.pro"
        else:
            self.subdomain = match.group(2).rstrip(".ru")
            if not self.root:
                self.root = f"https://{match.group(2)}"
        Extractor.__init__(self, match)

    def _init(self):
        pass

    def _pieces_page(self, project_slug, folder_path):
        url = (f"{self.root}/disk/{project_slug}/pieces"
               f"?design_variant=masonry&folder_path={folder_path}")
        return self.request(url).text

    def _piece_download_url(self, project_slug, piece_id):
        modal_url = (f"{self.root}/disk/{project_slug}"
                     f"/pieces/downloads/new?piece_id={piece_id}")
        modal = self.request(
            modal_url,
            headers={"Accept": "text/vnd.turbo-stream.html, text/html"},
            fatal=None,
        )
        if not modal:
            return None

        csrf = text.extr(
            modal.text, 'name="authenticity_token" value="', '"')

        if not csrf:
            self.log.warning(
                "Failed to get CSRF token for piece %s", piece_id)
            return None

        download_url = (f"{self.root}/disk/{project_slug}"
                        f"/pieces/downloads?piece_id={piece_id}")
        response = self.request(
            download_url,
            method="POST",
            data={"authenticity_token": csrf, "size": "original"},
            headers={
                "Accept": "text/vnd.turbo-stream.html, text/html, "
                          "application/xhtml+xml",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.root,
                "Referer": f"{self.root}/disk/{project_slug}",
                "X-CSRF-Token": csrf,
                "X-Requested-With": "XMLHttpRequest",
            },
            fatal=None,
        )
        if not response:
            return None

        cdn_url = text.extr(
            response.text, 'action="redirect" target="', '"')
        if not cdn_url:
            self.log.warning(
                "Failed to get download URL for piece %s", piece_id)
            return None

        return cdn_url

    def _extract_versions(self, html):
        """Extract fallback URLs from data-gallery-versions attributes"""
        versions_raw = re.findall(
            r'data-gallery-versions="([^"]+)"', html)
        fallback_urls = []
        for raw in versions_raw:
            try:
                versions = json.loads(unescape(raw))
                best = max(versions, key=lambda v: v.get("w", 0) * v.get("h", 0))
                src = best.get("src", "")
                if src.startswith("//"):
                    src = "https:" + src
                fallback_urls.append(src)
            except Exception:
                fallback_urls.append(None)
        return fallback_urls

    def _yield_pieces(self, html, project_slug, folder_path):
        """Yield messages for all pieces found in the HTML"""
        piece_ids = re.findall(r'data-piece-id="(\d+)"', html)
        filenames = re.findall(
            r'data-gallery-title="([^"]+)"', html)
        fallback_urls = self._extract_versions(html)

        base = {
            "subdomain": self.subdomain,
            "project_slug": project_slug,
            "folder_path": folder_path,
            "count": len(piece_ids),
        }

        for num, (piece_id, filename, fallback_url) in enumerate(
                zip(piece_ids, filenames, fallback_urls), 1):
            file_data = {
                "piece_id": piece_id,
                "filename": filename,
                "num": num,
            }
            text.nameext_from_url(
                f"https://example.com/{filename}", file_data)
            file_data.update(base)

            url = self._piece_download_url(project_slug, piece_id)
            if not url and fallback_url:
                url = fallback_url
            if not url:
                continue

            yield Message.Directory, "", file_data
            yield Message.Url, url, file_data


class WfolioFolderExtractor(WfolioExtractor):
    """Extractor for a wfolio disk folder"""
    subcategory = "folder"
    pattern = (BASE_PATTERN +
               r"/disk/([\w-]+)/((?:[^/?#]+/)*[^/?#]+)/?(?:$|\?|#)")
    example = "https://domino.wfolio.pro/disk/raw2-1fj4t5/photos"

    def __init__(self, match):
        WfolioExtractor.__init__(self, match)
        self.project_slug = match.group(3)
        self.folder_path = match.group(4).rstrip("/")

    def items(self):
        html = self._pieces_page(self.project_slug, self.folder_path)
        yield from self._yield_pieces(
            html, self.project_slug, self.folder_path)


class WfolioDiskExtractor(WfolioExtractor):
    """Extractor for a wfolio disk root (shows subfolders)"""
    subcategory = "disk"
    pattern = BASE_PATTERN + r"/disk/([\w-]+)/?(?:$|\?|#)"
    example = "https://domino.wfolio.pro/disk/raw2-1fj4t5"

    def __init__(self, match):
        WfolioExtractor.__init__(self, match)
        self.project_slug = match.group(3)

    def items(self):
        # First try fetching the disk root page to find subfolders
        main_page = self.request(
            f"{self.root}/disk/{self.project_slug}").text

        folders = []
        seen = set()
        for href in re.findall(
                r'href="/disk/' + re.escape(self.project_slug)
                + r'/([^"]+)"', main_page):
            folder = href.split("/", 1)[0].rstrip("/")
            if folder and folder not in seen:
                seen.add(folder)
                folders.append(folder)

        data = {
            "_extractor": WfolioFolderExtractor,
        }

        if folders:
            for folder in folders:
                folder_url = (f"{self.root}/disk/"
                              f"{self.project_slug}/{folder}")
                yield Message.Queue, folder_url, data
        else:
            # No subfolders - try empty folder path
            html = self._pieces_page(self.project_slug, "")
            piece_ids = re.findall(r'data-piece-id="(\d+)"', html)
            if piece_ids:
                yield from self._yield_pieces(
                    html, self.project_slug, "")
            else:
                self.log.warning(
                    "No files or folders found in %s", self.project_slug)
