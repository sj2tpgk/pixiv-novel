#!/usr/bin/env python3

import argparse
import base64
import colorsys
import dataclasses
import datetime
import gzip
import html.parser
import http.server
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import traceback
import time
import urllib.error, urllib.parse, urllib.request
import webbrowser
from html import escape, unescape
from typing import *

# base
# TODO custom style (e.g. load _style.css)
# TODO no-r mode
# TODO help page on how to get cookies.txt
# TODO html extractor: get innerHTML? (do ranking descriptions contain html tags??)
# TODO other websites? (and rename to ja-novels.py)
# TODO chara name db in separate files (one file per each series, and embed on build)
# TODO url like /search/abc/6?compact=... (for better history integration)

# as a cli util
# TODO json api (like &json=1, for cli, also for test automation)


### Configuration

CONFIG = {
    "cachedir" : "",     # Cache directory ('' to disable)
    "nocolor"  : False,  # Disable colorizing character names?
    "savedir"  : "",     # Save novels directory ('' to disable)
    "noimage"  : False,  # Disable embedding images?
}

emoji = { "love": "💙", "search": "🔍" }

def fcache(expiry=600, namef=lambda:"None"):
    def decor(f):
        def f2(*args, **kwargs):
            return withFileCache(namef(*args, **kwargs), lambda: f(*args, **kwargs), expiry)
        return f2
    return decor


### HTTP Server

def run_threaded_https_server(RequestHandlerClass, host="0.0.0.0", port=8030, https=False, certfile="", keyfile=""):
    """Run http server with threading and ssl support.
if `https` is true, (`certfile`, `keyfile`) is passed to load_cert_chain.
Use `openssl req -new -x509 -keyout CERTFILE -out KEYFILE -days 365 -nodes`."""
    import http.server, ssl
    def ssl_wrap(httpd, certfile, keyfile):
        # https://gist.github.com/DannyHinshaw/a3ac5991d66a2fe6d97a569c6cdac534
        ctx = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    httpd = http.server.ThreadingHTTPServer((host, port), RequestHandlerClass)
    if https:
        ssl_wrap(httpd, certfile, keyfile)
    httpd.serve_forever()

class MyRequestHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        cli = self.client_address
        logging.debug(("%s:%s " + format) % (cli[0], cli[1], *args))

    def send(self, status, mime, headers, body):

        gz = "gzip" in (self.headers["Accept-Encoding"] or "")

        if type(body) is str:
            body = body.encode()
        if gz:
            body = gzip.compress(body)

        self.send_response(status)

        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-type", mime)
        if gz: self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        try:
            self.wfile.write(body)
        except BrokenPipeError:
            logging.warning("BrokenPipeError")
            return

    def do_GET(self):

        parsed = urllib.parse.urlparse(self.path)
        paths  = [x for x in parsed.path.split("/") if x]
        param  = { k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items() }

        try:
            status, mime, headers, body = self.action(paths, param)
        except Exception as e:
            print(traceback.format_exc(), file=sys.stderr)
            logging.error("Error occured\n" + str(e))
            status, mime, headers, body = 500, "text/plain", [], "500 Internal Server Error"

        self.send(status, mime, headers, body)

    def action(self, paths, param):
        if len(paths) == 0:
            return self.action(["pixiv", "ranking"], param)
        elif len(paths) == 1:
            return self.action(["pixiv"] + paths, param)
        elif len(paths) == 2:
            site, cmd = paths[0], paths[1]
            # Select backend for site
            try:
                backend = BACKEND_TABLE[site]
            except KeyError:
                return 400, "text/plain", [], f"No such site: {site}"
            # Select data generator function
            try:
                makeData = getattr(backend, cmd.title()) # e.g. BackendPixiv.Novel
            except AttributeError:
                return 400, "text/plain", [], f"No such cmd on site: {cmd} on {site}"
            # Get data
            data = makeData(**param).data() # e.g. BackendPixiv.Novel(**param).data() : viewNovelData
            # Select view function
            makeView = VIEW_TABLE[type(data)]
            # Render view
            html = makeView(data) # e.g. viewNovel(data:viewNovelData) : str (html as a string)
            # Save function
            if CONFIG["savedir"] and (type(data) is viewNovelData):
                saveFile(data.title,
                         html,
                         prefix=getRSign(data.rate),
                         suffix=f" - {data.site} - {data.id}.html")
            # Send response
            status, mime, headers, body = 200, "text/html", [], html
            return status, mime, headers, body
        else:
            return 400, "text/plain", [], f"Invalid request"


### Backend

