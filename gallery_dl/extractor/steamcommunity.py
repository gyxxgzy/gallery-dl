# -*- coding: utf-8 -*-

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://steamcommunity.com/"""

from ..extractor.common import Extractor, Message
from .. import text, dt

BASE_PATTERN = r"(?:https?://)?(?:www\.)?steamcommunity.com"
SECTIONS = {
    "screenshots": 2,
    "artwork"    : 4,
    "images"     : 4,
}


class SteamcommunityExtractor(Extractor):
    """Base class for steamcommunity extractors"""
    category = "steamcommunity"
    root = "https://steamcommunity.com"
    directory_fmt = ("{category}", "{game}", "{section!c}")
    filename_fmt = "{file_id}{title:? //}{description:? //X180/…/}.{extension}"
    archive_fmt = "{game_appid}_{file_id}_{ugc_id}"
    request_interval = (0.5, 1.5)


class SteamcommunitySharedfileExtractor(SteamcommunityExtractor):
    """Extractor for steamcommunity shared files"""
    subcategory = "sharedfile"
    pattern = BASE_PATTERN + r"/sharedfiles/filedetails/\?id=(\d+)"
    example = "https://steamcommunity.com/sharedfiles/filedetails/?id=12345"

    def items(self):
        fid = self.groups[0]
        url = f"{self.root}/sharedfiles/filedetails/?id={fid}"
        page = self.request(url).text

        section = text.extr(
            page, 'class="apphub_sectionTab active "><span>', '<').lower()
        if section not in SECTIONS:
            raise self.exc.AbortExtraction(f"Unsupported section '{section}'")

        meta = {
            "section": section,
            "file_id": fid,
            "url"    : url,
        }

        return self.items_image(page, meta)

    def items_image(self, page, meta):
        extr = text.extract_from(page)

        data = {
            **meta,
            "title"     : text.unescape(extr(
                'class="workshopItemTitle">', "<")),
            "game_appid": extr('class="screenshotAppName', "") or extr(
                "/app/", "/"),
            "game"      : text.unescape(extr(">", "<")),
            "creator_id": extr('class="friendBlockLinkOverlay" '
                               'href="https://steamcommunity.com/', '"',
                               ).rpartition("/")[2],
            "creator"   : text.unescape(extr(
                'class="friendBlockContent">', "<").strip()),
            "size"      : text.parse_bytes(extr(
                'class="detailsStatRight">', "<")[:-1]),
            "date"      : extr('class="detailsStatRight">', "<"),
            "width"     : text.parse_int(extr(
                'class="detailsStatRight">', " x ")),
            "height"    : text.parse_int(extr("", "<")),
            "views"     : text.parse_int(extr("<td>", "<").replace(",", "")),
            "likes"     : text.parse_int(text.remove_html(extr(
                "<tr>", "</")).replace(",", "")),
            "description": text.unescape(extr(
                'id="description"', "") or extr(">", "</textarea>")),
            "extension" : "jpg",  # Guess 'jpg' - Rely on extension fixing
        }

        if "," in (date := data["date"]):
            data["date"] = dt.parse(date, "%d %b, %Y @ %I:%M%p")
        else:
            data["date"] = (dt.parse(date, "%d %b @ %I:%M%p")
                            .replace(year=dt.datetime.now().year))

        img = text.extr(page, '<img id="ActualMedia"', '>')
        src = text.unescape(text.extr(img, 'src="', '"'))
        if (pos := src.find("?")) >= 0:
            src = src[:pos]
        data["ugc_id"] = src[src.find("/ugc/")+5:-1]

        yield Message.Directory, "", data
        yield Message.Url, src, data


