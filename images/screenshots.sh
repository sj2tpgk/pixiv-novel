#!/bin/sh

cd "$(cd -- "$(dirname -- "$0")"; pwd)" || exit 1

screenshot() {
    echo "Screenshot out=$1 url=$2"
    firefox -P ss --headless --window-size 1024,768 --screenshot "$2" 2>/dev/null
    mv screenshot.png "$1"
}

port=8085
../pixiv-novel.py -p $port -c NONE &
pid=$!
sleep 1
screenshot top.png    "http://localhost:$port"
screenshot novel.png  "http://localhost:$port/novel?id=15898879"
screenshot search.png "http://localhost:$port/search?q=著作権フリー"
kill $pid

