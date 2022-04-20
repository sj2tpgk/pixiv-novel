#/usr/bin/sh

screenshot() {
    out=$1
    url=$2
    firefox -P ss --headless --window-size 1024,768 --screenshot "$url" 2>/dev/null
    mv screenshot.png "$out"
}


{
    echo '<!-- automatically generated file; do not edit -->'
    cat readme.def.md | perl -ne 'if(/^\@RUN (.*)/){print `$1`}else{print}'
} > readme.md

# generate html for local preview
md2html readme.md > readme.html

exit
port=8085
./pixiv-novel.py -B -p $port &
pid=$!
screenshot images/top.png    "http://localhost:$port"
screenshot images/novel.png  "http://localhost:$port/?cmd=fetch&id=17410715"
screenshot images/search.png "http://localhost:$port/?cmd=search&q=二次創作&npages=1&bookmarks=0&page=10&compact=1"
kill $pid

