#!/usr/bin/env python

from http.server import BaseHTTPRequestHandler, HTTPServer
from html.parser import HTMLParser
import argparse
import colorsys
import datetime
import json
import os
import random
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
import webbrowser

# base
# TODO no-r mode
# TODO help page on how to get cookies.txt
# TODO html extractor: get innerHTML? (do ranking descriptions contain html tags??)
# TODO other websites? (and rename to ja-novels.py)
# TODO chara name db in separate files (one file per each series, and embed on build)
# TODO url like /search/abc/6?compact=... (for better history integration)

# as a cli util
# TODO json api (like &json=1, for cli, also for test automation)


### Configuration

cookie = None  # Cookie string
save   = False # Save visited novels?
color  = False # colorize character names?

def hasCookie(): return bool(cookie)

emoji = { "love": "💙", "search": "🔍" }


### Server

class MyServer(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return # supress logs

    def do_GET(self):

        def sendHTML(html):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            try:
                self.wfile.write(bytes(html, "utf-8"))
            except BrokenPipeError:
                # print("BrokenPipeError")
                return

        params = urllib.parse.parse_qs(self.path[2:])
        # print(self.requestline, params)

        def param(name, default=None):
            if not name in params:
                return default
            else:
                return params[name][0]

        def getHTML():
            cmd = param("cmd", "ranking")
            if cmd == "fetch":
                if not (novelID := param("id")):
                    return "missing id"
                else:
                    f = Fetch(novelID)
                    if save:
                        f.save()
                    return f.html()
            elif cmd in ["search", "searchuser", "ranking"]:
                if cmd == "search":
                    s = Search(param("q", ""), param("bookmarks", 0), param("page", "1"), param("npages", 1))
                elif cmd == "searchuser":
                    s = SearchUser(param("q", ""), param("bookmarks", 0))
                elif cmd == "ranking":
                    s = SearchRanking(param("mode", "daily"), param("date", ""))
                return s.html(param("compact", 1))
            else:
                return "unknown cmd"

        if "favicon" in self.requestline:
            sendHTML("")
        else:
            # sendHTML(getHTML())
            try:
                sendHTML(getHTML())
            except Exception as e:
                print ("Error occured\n" + str(e))
                return "Error occured<br>" + str(e)


### Search

def searchEntry(title, tags, id, description, xRestrict, bookmarkCount, textCount):
    # Abstracts (1) response json format and (2) difference between websites
    return {
            "title"         : title,
            "tags"          : tags,
            "id"            : id,
            "description"   : description,
            "xRestrict"     : xRestrict,
            "bookmarkCount" : bookmarkCount,
            "textCount"     : textCount,
            }

def html_searchBar(simple=True, query="", compact=False, bookmarks=0, npages=1):
    html = f"""<form style="text-align: right; line-height: 1.5">
<input type="text" name="q" placeholder="検索" value="{query}">
<input type="submit" value="{emoji['search']}">
<input type="hidden" name="cmd" value="search">
<input type="hidden" name="compact" value="{1 if compact else ''}">
"""
    if not simple:
        html += f"""<br>
<select name="npages">
<option value="1"{" selected" if npages == 1 else ""}>1ページずつ
<option value="2"{" selected" if npages == 2 else ""}>2ページずつ
<option value="3"{" selected" if npages == 3 else ""}>3ページずつ
</select>
{emoji['love']}:<input type="text" name="bookmarks" value="{bookmarks}" size="3">
"""
    html += "</form>"
    return html

class Search():

    # Usage: print(Search("abc",10,1,1).html())

    def __init__(self, query, bookmarkCount, page, npages):
        self._novels = []

        self._query = query
        self._bookmarkCount = int(bookmarkCount)
        self._page = int(page)
        self._npages = int(npages)

        self._doSearch()

    def _doSearch(self):
        dataList = self._getDataList()
        self._novels = [
                searchEntry(x["title"], x["tags"], x["id"], x["description"], x["xRestrict"], x["bookmarkCount"], x["textCount"])
                for x in dataList
                if int(x["bookmarkCount"]) >= self._bookmarkCount
                ]

    def _getDataList(self):
        self._wordEscaped = percentEncode(self._query).replace("+", "%20")
        dataList = []
        for i in range(self._npages):
            url1 = f"{self._wordEscaped}?word={self._wordEscaped}&order=date_d&mode=all&p={i+self._page}&s_mode=s_tag&lang=ja"
            url = f"https://www.pixiv.net/ajax/search/novels/{url1}"
            resJson = myRequest(url, toJson=True)
            dataList += resJson["body"]["novel"]["data"]
        return dataList

    def html(self, compact):
        compact = compact == "1"

        # common css
        css = """body { max-width: 750px; margin: 1em auto; padding: 0 .5em; }
#main { margin: 1em 0 }
li p { margin: 1.5em 0 }
td:not(:nth-child(4)) { text-align: center; padding: 0 .35em }
td:nth-child(4)       { padding-left: 2em }"""

        # novels
        novels = "<table>" if compact else "<ul>"
        for x in self._novels:
            href = f"/?cmd=fetch&id={x['id']}"
            if compact:
                novels += f"<tr><td><a href=\"{href}\">{x['id']}</a></td><td>{getRSign(x['xRestrict'])}</td><td>{x['bookmarkCount']}</td><td>{x['title']}</td></tr>\n"
            else:
                desc = "<br>".join(replaceLinks(x["description"]).split("<br />")[0:5])
                desc = addMissingCloseTags(desc, tags=["b", "s", "u", "strong"])
                tags = ", ".join([f"<a href=\"/?cmd=search&q={percentEncode(t)}\">{t}</a>" for t in x["tags"]])
                novels += f"<li>{x['title']} ({x['textCount']}字) <a href=\"{href}\">[{x['id']}]</a><p>{desc}</p>{emoji['love']} {x['bookmarkCount']}<br>{tags}</li><hr>\n"
        novels += "</table>" if compact else "</ul>"

        # final html
        return f"""<!DOCTYPE html>
<html lang="ja">
<head>
{self._html_head()}
<meta http-equiv="content-type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
{css}
</style>
</head>
<body>
{self._html_header(compact)}
{self._html_nav(compact)}
<div id="main">
{novels}
</div>
{self._html_nav(compact)}
</body>
</html>"""

    def _html_head(self):
        return f"<title>Search {self._query}{(f' ({self._page})' if self._page > 1 else '')}</title>"

    def _html_header(self, compact):
        return f"""<h1>Search {self._query}{(f' ({self._page})' if self._page > 1 else '')}</h1>
{html_searchBar(simple=False, query=self._query, compact=compact, bookmarks=self._bookmarkCount, npages=self._npages)}
<hr>"""

    def _html_nav(self, compact):
        # navigation links (on both top and bottom of page)
        paramCompact    = "&compact=1" if     compact else ""
        paramCompactNeg = "&compact=1" if not compact else ""
        commonParams = f"?cmd=search&q={self._wordEscaped}&npages={self._npages}&bookmarks={self._bookmarkCount}"
        hrefPrev = f"/{commonParams}&page={max(1,self._page-self._npages)}{paramCompact}"
        hrefNext = f"/{commonParams}&page={self._page+self._npages}{paramCompact}"
        hrefToggle = f"/{commonParams}&page={self._page}{paramCompactNeg}"
        return f"""<div id="nav" style="display: flex">
<span style="flex: 1">
<a href="{hrefToggle}">{compact and "詳細表示" or "コンパクト表示"}</a>
</span>
<span style="flex: 1"></span>
<span style="flex: 1; text-align: right">
<a href='{hrefPrev}'>前へ</a>
<a href='{hrefNext}'>次へ</a>
</span>
</div>"""

class SearchUser(Search):

    def __init__(self, userID, bookmarkCount):
        self._novels = []

        self._userID = userID
        self._bookmarkCount = int(bookmarkCount)

        self._doSearch()

    def _getDataList(self):
        dataList = []

        # First, response includes all novelIDs of user
        url1 = f"https://www.pixiv.net/ajax/user/{self._userID}/profile/all?lang=ja"
        json1 = myRequest(url1, toJson=True)
        novelIDs = list(json1["body"]["novels"].keys())

        # Next, get data for each novel (100 novels at once)
        dataList = []
        n = 100
        for ids in [novelIDs[n*i:n*(i+1)] for i in range(1+int(len(novelIDs)/n))]:
            idsParams = "&".join([f"ids[]={x}" for x in ids])
            url2 = f"https://www.pixiv.net/ajax/user/{self._userID}/profile/novels?{idsParams}"
            json2 = myRequest(url2, toJson=True)
            dataList += list(json2["body"]["works"].values())

        return dataList

    def _html_head(self):
        return f"<title>Search {self._userID}</title>"

    def _html_header(self, compact):
        return f"""<h1>Search {self._userID}</h1>
{html_searchBar(simple=True, query="", compact=compact)}
<hr>"""

    def _html_nav(self, compact):
        hrefToggle = f"/?cmd=searchuser&q={self._userID}{'&compact=1' if not compact else ''}"
        return f"<a href='{hrefToggle}'>{compact and '詳細表示' or 'コンパクト表示'}</a>"

class SearchRanking(Search):

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

    def __init__(self, mode, date):
        self._novels = []

        self._mode = mode

        # set self._date to a date object (at most yesterday)
        if re.match(r"\d\d\d\d-\d\d-\d\d", date):
            d = datetime.date.fromisoformat(date)
            y = yesterday()
            self._date = d if d <= y else y
        else:
            self._date = yesterday()

        self._doSearch()

    def _doSearch(self):
        dataList = self._getDataList()
        self._novels = [
                searchEntry(x["title"], x["tags"], x["id"], x["description"], x["xRestrict"], x["bookmarkCount"], x["textCount"])
                for x in dataList
                ]

    def _getDataList(self):
        url = f"https://www.pixiv.net/novel/ranking.php?mode={self._mode}&date={self._date.isoformat().replace('-', '')}"
        # return self._getDataListFromHTML("".join(open("../r_daily","r").readlines()))
        dataList = []
        for page in [1, 2]:
            res = myRequest(url + ("&page=2" if page == 2 else ""))
            dataList += self._getDataListFromHTML(res)
        return dataList

    def _getDataListFromHTML(self, html):
        # searchEntry(title, tags, id, description, xRestrict, bookmarkCount, textCount):
        data = []
        current = None
        def done():
            nonlocal current, data
            if current:
                data += [searchEntry(**current)]
            current = {}
        def setp(prop, val):
            current[prop] = val
        def onStart(match, attr):
            if match("._ranking-item"):
                done()
                setp("xRestrict", "r18" in self._mode)
                setp("description", "") # some novels don't have description
            elif match(".cover"):
                setp("title", re.sub(r"/.*", "", attr("alt")))
                setp("tags",  attr("data-tags").split())
                setp("id",    attr("data-id"))
        def onData(match, data):
            if match(".bookmark-count"):
                setp("bookmarkCount", re.sub(r"[^\d]", "", data))
            elif match(".chars"):
                setp("textCount", re.sub(r"[^\d]", "", data))
            elif match(".novel-caption"):
                setp("description", data)

        MyHTMLParser(onStart, onData).feed(html)
        done()
        # print(json.dumps([[x["title"]] for x in data], indent=2, sort_keys=True, ensure_ascii=False))
        return data

    def _html_head(self):
        return f"<title>{self._modeNames[self._mode]} ランキング {self._date}</title>"

    def _html_header(self, compact):
        # links for other rankings
        hrefBase = f"/?cmd=ranking{'&compact=1' if compact else ''}&date={self._date}"
        modeLinks1 = "\n".join([f"""<a href="{hrefBase}&mode={mode}"{ ' class="ranking-selected"' if mode == self._mode else ""}>{self._modeNames[mode]}</a>""" for mode in self._modeNames.keys() if not "r18" in mode])
        if hasCookie():
            modeLinks2 = "<span>R-18:</span>"
            modeLinks2 += "\n".join([f"""<a href="{hrefBase}&mode={mode}"{ ' class="ranking-selected"' if mode == self._mode else ""}>{self._modeNames[mode].replace(" R-18", "")}</a>""" for mode in self._modeNames.keys() if "r18" in mode])
        else:
            modeLinks2 = "R-18 ランキングを見るには cookies.txt が必要です。"
        modeLinks = """<style>
#ranking-modes { margin: .8em 0; font-size: small; line-height: 1.8 }
#ranking-modes a { margin-right: 1.4em }
#ranking-modes span { margin-right: 1.0em }
.ranking-selected { font-weight: bold }
</style>""" + f"""
<p id="ranking-modes">
{modeLinks1}
<br>
{modeLinks2}
</p>"""

        # construct html
        return f"""<h1>{self._modeNames[self._mode]} ランキング {self._date}</h1>
{html_searchBar(simple=True, query="", compact=compact)}
{modeLinks}
<hr>
<form style="text-align: center; margin: .5em 0">
<label for="date">日付:</label>
<input type="date" id="date" name="date" value="{self._date}" max="{yesterday()}">
<input type="submit" value="{emoji['search']}">
<input type="hidden" name="cmd" value="ranking">
<input type="hidden" name="mode" value="{self._mode}">
<input type="hidden" name="compact" value="{1 if compact else ''}">
</form>"""

    def _html_nav(self, compact):
        hrefToggle = f"/?cmd=ranking&q={self._mode}{'&compact=1' if not compact else ''}&date={self._date}"
        return f"<a href='{hrefToggle}'>{compact and '詳細表示' or 'コンパクト表示'}</a>"

class MyHTMLParser(HTMLParser):
    # Usage: MyHTMLParser(onStart, onData).feed(html)
    # On each handle_starttag, onStart(match, attr) is called, where match(query) checks if the tag matches the CSS query, and attr(attrName) is like getAttribute(attrName)
    # On each handle_data, onData(match, data) is called, where match(query) is the same above, and data is the same as in handle_data
    def __init__(self, onStart, onData):
        super().__init__()
        self._stack = []
        self._onStart = onStart
        self._onData = onData
    def _attr(self, attr):
        if len(self._stack) == 0: return
        for (k, v) in self._stack[-1]["attrs"]:
            if k == attr:
                return v
    def _match(self, query):
        if not re.match(r"^\.[^\s.]*$", query):
            print("Query must be like .CLASS")
            return
        return re.sub(r"\.", "", query) in (self._attr("class") or "").split()
    def handle_starttag(self, tag, attrs):
        self._stack.append({ "tag": tag, "attrs": attrs })
        self._onStart(self._match, self._attr)
        if tag in ["img"]:
            self._stack.pop()
    def handle_endtag(self, tag):
        self._stack.pop()
    def handle_data(self, data):
        self._onData(self._match, data)


### Fetch

class Fetch():

    def __init__(self, novelID):
        self._novelID = novelID
        self._data = self._getData()
        self._html = None

    def _getData(self):
        url = "https://www.pixiv.net/novel/show.php?id=%s" % self._novelID
        html = myRequest(url)
        return self._extractData(html)

    def html(self):
        if self._html: return self._html

        ## Construct html

        data = self._getData()

        o_css = """body { max-width: 700px; margin: 1em auto; padding: 0 .5em; }
@media screen and (max-aspect-ratio: .75) and (max-width: 13cm) { /* Mobile */
    body { max-width: 100%; margin: 0.5em 0.5em }
}
#novel { line-height: 1.9; border-bottom: solid #888 1px; margin-bottom: 2em; padding-bottom: 3em; }
#data { display: none }"""

        o_rSign = getRSign(data["xRestrict"])
        o_title = data["title"]
        o_description = replaceLinks(data["description"])
        o_content = data["content"]
        for (regex, replace) in [
                (r"$", "<br>"),
                (r"\[newpage\]", "<hr>\n"),
                (r"\[chapter:(.*?)\]", "<h2>\\1</h2>\n"),
                (r"\[\[rb:(.*?)(>|&gt;)(.*?)\]\]", "<ruby>\\1<rt>\\3</rt></ruby>"),
                ]:
            o_content = re.sub(regex, replace, o_content, flags=re.MULTILINE)

        # uploadedimage
        def getImageTag(novelImageId):
            url = data["textEmbeddedImages"][novelImageId]["urls"]["original"]
            return f"""<figure>
<a href="{url}">
<img src=\"{url}\" alt=\"[uploadedimage:{novelImageId}\" style=\"width: 100%\">
</a>
</figure>"""
        o_content = re.sub(r"\[uploadedimage:([0-9]*)(.*?)\]", lambda m: getImageTag(m.group(1)), o_content)

        # pixivimage (not simple to retrieve images)
        o_content = re.sub(r"\[pixivimage:([0-9]*)(.*?)\]", "<a href=\"https://www.pixiv.net/artworks/\\1\">画像 \\1\\2</a>", o_content)

        # colorize character names
        if color:
            o_content = CharaColor.colorHTML(o_content)

        # embed json
        # ダブルクオートを残し、全体をシングルクオートで囲み、ensure_ascii=False を使うと、圧縮できる
        # とはいえjsonなしよりはかなり大きい (47k vs 114k vs 171k)
        o_json = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
        for (fromStr, toStr) in [
                ("'", "&#39;"), # ("\"", "&quot;"), ("<", "&lt;"), (">", "&gt;")
                ]:
            o_json = o_json.replace(fromStr, toStr)

        o_tags = ",\n".join(map(lambda y: f"<a href='/?cmd=search&q={percentEncode(y)}'>{y}</a>", [x["tag"] for x in data["tags"]["tags"]]))
        o_info = f"""<p>
タグ:
{o_tags}
</p>
<p>
<a href="https://www.pixiv.net/novel/show.php?id={data["id"]}">Pixivで開く</a>
ID:{data["id"]}
U:<a href="/?cmd=searchuser&q={data["userId"]}">{data["userId"]}</a>
B:{data["bookmarkCount"]}
D:{data["createDate"][:10]}
</p>"""

        self._html = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<title>{o_rSign}{o_title}</title>
<meta http-equiv="content-type" content="text/html; charset=utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<!--<link rel="stylesheet" href="_style.css">-->
<style>
{o_css}
</style>
</head>
<body>
<h1>{o_title}</h1>
<div id="novel">
{o_content}
</div>
<div id="info">
<p>
{o_description}
</p>
{o_info}
</div>
<div id="data" data-novels='{o_json}'></div>
</body>
</html>"""

        return self._html

    def save(self): # Save to file (will return filename)
        def trunc(s, lenBytes, suffix=""):
            # Tuncate s so that (s+suffix).encode("utf-8") has at most lenBytes bytes, and return s+suffix
            # Will not chop in the middle of byte-sequence representing single unicode character
            lenS       = len(s)
            lenSU      = len(s.encode("utf-8"))
            lenSuffixU = len(suffix.encode("utf-8"))
            i          = lenS
            while len(s[:i].encode("utf-8")) + lenSuffixU > lenBytes:
                i -= 1
            return s[:i] + suffix
        title = self._data["title"].replace("/", " ")
        outPrefix = f"{getRSign(self._data['xRestrict'])}"
        outSuffix = f" - pixiv - {self._data['id']}.html"
        outfile = trunc(outPrefix + title, os.pathconf('/', 'PC_NAME_MAX'), outSuffix)
        open(outfile, "w").write(self.html())
        return outfile

    def _extractData(self, html): # parse show.php and get json inside meta[name=preload-data]
        # Extract json string
        s = None
        def onStart(match, attr):
            nonlocal s
            if attr("name") == "preload-data":
                s = attr("content")
        MyHTMLParser(onStart, lambda match, data: 0).feed(html)

        # Extract part of json
        json1 = json.loads(s)
        return json1["novel"][list(json1["novel"].keys())[0]]


### Character name colorizer

class CharaColor:
    _lightness = 0.52
    _saturation = 0.7

    _db0 = { # _db0[series][characterName] = color (format: "#xxxxxx" or "#xxx")
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
                " アナスタシア": "#b1c9e8", "及川 雫": "#f4f9ff", "大槻 唯": "#f6be00", "乙倉 悠貴": "#e3bec3", "喜多見 柚": "#f0ec74", "桐生 つかさ": "#ab4ec6", "小日向 美穂": "#db3fb1", "高森 藍子": "#ceea80", "道明寺 歌鈴": "#d22730", " ナターリア": "#f5633a", "難波 笑美": "#e13c30", "浜口 あやめ": "#450099", "姫川 友紀": "#ee8b00", "藤原 肇": "#9595d2", "星輝 子": "#a6093d", "本田 未央": "#feb81c", "三船 美優": "#12bfb2", "三村 かな子": "#feb1bb", "夢見 りあむ": "#e59bdc",
                "相葉 夕美": "#f1e991", "赤城 みりあ": "#ffcd00", "浅利 七海": "#009cbc", "安部 菜々": "#ef4b81", "荒木 比奈": "#a0d884", "一ノ瀬 志希": "#a50050", "緒方 智絵里": "#6cc24a", "片桐 早苗": "#dc4404", "上条 春菜": "#5ac2e7", "神谷 奈緒": "#9678d3", "川島 瑞樹": "#485cc7", "神崎 蘭子": "#84329b", "喜多 日菜子": "#fcd757", "木村 夏樹": "#2d2926", "黒埼 ちとせ": "#ef3340", "小関 麗奈": "#9b26b6", "小早川 紗枝": "#e56db1", "西園寺 琴歌": "#e8cdd0", "鷺沢 文香": "#606eb2", "佐久間 まゆ": "#da1984", "佐々木 千枝": "#0072ce", "佐城 雪美": "#171c8f", "椎名 法子": "#f8485e", "塩見 周子": "#dce6ed", "渋谷 凛": "#0f9dde", "島村 卯月": "#f67499", "城ヶ崎 美嘉": "#fe9d1a", "城ヶ崎 莉嘉": "#fedd00", "白菊 ほたる": "#c964cf", "白坂 小梅": "#abcae9", "白雪 千夜": "#efd7e5", "砂塚 あきら": "#7e93a7", "関 裕美": "#ffb3ab", "高垣 楓": "#47d7ac", "鷹富士 茄子": "#5c068c", "多田 李衣菜": "#0177c8", "橘あ りす": "#5c88da", "辻野 あかり": "#e10600", "南条 光": "#e4012b", "新田 美波": "#71c5e8", "二宮 飛鳥": "#60249f", "早坂 美玲": "#c701a0", "速水 奏": "#033087", "久川 凪": "#f8a3bc", "久川 颯": "#7eddd3", "日野 茜": "#fa423a", "藤本 里奈": "#623b2a", "双葉 杏": "#f8a3bc", "北条 加蓮": "#2ad2c9", "堀 裕子": "#eca154", "前川 みく": "#ce0037", "松永 涼": "#221651", "的場 梨沙": "#e01a95", "宮本 フレデリカ": "#a20067", "向井 拓海": "#b0008e", "棟方 愛海": "#c7579a", "村上 巴": "#a5192e", "森久保 乃々": "#9cdbd9", "諸星 きらり": "#ffd100", "八神 マキノ": "#a6a4e0", "大和 亜季": "#28724f", "結城 晴": "#71dad4", "遊佐 こずえ": "#f4a6d7", "依田 芳乃": "#c4bcb7", "龍崎 薫": "#fae053", "脇山 珠美": "#407ec8",
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
                }
            }

    _db = {} # same as _db0, but with better saturation and lightness, and uses rgb() format. also last name and name with spaces stripped as keys
    for series in _db0:
        _db[series] = {}
        for name in _db0[series]:
            color1   = _db0[series][name]
            match    = re.match(r"#(..)(..)(..)", re.sub(r"#(.)(.)(.)$", r"\1\1\2\2\3\3", color1))
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
        regex = r"(^\s*)(.*?)([^\S\r\n]*[(（「『｢])"

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

def myRequest(url, toJson=False):
    # %-encode non-ascii chars
    regex = r'[^\x00-\x7F]'
    for m in re.findall(regex, url):
        url = url.replace(m, urllib.parse.quote_plus(m, encoding="utf-8"))

    headers = { # 404 without these
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/69.0.3497.100",
            "Host": "www.pixiv.net",
            "Accept": "application/json",
            "Accept-Language": "ja,en-US;q=0.7,en;q=0.3",
            "Referer": "https://www.pixiv.net/",
            "x-user-id": str(random.randrange(0, 100000000)),
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "TE": "trailers",
            }

    global cookie
    if cookie:
        headers["Cookie"] = cookie

    import urllib.error
    try:
        req = urllib.request.Request(url, headers=headers)
        out = urllib.request.urlopen(req).read().decode("utf-8")
        return json.loads(out) if toJson else out
    except urllib.error.HTTPError as e:
        print("Error when downloading from Pixiv, possibly cookies.txt is outdated.")
        print("HTTPError: ", e)
    except urllib.error.URLError as e:
        print("URLError: ", e)
    except Exception as e:
        print(e)

def replaceLinks(desc): # replace novel/xxxxx links and user/xxxxx links
    for (regex, rep) in [
            (r"https://www.pixiv.net/users/([0-9]*)", "/?cmd=searchuser&q=\\1"),
            (r"https://www.pixiv.net/novel/show.php\?id=([0-9]*)", "/?cmd=fetch&id=\\1"),
            ]:
        desc = re.sub(regex, rep, desc)
    return desc

def getRSign(xRestrict):
    return ["", "R ", "G "][int(xRestrict)]

def percentEncode(word):
    return urllib.parse.quote_plus(word, encoding="utf-8")

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

def readCookiestxtAsCookieHeader():
    # Read Netscape HTTP Cookie File and return string for urllib request header
    #   urllib.request.Request(url, headers={"Cookie": ...})

    cookiestxt = "cookies.txt"

    try:
        with open(cookiestxt) as f:
            results = []

            for line in f:
                # Skip empty or comment lines
                if re.match(r"^\s*$", line) or re.match(r"^# ", line):
                    continue
                fields = line[:-1].split('\t')
                # Each line must have 7 fields and domain name must be pixiv related
                if len(fields) == 7 and fields[0].find("pixiv.net") != -1:
                    results += [ f"{fields[5]}={fields[6]}" ]

            # Output will be like "name=val; name=val"
            return "; ".join(results)

    except OSError as e:
        print("Could not read cookies.txt; R-18 search results will be omitted!")
        return False

def openInBrowser(url):
    if shutil.which("termux-open-url"):
        subprocess.run(["termux-open-url", url])
    else:
        webbrowser.open(url)

def yesterday():
    return datetime.date.today() - datetime.timedelta(days = 1)


### Main

if __name__ == "__main__":

    ## Parse args
    parser = argparse.ArgumentParser(description="Start web server to view pixiv novels. Load cookies.txt if found in current dir.")
    parser.add_argument("-a", "--autosave", action="store_true", help="Enable autosave; save visited novels as files.")
    parser.add_argument("-B", "--nobrowser", action="store_true", help="Don't open browser.")
    parser.add_argument("-C", "--nocolor", action="store_true", help="Disable character name colors.")
    parser.add_argument("-d", "--download", type=str, metavar="URL", help="Download a novel and exit.")
    parser.add_argument("-p", "--port", type=int, default=8080, help="Port number. (default: 8080)")
    # parser.add_argument("-R", "--nor18", action="store_true", help="Disable R18.")

    # Save some options on global
    args = parser.parse_args()
    save = args.autosave
    color = not args.nocolor

    # Readme
    # - Check out: cool reader (android app)
    # - cookies.txt
    # - how to visit server

    # Download novel and exit.
    if args.download:
        novelID = re.match(r"[0-9]*", args.download).group()
        if not novelID:
            print("Invalid url")
        else:
            f = Fetch(novelID)
            outfile = f.save()
            print(outfile)
        exit()

    # Try read cookies.txt
    # To obtain cookies.txt, use https://addons.mozilla.org/ja/firefox/addon/cookies-txt/ or https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid or type document.cookie in devtool
    cookie = readCookiestxtAsCookieHeader()

    # Run server
    hostName = "0.0.0.0" # Also accessible from other computers
    serverPort = args.port
    webServer = HTTPServer((hostName, serverPort), MyServer)
    serverUrl = "http://%s:%s" % (hostName, serverPort)
    print("Server at %s" % serverUrl)

    # Open in browser
    if not args.nobrowser:
        openInBrowser(serverUrl)

    try:
        webServer.serve_forever()
    except KeyboardInterrupt:
        pass

    webServer.server_close()