class BackendPixiv:

    class Search:

        def __init__(self, q, bookmarkCount=0, page=1, npages=1, mode="detailed", **_):
            self._query         = q
            self._bookmarkCount = int(bookmarkCount)
            self._page          = max(1, int(page))
            self._npages        = min(1, max(3, int(npages)))
            self._mode          = mode

        def data(self):

            dataList = [
                x for x in self._getDataList()
                if int(x["bookmarkCount"]) >= self._bookmarkCount
            ]

            items = [viewSearchDataItem(
                title  = x["title"],
                id     = x["id"],
                tags   = x["tags"],
                rate   = getRSign(x["xRestrict"]),
                desc   = x["description"],
                score  = x["bookmarkCount"],
                length = x["textCount"],
                user   = (x["userId"], x["userName"])
            ) for x in dataList]

            attr = lambda a, d: getattr(self, a) if hasattr(self, a) else d

            form = [
                { "name": "q", "type": "text", "disp": 1, "field": "query", "args": { "placeholder": "search" } },
                { "name": "bookmarkCount", "type": "number", "disp": 2, "label": f"{emoji['love']}:", "field": "score" },
                { "name": "page", "type": "number", "disp": 2, "label": f"Page:", "field": "page", "args": { "min": 1 } },
                { "name": "npages", "type": "select", "disp": 2, "args": [("1", "1 page"), ("2", "2 pages"), ("3", "3 pages")], "field": "npages" },
                { "name": "mode", "type": "hidden", "disp": 2, "field": "mode" },
            ]

            d = viewSearchData(
                site   = "pixiv",
                title  = self._html_title(),
                query  = attr("_query", ""),
                score  = attr("_bookmarkCount", 0),
                page   = attr("_page", 1),
                npages = attr("_npages", 0),
                mode   = self._mode,
                items  = items,
                form   = form,
                viewOption = viewSearchDataViewOption(
                    htmlHeader = lambda: self._html_header(self._mode == "compact"),
                    htmlPrevNextLinks = self._html_prevnext_links(),
                )
            )

            return d

        def _getDataList(self):
            dataList = []
            for i in range(self._npages):
                resJson = Resources.Pixiv.jsonSearch(self._query, i+self._page)
                dataList += resJson["body"]["novel"]["data"]
            return dataList

        def _html_title(self):
            return f""

        def _html_header(self, compact):
            return ""

        def _html_prevnext_links(self): return True

    class User(Search):

        def __init__(self, id, bookmarkCount=0, mode="detailed"):
            self._userID        = int(id)
            self._bookmarkCount = int(bookmarkCount)
            self._mode          = mode

        def _getDataList(self):

            # First, response includes all novelIDs of user
            json1 = Resources.Pixiv.jsonUserAll(self._userID)
            novels = json1["body"]["novels"] # a dict or a empty list
            if len(novels) == 0:
                return []
            novelIDs = list(novels.keys())

            # Next, get data for each novel (100 novels at once)
            # So, 0 novel = 0 request, 1-100 novels = 1 request, 101-200 = 2 etc.
            dataList = []
            n = 100
            numRequests = 1 + int((len(novelIDs)-1)/n)
            for ids in [novelIDs[n*i:n*(i+1)] for i in range(numRequests)]:
                json2 = Resources.Pixiv.jsonUserNovels(self._userID, ids)
                dataList += list(json2["body"]["works"].values())

            return dataList

        def _html_title(self):
            return f"User {self._userID}"

        def _html_header(self, compact):
            return ""

        def _html_prevnext_links(self): return False

    class Ranking(Search):

        _modeNames = {
            "daily":           "デイリー",
            "weekly":          "ウィークリー",
            "monthly":         "マンスリー",
            "rookie":          "ルーキー",
            "weekly_original": "オリジナル",
            "male":            "男子に人気",
            "female":          "女子に人気",
            "daily_r18":       "デイリー R-18",
            "weekly_r18":      "ウィークリー R-18",
            "male_r18":        "男子に人気 R-18",
            "female_r18":      "女子に人気 R-18",
        }

        def __init__(self, kind="daily", date="", mode="detailed"):
            self._kind = kind

            # set self._date to a date object (at most yesterday)
            if re.match(r"\d\d\d\d-\d\d-\d\d", date):
                d = datetime.date.fromisoformat(date)
                y = yesterday()
                self._date = d if d <= y else y
            else:
                self._date = yesterday()

            self._mode = mode
            self._bookmarkCount = 0

        def _cacheName(self):
            return f"pixiv-ranking-{self._kind}-{self._date.isoformat().replace('-', '')}"

        def _getDataList(self):
            dataList = []
            for page in [1, 2]:
                res = Resources.Pixiv.rankingPhp(self._kind, self._date, page)
                dataList += self._getDataListFromHTML(res)
            return dataList

        def _getDataListFromHTML(self, html):
            data = []

            p = StringParser(html) # faster than html parser
            toInt = lambda s: int(re.sub(r"\D+", "", s))
            for _ in range(50):
                d = {}
                # one novel for each ._novel-item
                if p.seek("_novel-item") == -1:
                    break
                d["xRestrict"]     = "r18" in self._kind
                # attrs from img.cover
                d["title"]         = re.sub(r"/.*", "", p.extract('alt="', '"'))
                d["tags"]          = p.extract('data-tags="', '"').split()
                d["id"]            = p.extract('data-id="', '"')
                # innerHTML from div.chars
                d["textCount"]     = toInt(p.extract('<div class="chars">', '文字</div>'))
                # innerHTML from a.bookmark-count
                d["bookmarkCount"] = toInt(p.extract('bookmark-count', '</i>', '</a>'))
                # innerHTML from p.novel-caption
                d["description"]   = unescape(p.extract('<p class="novel-caption">', '</p>', default="").strip())
                # attrs from a.user
                d["userId"]        = p.extract('data-user_id="', '"')
                d["userName"]      = p.extract('data-user_name="', '"')
                # add entry to list
                data.append(d)

            return data

        def _html_title(self):
            return f"{self._modeNames[self._kind]} ランキング {self._date}"

        def _html_header(self, compact):
            # links for other rankings
            hrefBase = mkurl("ranking", mode="compact" if compact else "detailed", date=self._date)
            modeLinks1 = "\n".join([f"""<a href="{hrefBase}&kind={kind}"{ ' class="ranking-selected"' if kind == self._kind else ""}>{self._modeNames[kind]}</a>""" for kind in self._modeNames.keys() if not "r18" in kind])
            if Resources.Pixiv.hasCookie():
                modeLinks2 = "<span>R-18:</span>"
                modeLinks2 += "\n".join([f"""<a href="{hrefBase}&kind={kind}"{ ' class="ranking-selected"' if kind == self._kind else ""}>{self._modeNames[kind].replace(" R-18", "")}</a>""" for kind in self._modeNames.keys() if "r18" in kind])
            else:
                modeLinks2 = "R-18 ランキングを見るには cookies.txt が必要です。"
            modeLinksCSS = """
                #ranking-modes { margin: .8em 0; font-size: small; line-height: 1.8 }
                #ranking-modes a { margin-right: 1.4em }
                #ranking-modes span { margin-right: 1.0em }
                .ranking-selected { font-weight: bold }
            """
            modeLinks = f"""
                <style>
                    {modeLinksCSS}
                </style>
                <p id="ranking-modes">
                    {modeLinks1}
                    <br>
                    {modeLinks2}
                </p>"""

            # construct html
            return f"""
                {modeLinks}
                <form style="text-align: center; margin: .5em 0" action=ranking>
                    <label for="date">日付:</label>
                    <input type="date" id="date" name="date" value="{self._date}" max="{yesterday()}">
                    <input type="submit" value="{emoji['search']}">
                    <input type="hidden" name="kind" value="{self._kind}">
                    <input type="hidden" name="mode" value="{1 if compact else ''}">
                </form>
            """

        def _html_prevnext_links(self): return False

    class Novel:

        def __init__(self, id):
            self._novelID = id

        def data(self):
            jso  = Resources.Pixiv.novelJson(self._novelID)["body"]

            o_content = jso["content"]
            for (regex, replace) in [
                    (r"$", "<br>"),
                    (r"\[newpage\]", "<hr>\n"),
                    (r"\[chapter:(.*?)\]", "<h2>\\1</h2>\n"),
                    (r"\[\[rb:(.*?)(>|&gt;)(.*?)\]\]", "<ruby>\\1<rt>\\3</rt></ruby>"),
                    ]:
                o_content = re.sub(regex, replace, o_content, flags=re.MULTILINE)

            # threshold on total embedded image size
            # if total image size exceeds MAX_TOTAL_IMAGE_SIZE, return only link next time
            MAX_TOTAL_IMAGE_SIZE  = 0 if CONFIG["noimage"] else (5 * 10**6) # 5 MBytes
            currentTotalImageSize = 0 # 0 Byte

            # pixivimage
            def getPixivImg(imgId):
                assert imgId.isdigit()
                jso = Resources.Pixiv.artworkPagesJson(imgId)
                url = jso["body"][0]["urls"]["original"]
                return url, (currentTotalImageSize < MAX_TOTAL_IMAGE_SIZE) and Resources.Pixiv.artworkImage(url)

            # uploadedimage
            def getUploadedImg(imgId):
                assert imgId.isdigit()
                url = jso["textEmbeddedImages"][imgId]["urls"]["original"]
                return url, (currentTotalImageSize < MAX_TOTAL_IMAGE_SIZE) and Resources.Pixiv.uploadedImage(url)

            # create image tag
            def getImgTag(imgType:"Literal['uploadedimage', 'pixivimage']", imgId):
                nonlocal currentTotalImageSize
                url, img = (getPixivImg if imgType == "pixivimage" else getUploadedImg)(imgId)
                if not img:
                    return f"""<figure><a href="{url}">[{imgType}:{imgId}]</a></figure>"""
                currentTotalImageSize += len(img)
                imgB64 = base64.b64encode(img).decode("utf-8")
                return f"""<figure><a href="{url}"><img src=\"data:image/png;base64,{imgB64}\" alt=\"[{imgType}:{imgId}]\" style=\"width: 100%\"></a></figure>"""

            # replace image links
            o_content = re.sub(r"\[(pixivimage|uploadedimage):(.*?)\]", lambda m: getImgTag(m.group(1), m.group(2)), o_content)

            # colorize character names
            if not CONFIG["nocolor"]:
                o_content = CharaColor.colorHTML(o_content)

            tags = [x["tag"] for x in jso["tags"]["tags"]]

            # embed json
            # e.g. <div data='{"x":10,"y":"あ"}'></div>
            # jso1 = json.dumps(jso, ensure_ascii=False, separators=(',', ':'))
            # for (fromStr, toStr) in [ # unnecessary if b64 is used
            #         ("'", "&#39;"), # ("\"", "&quot;"), ("<", "&lt;"), (">", "&gt;")
            #         ]:
            #     jso1 = jso1.replace(fromStr, toStr)
            # jso2 = gzip.compress(jso1.encode("utf-8"))
            # jso3 = base64.b64encode(jso2).decode("utf-8")

            data = viewNovelData(
                site  = "pixiv",
                title = jso["title"],
                id    = jso["id"],
                rate  = getRSign(jso["xRestrict"]),
                body  = o_content,
                desc  = replaceLinks(jso["description"]),
                tags  = tags,
                orig  = f"https://www.pixiv.net/novel/show.php?id={jso['id']}",
                user  = (jso["userId"], jso["userName"]),
                score = jso["bookmarkCount"],
                date  = datetime.datetime.strptime(jso["createDate"][:10], "%Y-%m-%d"),
            )

            return data

        def _extractData(self, html): # parse show.php and get json inside meta[name=preload-data]
            # Extract json string
            # querySelector("meta[name=meta-preload-data]").content
            s = sfind(html, ["meta-preload-data\" content='", "'"])
            s = unescape(s)

            # Extract part of json
            json1 = json.loads(s)
            return json1["novel"][list(json1["novel"].keys())[0]]

