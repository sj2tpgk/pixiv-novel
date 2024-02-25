<!--
cat readme.md | awk '/@RUN/{while(substr($0,6)|getline out){print out}next}{print}'
md2html readme.md > readme.html
-->

# Lightweight pixiv novel viewer

Lightweight frontend for pixiv novels.

Features: search/view novels, view rankings, generates simple html, no javascript, autosave, optional login with `cookies.txt`, written in python, no 3rd party dependency, also works on android+termux.

### Usage
``` sh
wget 'https://codeberg.org/sj2tpgk/pixiv-novel/raw/branch/main/pixiv-novel.py'
python pixiv-novel.py --browser
# Automatically opens daily ranking in browser (0.0.0.0:8080 by default)
```

### Instances

* Test instance:
  [https://noouan.f5.si/](https://noouan.f5.si/)
  [(onion)](http://4xwgxkd27mor6xds4uh4qh3vwirdxh33lwdj2fecx2zdcmtcr7ua.b32.i2p)
  [(garlic)](http://bhwtqh42kcbzt3idsmnaklnbgeq2yhidnlxsndglrenz2etjc7yqcvqd.onion)

### Screenshots
<img width="450" src="images/novel.png">
<img width="450" src="images/search.png">
<img width="450" src="images/top.png">

### Cookies
To search/view age-restricted contents, put `cookies.txt` in current directory:
1. Login to pixiv.
2. Export `cookies.txt` using this [Chrome addon](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid) or [Firefox addon](https://addons.mozilla.org/ja/firefox/addon/cookies-txt/).
3. Check `cookies.txt` is in the current directory and run script:

    ```sh
    $ grep -i pixiv cookies.txt
    www.pixiv.net   FALSE   /       TRUE    ...
    ...
    $ python pixiv-novel.py
    ```

When `HTTP Error` happens, try re-exporting your `cookies.txt`.

<!-- or use document.cookie in devtool -->

### Options
```
usage: pixiv-novel.py [-h] [-a] [-b ADDRESS] [-C] [-c CACHEDIR] [-d URL]
                      [-p PORT] [-v] [--browser] [--sslcert SSLCERT]
                      [--sslkey SSLKEY] [--test]

Start web server to view pixiv novels. Load cookies.txt if found in current
dir.

options:
  -h, --help            show this help message and exit
  -a, --autosave        Enable autosave; save visited novels as files.
  -b ADDRESS, --bind ADDRESS
                        Bind to this address. (default: 0.0.0.0)
  -C, --nocolor         Disable character name colors.
  -c CACHEDIR, --cachedir CACHEDIR
                        Directory to store cache (NONE to disable).
  -d URL, --download URL
                        Download a novel and exit.
  -p PORT, --port PORT  Port number. (default: 8080)
  -v, --verbose         Verbose mode.
  --browser             Open in browser.
  --sslcert SSLCERT     HTTPS cert file.
  --sslkey SSLKEY       HTTPS key file.
  --test
```

### Character name colorizer
This script has a feature to colorize each character name with different colors in SS-style novels (e.g. "太郎" in "太郎「こんにちは」").

It needs a database of character names & colors.
See the source code for database definitions.