class SteamcommunityGameExtractor(SteamcommunityExtractor):
    subcategory = "game"
    pattern = (BASE_PATTERN + r"/app/(\d+)/"
               r"((?:screenshot|image)s)(?:/?\?([^#]+))?")
    example = "https://steamcommunity.com/app/12345/screenshots/"

    def items(self):
        per_page = 10

        if self.config("metadata"):
            data = {"_extractor": SteamcommunitySharedfileExtractor}
            base = "https://steamcommunity.com/sharedfiles/filedetails/?id="
            find = SteamcommunitySharedfileExtractor.pattern.findall
            for page in self._pagination(per_page):
                post_ids = find(page)
                for pid in post_ids:
                    yield Message.Queue, base + pid, data
                if len(post_ids) < per_page:
                    break
        else:
            for page in self._pagination(per_page):
                cards = page.split("<div data-panel=")
                del cards[0]
                for card in cards:
                    data = self._extract_card(card)
                    src = text.unescape(data.pop("url"))
                    if (pos := src.find("?")) >= 0:
                        src = src[:pos]
                    data["ugc_id"] = src[src.find("/ugc/")+5:-1]

                    yield Message.Directory, "", data
                    yield Message.Url, src, data
                if len(cards) < per_page:
                    break

    def _extract_card(self, card):
        extr = text.extract_from(card)
        data = {
            "post_url"   : extr('data-modal-content-url="', '"'),
            "game_appid" : extr('data-appid="', '"'),
            "file_id"    : extr('data-publishedfileid="', '"'),
            "section"    : extr('class="apphub_CardContentType">', '<'),
            "url"        : extr('src="', '"'),
            "comments"   : extr('class="apphub_CardCommentCount">', '<'),
            "description": text.unescape(extr(
                'class="apphub_CardContentTitle ellipsis">', '<')).strip(),
            "creator_id" : extr('data-miniprofile="', '"'),
            "extension"  : "jpg",
        }

        creator = extr('class="apphub_CardContentAuthorName', "</")
        data["creator"] = text.unescape(creator[creator.rfind(">")+1:])
        data["game"] = self.cache(
            self._extract_game, data["game_appid"], _mem=False)
        return data

    def _extract_game(self, appid):
        url = f"{self.root}/app/{appid}/"
        page = self.request(url).text
        name = text.extr(page, 'class="apphub_AppName', '<')
        return text.unescape(name[name.rfind(">")+1:])

    def _pagination(self, per_page=10):
        appid, type, qs = self.groups
        url = f"{self.root}/app/{appid}/homecontent/"
        params = text.parse_query(qs)
        pnum = text.parse_int(params.get("p"), 1)

        params = {
            "userreviewsoffset"  : "0",
            "p"                  : None,
            "workshopitemspage"  : None,
            "readytouseitemspage": None,
            "mtxitemspage"       : None,
            "itemspage"          : None,
            "screenshotspage"    : None,
            "videospage"         : None,
            "artpage"            : None,
            "allguidepage"       : None,
            "webguidepage"       : None,
            "integratedguidepage": None,
            "discussionspage"    : None,
            "numperpage"         : str(per_page),
            "browsefilter"       : "trend",
            "appid"              : appid,
            "appHubSubSection"   : str(SECTIONS[type]),
            "l"                  : "english",
            "filterLanguage"     : "default",
            "searchText"         : "",
            "maxInappropriateScore": "100",
            "forceanon"          : "1",
            **params,
        }
        headers = {
            "Accept": "text/javascript, text/html, application/xml, "
                      "text/xml, */*",
            "X-Requested-With": "XMLHttpRequest",
            "X-Prototype-Version": "1.7",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        while True:
            params["p"] = \
                params["workshopitemspage"] = \
                params["readytouseitemspage"] = \
                params["mtxitemspage"] = \
                params["itemspage"] = \
                params["screenshotspage"] = \
                params["videospage"] = \
                params["artpage"] = \
                params["allguidepage"] = \
                params["webguidepage"] = \
                params["integratedguidepage"] = \
                params["discussionspage"] = str(pnum)
            html = self.request(url, params=params, headers=headers).text

            yield html

            pnum += 1