BACKEND_TABLE = {
    "pixiv": BackendPixiv,
}


### Views

@dataclasses.dataclass
class viewNovelDataPage:
    page:  int
    title: str
    id:    str
    desc:  str
    date:  datetime.datetime

@dataclasses.dataclass
class viewNovelData:
    site:  str
    title: str
    id:    str # content id (used for id= param)
    rate:  Literal["", "R", "G"]
    body:  str
    desc:  str
    tags:  list[str]
    orig:  str
    user:  tuple[str, str] # (id, name) such that /<site>/user?id=<id> will work
    score: int
    date:  datetime.datetime
    pages: Optional[list[viewNovelDataPage]] = None # For toc page (mokuji)

def viewNovel(d:viewNovelData):

    # print(json.dumps(dataclasses.asdict(dataclasses.replace(d, body='')), default=str, ensure_ascii=False, indent=2))

    o_css = """
        body { max-width: 700px; margin: 1em auto; padding: 0 .5em; }
        @media screen and (max-aspect-ratio: .75) and (max-width: 13cm) { /* Mobile */
            body { max-width: 100%; margin: 0.5em 0.5em }
        }
        #novel { line-height: 1.9; border-bottom: solid #888 1px; margin-bottom: 2em; padding-bottom: 3em; }
        #data { display: none }
    """

    o_tags = ",\n".join(f"<a href='{mkurl(d.site, 'search', q=x)}'>{x}</a>" for x in d.tags)

    o_rSign = re.sub("^ *", " ", d.rate) if d.rate else ""

    o_info = f"""
        <p> タグ: {o_tags} </p>
        <p>
            <a href="{d.orig}">{d.site.capitalize()}で開く</a>
            ID:{d.id}
            U:<a href="{mkurl(d.site, 'user', id=d.user[0])}">{d.user[0]}</a>
            B:{d.score}
            D:{d.date.strftime("%Y-%m-%d")}
        </p>
    """

    nl = "\n"
    o_toc = "" if not d.pages else f"""
        <ul>
            {nl.join(f'''
                <li>
                    <span style="display:none">{p.page}</span>
                    <a href="{mkurl(d.site, 'novel', id=p.id, page=p.page)}">
                        {escape(p.title)}
                    </a>
                    <br>
                    <div>{p.desc}</div>
                </li>
            ''' for p in d.pages)}
        </ul>
    """

    o_html = f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <title>{o_rSign}{d.title} - {d.site}</title>
            <meta http-equiv="content-type" content="text/html; charset=utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <!--<link rel="stylesheet" href="_style.css">-->
            <style>{o_css}</style>
        </head>
        <body>
            <h1>{d.title}</h1>
            <div id="novel">
                {d.body}
                {o_toc}
            </div>
            <div id="info"> <p> {d.desc} </p> {o_info} </div>
        </body>
        </html>
    """
    o_html = "\n".join(x.strip() for x in o_html.splitlines())
    # <div id="data" data-novels='{o_json}'></div>

    return o_html

@dataclasses.dataclass
class viewSearchDataItem:
    title:  str
    id:     str
    tags:   list[str]
    rate:   Literal["", "R", "G"]
    desc:   str
    score:  int
    length: int
    user:   tuple[str, str] # (id, name)

@dataclasses.dataclass
class viewSearchDataViewOption:
    htmlHeader: Callable = lambda: ""
    htmlPrevNextLinks: bool = True

@dataclasses.dataclass
class viewSearchData:
    site:   str
    title:  str # if nonempty used as title
    query:  str
    score:  int # TODO: replace with generic filtering condition
    # filter: dict
    page:   int
    npages: int
    mode:   Literal["detailed", "compact", "tiled"] # view mode
    items:  list[viewSearchDataItem]
    form:   list = dataclasses.field(default_factory=lambda: [])
    viewOption: Optional[viewSearchDataViewOption] = None

def viewSearch(d:viewSearchData):

    # create form from a specification and default values
    def makeForm(formSpec, values, action):
        elems1, elems2 = [], []
        for x in formSpec:
            if x["type"] == "text":
                elem = f'<input type=text name="{x["name"]}" value="{values[x["name"]]}" placeholder="{x.get("args", {}).get("placeholder", 0)}">'
            elif x["type"] == "number":
                elem = f'<input type=number name="{x["name"]}" value="{values[x["name"]]}" size=3 min="{x.get("args", {}).get("min", 0)}">'
            elif x["type"] == "hidden":
                elem = f'<input type=hidden name="{x["name"]}" value="{values[x["name"]]}">'
            elif x["type"] == "select":
                elem = f'<select name="{x["name"]}">\n'
                for value, text in x["args"]:
                    selected = "selected" if value == values[x["name"]] else ""
                    elem += f'<option value="{value}" {selected}>{text}</option>\n'
                elem += "</select>"
            else:
                assert False, f'Invalid formSpec: {x}'
            if x.get("label"):
                elem = f'<label>{x["label"]}{elem}</label>'
            if   x["disp"] == 1: elems1.append(elem)
            elif x["disp"] == 2: elems2.append(elem)
        nl = "\n"
        html = f"""
            <form style="text-align: right; line-height: 1.5" action="{action}">
                <details title="detailed search" style="display: inline">
                    <summary>
                        ...&nbsp;&nbsp;
                        {nl.join(elems1)}
                        <input type=submit value="{emoji["search"]}" title="search">
                    </summary>
                    {nl.join(elems2)}
                </details>
            </form>
        """
        return html

    # search bar
    def searchBar():
        values = { x["name"]: getattr(d, x["field"], x.get("default", "")) for x in d.form }
        action = f"/{d.site}/search"
        return makeForm(d.form, values, action)

    # links (next/prev, toggle compact)
    def navLinks():
        values = { x["name"]: getattr(d, x["field"], x.get("default", "")) for x in d.form }
        hrefPrev   = mkurl(**{ **values, "page": max(1, d.page-d.npages) })
        hrefNext   = mkurl(**{ **values, "page": d.page+d.npages })
        hrefToggle = mkurl(**{ **values, "mode": "detailed" if d.mode == "compact" else "compact" })
        html = f"""
            <div id="nav" style="display: flex">
                <span style="flex: 1">
                    <a href="{hrefToggle}">{"詳細表示" if d.mode == "compact" else "コンパクト表示"}</a>
                </span>
                <span style="flex: 1"></span>
        """
        if d.viewOption and d.viewOption.htmlPrevNextLinks:
            html += f"""
                <span style="flex: 1; text-align: right">
                    <a href='{hrefPrev}'>前へ</a>
                    <a href='{hrefNext}'>次へ</a>
                </span>
            """
        html += """
            </div>
        """
        return html

    # common css
    css = """
        body { max-width: 750px; margin: 1em auto; padding: 0 .5em; }
        #main { margin: 1em 0 }
        li p { margin: 1.5em 0 }
        li > a.title { color: white }
        td:not(:nth-child(4)) { text-align: center; padding: 0 .35em }
        td:nth-child(4) { padding-left: 2em }
    """

    # novels
    novels = "<table>" if d.mode == "compact" else "<ul>"
    for x in d.items: # self._novels
        href = mkurl(d.site, "novel", id=x.id)
        if d.mode == "compact":
            novels += f"<tr><td><a href=\"{href}\">{x.id}</a></td><td>{re.sub('^ *', ' ', x.rate) if x.rate else ''}</td><td>{x.score}</td><td>{x.title}</td></tr>\n"
        else:
            desc = "<br>".join(replaceLinks(x.desc).split("<br />")[0:5])
            desc = addMissingCloseTags(desc, tags=["b", "s", "u", "strong"])
            tags = ", ".join([f"<a href=\"/{d.site}/search?q={escape(y)}\">{y}</a>" for y in x.tags])
            novels += f"<li>{x.title} ({x.length}字) <a href=\"{href}\">[{x.id}]</a><p>{desc}</p>{emoji['love']} {x.score}<br>{tags}</li><hr>\n"
    novels += "</table>" if d.mode == "compact" else "</ul>"

    # search bar
    o_searchBar = searchBar()

    o_header = d.viewOption.htmlHeader() if d.viewOption else ""

    o_nav = navLinks()

    o_title = d.title or f"{d.query}{(f' ({d.page})' if d.page > 1 else '')}"

    # final html
    o_html = f"""
        <!DOCTYPE html>
        <html lang="ja">
        <head>
            <title>{o_title} - {d.site}</title>
            <meta http-equiv="content-type" content="text/html; charset=utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <style> {css} </style>
        </head>
        <body>
            <h1>{o_title}</h1>
            {o_searchBar}
            {o_header}
            <hr>
            {o_nav}
            <div id="main"> {novels} </div>
            {o_nav}
        </body>
        </html>
    """
    o_html = "\n".join(x.strip() for x in o_html.splitlines())
    return o_html

VIEW_TABLE = {
    viewNovelData:  viewNovel,
    viewSearchData: viewSearch,
}


### Resources

class Resources:

    # Resource downloading often breaks due to expired cookies, change in request headers etc.
    # So we want unit-testable functions for each resource.

    class Pixiv:

        # 404 without headers
        _headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'ja,en-US;q=0.7,en;q=0.3',
            'Accept-Encoding': 'gzip',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Pragma': 'no-cache',
            'Referer': 'https://www.pixiv.net/',
            'Cache-Control': 'no-cache'
        }

        # cookie = readCookiestxtAsHTTPCookieHeader("../cookies.txt", "pixiv.net")
        cookie = None

        @classmethod
        def hasCookie(cls):
            return bool(cls.cookie)

        @classmethod
        def cookieHeader(cls):
            return { "cookie": cls.cookie } if cls.hasCookie() else {}

        @classmethod
        @fcache(3*86400, lambda cls, novelID: f"pixiv-novelJson-{novelID}")
        def novelJson(cls, novelID):
            url = f"https://www.pixiv.net/ajax/novel/{novelID}?lang=ja"
            return httpGet(url, fmt="json", headers=[cls._headers, cls.cookieHeader()])

        @classmethod
        @fcache(3600, lambda cls, mode, date, page: f"pixiv-ranking-{mode}-{date.isoformat().replace('-', '')}-{page}")
        def rankingPhp(cls, mode, date: datetime.date, page: int):
            # Check modes
            MODES = { "daily", "weekly", "monthly", "rookie", "weekly_original", "male", "female", "daily_r18", "weekly_r18", "male_r18", "female_r18", }
            if not mode in MODES:
                raise Exception(f"Resources.Pixiv.rankingPhp: unknown mode {mode} (expected one of {MODES})")
            if (not cls.hasCookie()) and mode.endswith("r18"):
                raise Exception(f"Resources.Pixiv.rankingPhp: cookie is needed to view ranking of mode {mode}")
            # Make URL
            dateiso = date.isoformat()
            url = f"https://www.pixiv.net/novel/ranking.php?mode={mode}&date={dateiso.replace('-', '')}"
            if page > 1:
                url += f"&page={page}"
            # Download
            return httpGet(url, headers=[cls._headers, (cls.cookieHeader() if mode.endswith("r18") else {})])

        @classmethod
        @fcache(3600, lambda cls, userID: f"pixiv-user-{userID}")
        def jsonUserAll(cls, userID):
            url = f"https://www.pixiv.net/ajax/user/{userID}/profile/all?full=1&lang=ja"
            return httpGet(url, fmt="json", headers=[cls._headers, cls.cookieHeader()])

        @classmethod
        @fcache(3600, lambda cls, userID, novelIDs: f"pixiv-user-{userID}-{sum(map(int, novelIDs))}")
        def jsonUserNovels(cls, userID, novelIDs):
            n = 100
            if len(novelIDs) <= 0:
                raise Exception(f"Resources.Pixiv.apiUserIds: at least 1 novel IDs are required")
            if len(novelIDs) > n:
                raise Exception(f"Resources.Pixiv.apiUserIds: at most {n} novel IDs are allowed to query at once; got {len(novelIDs)}")
            idsParams = "&".join([f"ids[]={x}" for x in novelIDs])
            url = f"https://www.pixiv.net/ajax/user/{userID}/profile/novels?{idsParams}"
            return httpGet(url, fmt="json", headers=[cls._headers, cls.cookieHeader()])

        @classmethod
        @fcache(600, lambda cls, word, page: f"pixiv-search-{''.join(hex(x)[2:] for x in word.encode())}-{page}")
        def jsonSearch(cls, word, page):
            params = f"?word={word}&order=date_d&mode=all&p={page}&s_mode=s_tag&lang=ja"
            url = f"https://www.pixiv.net/ajax/search/novels/{word}{params}"
            return httpGet(url, fmt="json", headers=[cls._headers, cls.cookieHeader()])

        @classmethod
        def artworkPagesJson(cls, id):
            url = f"https://www.pixiv.net/ajax/illust/{id}/pages?lang=ja"
            try:
                return httpGet(url, fmt="json", headers=[cls._headers, cls.cookieHeader(), { "Accept": "application/json" }])
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    logging.warning("Resources.Pixiv.artworkPagesJson: Artwork not found" + (", or cookie is required to view this artwork" if not cls.hasCookie() else "") + ":", e)
                else:
                    logging.error("Resources.Pixiv.artworkPagesJson: Unknown error:", e)
                raise e

        @classmethod
        def artworkImage(cls, url):
            headers2 = { "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8" }
            return httpGet(url, fmt="bytes", headers=[cls._headers, headers2])

        @classmethod
        def uploadedImage(cls, url):
            # headers2 = { "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8" }
            return httpGet(url, fmt="bytes", headers=cls._headers)


### Character name colorizer

class CharaColor:
    _lightness = 0.52
    _saturation = 0.7

    _db0 = {
        # _db0[series][characterName] = color (format: "#xxxxxx" or "#xxx")
        # Idolmaster (https://imas-db.jp/misc/color.html) (imcomplete, and not very strict)
        "アイドルマスターミリオンライブ": {
            "P": "#555555", "Ｐ": "#555555",
            "天海 春香": "#e22b30", "如月 千早": "#2743d2", "萩原 雪歩": "#d3dde9", "高槻 やよい": "#f39939", "秋月 律子": "#01a860", "三浦 あずさ": "#9238be", "水瀬 伊織": "#fd99e1", "菊地 真": "#515558", "双海 亜美": "#ffe43f", "双海 真美": "#ffe43f", "星井 美希": "#b4e04b", "我那覇 響": "#01adb9", "四条 貴音": "#a6126a", "音無 小鳥": "#00ff00",
            "伊吹 翼": "#fed552", " エミリー": "#554171", "大神 環": "#ee762e", "春日 未来": "#ea5b76", "北上 麗花": "#6bb6b0", "北沢 志保": "#afa690", "木下 ひなた": "#d1342c", "高坂 海美": "#e9739b", "桜守 歌織": "#274079", "佐竹 美奈子": "#58a6dc", "篠宮 可憐": "#b63b40", "島原 エレナ": "#9bce92", " ジュリア": "#d7385f", "白石 紬": "#ebe1ff", "周防 桃子": "#efb864", "高山 紗代子": "#7f6575", "田中 琴葉": "#92cfbb", "天空橋 朋花": "#bee3e3", "徳川 まつり": "#5abfb7", "所 恵美": "#454341", "豊川 風花": "#7278a8", "中谷 育": "#f7e78e", "永吉 昴": "#aeb49c", "七尾 百合子": "#c7b83c", "二階堂 千鶴": "#f19557", "野々原 茜": "#eb613f", "箱崎 星梨花": "#ed90ba", "馬場 このみ": "#f1becb", "福田 のり子": "#eceb70", "舞浜 歩": "#e25a9b", "真壁 瑞希": "#99b7dc", "松田 亜利沙": "#b54461", "宮尾 美也": "#d7a96b", "最上 静香": "#6495cf", "望月 杏奈": "#7e6ca8", "百瀬 莉緒": "#f19591", "矢吹 可奈": "#f5ad3b", "横山 奈緒": "#788bc5", " ロコ": "#fff03c",
            "青羽 美咲": "#57c7c4",
            " 玲音": "#512aa3", " 詩花": "#e6f9e5", "奥空 心白": "#fefad4",
            "日高 愛": "#e85786", "水谷 絵理": "#00adb9", "秋月 涼": "#b2d468",
        },
        "アイドルマスターシンデレラガールズ": {
            "P": "#555555", "Ｐ": "#555555",
            " アナスタシア": "#b1c9e8", "及川 雫": "#f4f9ff", "大槻 唯": "#f6be00", "乙倉 悠貴": "#e3bec3", "喜多見 柚": "#f0ec74", "桐生 つかさ": "#ab4ec6", "小日向 美穂": "#db3fb1", "高森 藍子": "#ceea80", "道明寺 歌鈴": "#d22730", " ナターリア": "#f5633a", "難波 笑美": "#e13c30", "浜口 あやめ": "#450099", "姫川 友紀": "#ee8b00", "藤原 肇": "#9595d2", "星 輝子": "#a6093d", "本田 未央": "#feb81c", "三船 美優": "#12bfb2", "三村 かな子": "#feb1bb", "夢見 りあむ": "#e59bdc",
            "相葉 夕美": "#f1e991", "赤城 みりあ": "#ffcd00", "浅利 七海": "#009cbc", "安部 菜々": "#ef4b81", "荒木 比奈": "#a0d884", "一ノ瀬 志希": "#a50050", "緒方 智絵里": "#6cc24a", "片桐 早苗": "#dc4404", "上条 春菜": "#5ac2e7", "神谷 奈緒": "#9678d3", "川島 瑞樹": "#485cc7", "神崎 蘭子": "#84329b", "喜多 日菜子": "#fcd757", "木村 夏樹": "#2d2926", "黒埼 ちとせ": "#ef3340", "小関 麗奈": "#9b26b6", "小早川 紗枝": "#e56db1", "西園寺 琴歌": "#e8cdd0", "鷺沢 文香": "#606eb2", "佐久間 まゆ": "#da1984", "佐々木 千枝": "#0072ce", "佐城 雪美": "#171c8f", "椎名 法子": "#f8485e", "塩見 周子": "#dce6ed", "渋谷 凛": "#0f9dde", "島村 卯月": "#f67499", "城ヶ崎 美嘉": "#fe9d1a", "城ヶ崎 莉嘉": "#fedd00", "白菊 ほたる": "#c964cf", "白坂 小梅": "#abcae9", "白雪 千夜": "#efd7e5", "砂塚 あきら": "#7e93a7", "関 裕美": "#ffb3ab", "高垣 楓": "#47d7ac", "鷹富士 茄子": "#5c068c", "多田 李衣菜": "#0177c8", "橘 ありす": "#5c88da", "辻野 あかり": "#e10600", "南条 光": "#e4012b", "新田 美波": "#71c5e8", "二宮 飛鳥": "#60249f", "早坂 美玲": "#c701a0", "速水 奏": "#033087", "久川 凪": "#f8a3bc", "久川 颯": "#7eddd3", "日野 茜": "#fa423a", "藤本 里奈": "#623b2a", "双葉 杏": "#f8a3bc", "北条 加蓮": "#2ad2c9", "堀 裕子": "#eca154", "前川 みく": "#ce0037", "松永 涼": "#221651", "的場 梨沙": "#e01a95", "宮本 フレデリカ": "#a20067", "向井 拓海": "#b0008e", "棟方 愛海": "#c7579a", "村上 巴": "#a5192e", "森久保 乃々": "#9cdbd9", "諸星 きらり": "#ffd100", "八神 マキノ": "#a6a4e0", "大和 亜季": "#28724f", "結城 晴": "#71dad4", "遊佐 こずえ": "#f4a6d7", "依田 芳乃": "#c4bcb7", "龍崎 薫": "#fae053", "脇山 珠美": "#407ec8",
        },
        "アイドルマスターシャイニーカラーズ": {
            "P": "#555555", "Ｐ": "#555555",
            "櫻木 真乃": "#ffbad6", "風野 灯織": "#144384", "八宮 めぐる": "#ffe012",
            "月岡 恋鐘": "#f84cad", "田中 摩美々": "#a846fb", "白瀬 咲耶": "#006047", "三峰 結華": "#3b91c4", "幽谷 霧子": "#d9f2ff",
            "小宮 果穂": "#e5461c", "園田 智代子": "#f93b90", "西城 樹里": "#ffc602", "杜野 凛世": "#89c3eb", "有栖川 夏葉": "#90e667",
            "大崎 甘奈": "#f54275", "大崎 甜花": "#e75bec", "桑山 千雪": "#fafafa",
            "芹沢 あさひ": "#f30100", "黛 冬優子": "#5aff19", "和泉 愛依": "#ff00ff",
            "浅倉 透": "#50d0d0", "樋口 円香": "#be1e3e", "福丸 小糸": "#7967c3", "市川 雛菜": "#ffc639",
            "七草 にちか": "#a6cdb6", "緋田 美琴": "#760f10",
            "斑鳩 ルカ": "#23120c", "七草 はづき": "#8adfff",
        },
        "ブルーアーカイブ": {
            "先生": "#555555",
            "栗村 アイリ": "#4f423e", "鰐渕 アカリ": "#faf1b8", "天雨 アコ": "#a9bfdf", "天童 アリス": "#414a61", "陸八魔 アル": "#f9b5ca",
            "白石 ウタハ": "#e9d0f3",
            "杏山 カズサ": "#2a2839",
            "中務 キリノ": "#fbf8f4",
            "空井 サキ": "#a491ad", "歌住 サクラコ": "#f1ece8",
            "砂狼 シロコ": "#c5c4c8",
            "桐藤 ナギサ": "#e4dad1", "柚鳥 ナツ": "#fdebe4",
            "生塩 ノア": "#e8eff3",
            "伊草 ハルカ": "#534665", "黒舘 ハルナ": "#ccc9d5",
            "槌永 ヒヨリ": "#d5f5e9",
            "愛清 フウカ": "#423856",
            "小鳥遊 ホシノ": "#fbe0e7",
            "小塗 マキ": "#d05a5b", "伊落 マリー": "#fcd9a3",
            "聖園 ミカ": "#ffebf3", "才羽 ミドリ": "#fdd8a3", "近衛 ミナ": "#bfc6c4", "蒼森 ミネ": "#c7ddf7", "月雪 ミヤコ": "#f1f5f9", "霞沢 ミユ": "#787285",
            "浅黄 ムツキ": "#f0eeed",
            "風倉 モエ": "#beadab", "才羽 モモイ": "#fddca6",
            "早瀬 ユウカ": "#615b96", "花岡 ユズ": "#fc7c82",
            "宇沢 レイサ": "#fef3fb",
        },
        "学園アイドルマスター": { # from https://github.com/vertesan/gakumasu-diff/blob/main/CharacterColor.yaml
            "P": "#555555", "Ｐ": "#555555",
            "花海 咲季": "#FF4F64",
            "月村 手毬": "#27B4EB",
            "藤田 ことね": "#FFD203",
            "有村 麻央": "#C45DC8",
            "葛城 リーリヤ": "#D2E3E4",
            "倉本 千奈": "#FE8A22",
            "紫雲 清夏": "#92DE5A",
            "篠澤 広": "#00BED8",
            "姫崎 莉波": "#FD7EC2",
            "十王 星南": "#FFAC28",
            "秦谷 美鈴": "#6EA3FC",
            "花海 佑芽": "#F74C2C",
            "根緒 亜紗里": "#988D83",
            "十王 邦夫": "#988D83",
        },
    }

    _db = {} # same as _db0, but with better saturation and lightness, and uses rgb() format. also last name and name with spaces stripped as keys
    for series in _db0:
        _db[series] = {}
        for name in _db0[series]:
            color1   = _db0[series][name]
            match    = re.match(r"#(..)(..)(..)", re.sub(r"#(.)(.)(.)$", r"\1\1\2\2\3\3", color1))
            assert match, f"Invalid color {color1} (expected: #rrggbb or #rgb)"
            h,l,s    = colorsys.rgb_to_hls(*[int(x, 16) / 256 for x in match.groups()])
            r,g,b    = colorsys.hls_to_rgb(*[h, _lightness, _saturation] if s > 0.01 else [h, l, s])
            color2   = "rgb(%s)" % ",".join([str(int(x * 256)) for x in [r, g, b]])
            lastname = re.search(r"\S*$", name).group(0)
            nospname = re.sub(r"\s", "", name)
            _db[series][lastname] = color2
            _db[series][nospname] = color2

    @classmethod
    def colorHTML(self, html):
        # color character names starting a serifu (e.g. 太郎 in "太郎「こんにちは」")

        # regex: 1 = line beginning, 2 = name, 3 = open paren etc.
        #         (1   )(2  )(3                   )
        regex = r"(^\s*)(.*?)([^\S\r\n]*[(（「『｢])" # ) dummy parent to fix indent

        # Find what series is this html (different serieses may have same name charas with different colors)
        # list of characters found in html (with multiplicity, excluding bad patterns)
        def isCharaName(s): return len(s) > 0 and (not s.startswith("―"))
        charaList = [x[1] for x in re.findall(regex, html, flags=re.MULTILINE) if isCharaName(x[1])]
        # get series with most matching names in charaList
        series = max(self._db.keys(), key = lambda series: len([s for s in charaList if s in self._db[series].keys()]))

        # If at most 1/2 of charaList will get colored, it's likely that series is incorrect
        # We don't have a db for the correct series
        if 0.5 * len(charaList) > len([s for s in charaList if s in self._db[series].keys()]):
            return html

        # Wrap with <span>
        def nosp(s): return s.replace(" ", "")
        def decorHTML(name):
            if not nosp(name) in self._db[series]: return name
            return f"<span class='name name_{nosp(name)}'>{name}</span>"

        # CSS
        style = "<style>\n.name { font-weight: bold }\n" + "\n".join([".name_%s { color: %s; }" % (nosp(name), color) for (name, color) in self._db[series].items() if name in charaList]) + "\n</style>\n"

        # HTML (modified)
        html = re.sub(regex, lambda m: m.group(1) + decorHTML(m.group(2)) + m.group(3), html, flags=re.MULTILINE)

        return style + html


### Misc mini functions

class HttpGet:

    def __init__(self):
        self.times = {}

    def tryDecode(self, data):
        for enc in ["utf-8", "shift-jis", "euc-jp", "cp932"]:
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                pass
        assert False, "Could not decode data"

    def __call__(self, url, fmt:"Literal['str','json','bytes']"="str", headers={}):
        # fmt: "str" (default), "json", "bytes"
        # headers: dict or list of dicts (later element har priority)

        assert fmt in ["str", "json", "bytes"]

        # %-encode chars not allowed in URI, see https://en.wikipedia.org/wiki/Percent-encoding
        regex = r"""[^][!"#$&'()*+,/:;=?@A-Za-z0-9_.~-]+"""
        for m in re.findall(regex, url):
            url = url.replace(m, urllib.parse.quote(m))

        # Rate limiting per domain:port
        loc = urllib.parse.urlparse(url).netloc
        y = max(self.times.setdefault(loc, 0), (x := time.time())) # send request at y
        self.times[loc] = y + 0.5 + min(3, y - x) # exponential wait time, at most 3.5 between requests
        # Sleep if needed
        if y - x > 0.1:
            logging.info(f"HttpGet: requests to the same domain {loc} in a short period, sleeping for {y-x}")
            time.sleep(y - x)

        # Merge headers
        if isinstance(headers, list):
            headers = dict(sum((list(x.items()) for x in headers), []))

        # Actually send request and catch error
        req = urllib.request.Request(url, headers=headers)
        try:
            res = urllib.request.urlopen(req)
        except (urllib.error.HTTPError, urllib.error.URLError, Exception) as e:
            raise e

        if res.status != 200:
            raise Exception(f"http non-200: {res.status}")

        # Decompress, decode, and optionally parse json (and html?)
        data = res.read()
        if "gzip" == ("Content-Encoding" in res.headers and res.headers["Content-Encoding"]):
            data = gzip.decompress(data) # may miss deflate and brotli
        if fmt == "bytes":
            return data
        data = self.tryDecode(data)
        if fmt == "json":
            return json.loads(data)
        elif fmt == "str":
            return data
        else:
            assert False, f"Invalid fmt: {fmt}"

httpGet = HttpGet()

def withFileCache(name, getDefault, expiry=600):
    # note: when cache is expired and getDefault fails, returns old cache
    # expiry is in seconds
    # getDefault should return json-serializable data
    cachedir = CONFIG["cachedir"]
    if not cachedir:
        return getDefault()
    if not re.match(r"^[a-zA-Z0-9-._]*$", name):
        raise Exception("Invalid cache name", name)
    if not os.path.isdir(cachedir):
        os.makedirs(cachedir, exist_ok=True)
    file = cachedir + os.sep + name
    # TODO avoid json encoding/decoding for strings and bytes
    def updateCache():
        value = getDefault()
        with open(file, "w") as f:
            json.dump(value, f, ensure_ascii=False, separators=(",", ":"))
        return value
    def readCache():
        with open(file, "r") as f:
            return json.load(f)
    try:
        if datetime.datetime.now().timestamp() - os.stat(file).st_mtime > expiry:
            try:
                value = updateCache()
                logging.debug("cache updating " + name)
            except:
                value = readCache()
                logging.debug("cache failed updating, using old " + name)
        else:
            value = readCache()
            logging.debug("cache is used " + name)
    except FileNotFoundError:
        value = updateCache()
        logging.debug("cache new item " + name)
    return value

class StringParser:

    def __init__(self, string:str):
        self.string = string
        self.cursor = 0

    def seek(self, sub:str):
        "seek to the next substring sub."
        ret = self.string.find(sub, self.cursor)
        if ret == -1:
            return -1
        self.cursor = ret + len(sub)

    def extract(self, *subs:str, default=None):
        "find substrings from subs and return string between the last two. no seek."
        p1, nt1, p2, nt2 = 0, 0, self.cursor, 0
        for t in subs:
            p1, nt1, p2, nt2 = p2, nt2, self.string.find(t, p2 + nt2), len(t)
            if p2 == -1:
                assert not (default is None), "matching failed and no default given"
                return default
        return self.string[p1+nt1:p2]

def replaceLinks(desc, addTag=False): # replace novel/xxxxx links and user/xxxxx links
    f1 = lambda m: mkurl("user", id=m[1])
    f2 = lambda m: mkurl("novel", id=m[1])
    g1 = lambda m: f'<a href="{mkurl("user", id=m[1])}">user/{m[1]}</a>'
    g2 = lambda m: f'<a href="{mkurl("novel", id=m[1])}">novel/{m[1]}</a>'
    for (regex, rep) in [
        (r"https://www.pixiv.net/users/([0-9]*)",              g1 if addTag else f1),
        (r"https://www.pixiv.net/novel/show.php\?id=([0-9]*)", g2 if addTag else f2),
    ]:
        desc = re.sub(regex, rep, desc)
    return desc

def getRSign(spec):
    "Get canonical rating sign"
    mapping = {
        0: "", "0": "", "": "",
        1: "R ", "1": "R ", "r": "R ", "R": "R ", "R ": "R ",
        2: "G ", "2": "G ", "g": "R ", "G": "R ", "G ": "R ",
    }
    return mapping[spec]

def percentEncode(word):
    return urllib.parse.quote_plus(word, encoding="utf-8")

def mkurl(*args, **kwargs):
    return ("/" if len(args) else "") + "/".join(percentEncode(str(v)) for v in args if v) + ("?" if kwargs else "") + "&".join(f"{k}={percentEncode(str(v))}" for k, v in kwargs.items() if v)

def addMissingCloseTags(html, tags=["b", "s", "u", "strong"]):

    # "aaa<b"  ==>  "aaa"
    m = re.search("<[^>]*$", html)
    if m:
        html = html[:m.start(0)]

    # Count opened counts for each tag in `tags`
    counts = {}
    for m in re.finditer(r"<\s*(/?)\s*(" + "|".join(tags) + r")\s*>", html):
        t = m.group(2)
        if m.group(1) == "/":
            counts[t] = (counts[t] - 1) if t in counts else -1
        else:
            counts[t] = (counts[t] + 1) if t in counts else 1

    # For each tag, if opened count > closed count then add close tags
    for t in counts:
        if counts[t] > 0:
            html += ("</" + t + ">") * counts[t]

    return html

def readCookiestxtAsHTTPCookieHeader(cookiestxt, domain):
    # Read Netscape HTTP Cookie File and return string for urllib request header
    #   urllib.request.Request(url, headers={"Cookie": ...})
    # Only matching domains will be extracted (if domain=="a.com" then www.a.com, .a.com etc will match)

    try:
        with open(cookiestxt) as f:
            results = []

            for line in f:
                # Skip empty or comment lines
                if re.match(r"^\s*$", line) or re.match(r"^# ", line):
                    continue
                fields = line[:-1].split('\t')
                # Each line must have 7 fields and has the specified
                if len(fields) == 7 and (not domain or fields[0].find(domain) != -1):
                    results += [ f"{fields[5]}={fields[6]}" ]

            logging.info(f"Loaded {len(results)} cookies for {domain} from {cookiestxt}")
            return "; ".join(results) # something like "name=val; name=val"

    except OSError as e:
        logging.warning("Could not read cookies.txt; R-18 search results will be omitted!")
        return False

def openInBrowser(url):
    if shutil.which("termux-open-url"):
        subprocess.run(["termux-open-url", url])
    else:
        webbrowser.open(url)

def yesterday():
    return datetime.date.today() - datetime.timedelta(days = 1)

def saveFile(name, text, maxLenBytes=os.pathconf('/', 'PC_NAME_MAX'), prefix="", suffix=""):
    def fsSafeChars(s):
        return re.sub(r'[\\/*<>|]', " ", s).replace('"', "”").replace(":", "：").replace("?", "？")
    def trunc(s, lenBytes, suffix=""):
        # Tuncate s so that (s+suffix).encode("utf-8") has at most lenBytes bytes, and return s+suffix
        # Will not chop in the middle of byte-sequence representing single unicode character
        lenS       = len(s)
        # lenSU      = len(s.encode("utf-8"))
        lenSuffixU = len(suffix.encode("utf-8"))
        i          = lenS
        while len(s[:i].encode("utf-8")) + lenSuffixU > lenBytes:
            i -= 1
        return s[:i] + suffix
    outfile = trunc(fsSafeChars(prefix + name), maxLenBytes, fsSafeChars(suffix))
    savedir = CONFIG["savedir"]
    if not os.path.isdir(savedir): os.makedirs(savedir, exist_ok=True)
    with open(savedir + os.sep + outfile, "w") as f: f.write(text)
    return outfile

def sfind(string:str, tokens:list[str]):
    # find str
    p1, nt1, p2, nt2 = 0, 0, 0, 0
    for t in tokens:
        p1, nt1, p2, nt2 = p2, nt2, string.find(t, p2 + nt2), len(t)
    return string[p1+nt1:p2]

def loadPlugins(plugDir):
    if not os.path.isdir(plugDir):
        raise Exception(f"plugin directory {plugDir} does not exist")
    import glob, importlib.util
    logging.debug(f"Searching plugins in {plugDir}")
    for plugFile in glob.glob("plugin-*.py", root_dir=plugDir):
        logging.debug(f"Loaded plugin from {plugFile}")
        module_name = plugFile[2:-3]
        file_path = os.path.join(plugDir, plugFile)
        # https://docs.python.org/3/library/importlib.html#importing-a-source-file-directly
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)


