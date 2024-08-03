#!/usr/bin/env python3

import subprocess as sp, time, urllib.error as ue, urllib.parse as up, urllib.request as ur

port = 8001
proc = sp.Popen(["python", "pixiv-novel.py", "-p", str(port), "-c", ""])

def test(path):
    time.sleep(1)
    try:
        res = ur.urlopen(f"http://localhost:{port}{path}")
    except ue.HTTPError as e:
        return print(f"FAIL {path}   ", e)
    data = res.read()
    if len(data) < 1000:
        return print(f"FAIL {path}   ", "response too short", len(data))
    print(f"OK   {path}")

try:
    test("/")
    test("/novel?id=15898879")
    test("/search?q=" + up.quote("著作権フリー"))
finally:
    proc.kill()
