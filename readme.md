<!-- automatically generated file; do not edit -->
# Alternative frontend for pixiv novels

### Usage
``` sh
curl 'https://raw.githubusercontent.com/sj2tpgk/pixiv-novel/main/pixiv-novel.py' > pixiv-novel.py
python pixiv-novel.py
# Automatically opens daily ranking in browser
```

### Screenshots
<img width="450" src="images/search.png">
<img width="450" src="images/top.png">
<img width="450" src="images/novel.png">

### Cookies
To search age-restricted contents, put `cookies.txt` in current directory:
1. Login to pixiv.
2. Export `cookies.txt` using this [Chrome addon](https://chrome.google.com/webstore/detail/get-cookiestxt/bgaddhkoddajcdgocldbbfleckgcbcid) or [Firefox addon](https://addons.mozilla.org/ja/firefox/addon/cookies-txt/).
3. Check `cookies.txt` is in the current directory and run script:

    ```sh
    $ grep -i pixiv cookies.txt
    www.pixiv.net   FALSE   /       TRUE    ...
    ...
    $ python pixiv-novel.py
    ```

<!-- or use document.cookie in devtool -->

### Options
```
usage: pixiv-novel.py [-h] [-a] [-B] [-C] [-d URL] [-p PORT]

Start web server to view pixiv novels. Load cookies.txt if found in current
dir.

options:
  -h, --help            show this help message and exit
  -a, --autosave        Enable autosave; save visited novels as files.
  -B, --nobrowser       Don't open browser.
  -C, --nocolor         Disable character name colors.
  -d URL, --download URL
                        Download a novel and exit.
  -p PORT, --port PORT  Port number. (default: 8080)
```