### test

def test():
    import subprocess as sp, time, urllib.error as ue, urllib.parse as up, urllib.request as ur
    port = 8001
    proc = sp.Popen(["python", "pixiv-novel.py", "-p", str(port), "-c", ""])
    fail = 0

    def test(path):
        # test http status and response length
        # if success, show time taken for request+response
        # if success return 0, if fail return 1
        time.sleep(1)
        t1 = datetime.datetime.now().timestamp()
        try:
            res = ur.urlopen(f"http://localhost:{port}{path}")
        except ue.HTTPError as e:
            print(f"FAIL {path}   ", e)
            return 1
        data = res.read()
        t2 = datetime.datetime.now().timestamp()
        if len(data) < 1000:
            print(f"FAIL {path}   ", "response too short", len(data))
            return 1
        print(f"OK   {path}   {round(t2-t1,3)}s")
        return 0

    try:
        fail += test("/")
        fail += test("/novel?id=15898879")
        fail += test("/search?q=" + up.quote("著作権フリー"))
        fail += test("/user?id=15370995")
    finally:
        proc.kill()
        exit(fail)


### Main

def main():

    global CONFIG

    ## Parse args
    parser = argparse.ArgumentParser(description="Start web server to view pixiv novels.")
    A = parser.add_argument
    D1 = " (default: %(default)s)"
    D2 = " (default: %(default)s; set '' to disable)"
    A("-b", "--bind",     metavar="ADDR", default="0.0.0.0", help="Bind to this address" + D1)
    A("-c", "--cachedir", metavar="DIR", default="_cache",   help="Cache directory" + D2)
    A("-d", "--download", metavar="URL",                     help="Download a novel and exit")
    A("-k", "--cookie",   default="cookies.txt",             help="Path of cookies.txt" + D2)
    A("-l", "--plugdir",  metavar="DIR", default="",         help="Plugin directory" + D2)
    A("-p", "--port",     type=int, default=8080,            help="Port number" + D1)
    A("-s", "--savedir",  metavar="DIR", default="_save",    help="Auto save novels in this directory" + D2)
    A("-v", "--verbose",  action="store_true",               help="Verbose mode")
    A("--browser", action="store_true", help="Open in browser")
    A("--nocolor", action="store_true", help="Disable character name colors")
    A("--noimage", action="store_true", help="Disable image embedding")
    A("--sslcert", help="HTTPS cert file")
    A("--sslkey",  help="HTTPS key file")
    A("--test",    action="store_true")
    # parser.add_argument("--nor18", action="store_true", help="Disable R18.")
    args = parser.parse_args()

    # Save some options on global
    CONFIG["cachedir"] = args.cachedir
    CONFIG["nocolor"]  = args.nocolor
    CONFIG["savedir"]  = args.savedir
    CONFIG["noimage"]  = args.noimage

    logging.basicConfig(format='%(asctime)s:%(levelname)s:%(name)s:%(thread)d:%(message)s', level=logging.DEBUG if args.verbose else logging.ERROR)

    if args.plugdir:
        loadPlugins(args.plugdir)

    # Readme
    # - Check out: cool reader (android app)
    # - cookies.txt
    # - how to visit server

    # Download novel and exit.
    if args.download:
        novelID = re.match(r"[0-9]*", args.download).group()
        if not novelID:
            logging.error("Invalid url")
        else:
            f = Fetch(novelID)
            outfile = f.save()
            print("Written to " + outfile, flush=True)
        exit()

    # Try read cookies.txt
    # To obtain cookies.txt, use https://addons.mozilla.org/ja/firefox/addon/cookies-txt/ or https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid or type document.cookie in devtool
    if args.cookie:
        Resources.Pixiv.cookie = readCookiestxtAsHTTPCookieHeader(args.cookie, "pixiv.net")

    # Test code
    if args.test:
        test()
        quit()

    # Check HTTPS support
    if args.sslcert and args.sslkey:
        serverHttps = True
        serverCert  = args.sslcert
        serverKey   = args.sslkey
    elif args.sslcert or args.sslkey:
        raise Exception("Specify both --sslcert and --sslkey for HTTPS support.")
    else:
        serverHttps = serverCert = serverKey = None

    # Run server
    serverHost = args.bind
    serverPort = args.port

    serverThread = threading.Thread(
        None,
        target=run_threaded_https_server,
        args=(MyRequestHandler, serverHost, serverPort, serverHttps, serverCert, serverKey),
        daemon=True)
    serverThread.start()

    serverUrl = f"http{'s' if serverHttps else ''}://{serverHost}:{serverPort}"
    print(f"Serving at {serverUrl}", flush=True)

    # Open in browser
    if args.browser:
        openInBrowser(serverUrl)

    try:
        serverThread.join()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
