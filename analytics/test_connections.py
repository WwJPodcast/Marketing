"""
test_connections.py

Checks that every analytics secret in GitHub Actions works.
Prints only PASS/FAIL and harmless totals. Never prints a secret.
Standard library only, so no installs are needed.
"""

import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_FB_PAGE_ID = "1200454029823959"


def call(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"raw": body[:200]}


def missing(names):
    return [n for n in names if not os.environ.get(n)]


def test_youtube():
    need = ["YOUTUBE_REFRESH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"]
    gone = missing(need)
    if gone:
        return False, "missing secrets: " + ", ".join(gone)

    body = urllib.parse.urlencode({
        "client_id": os.environ["GOOGLE_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode()
    status, resp = call("https://oauth2.googleapis.com/token", data=body, method="POST")
    if status != 200:
        return False, f"token step {status}: {resp.get('error_description') or resp.get('error')}"

    end = datetime.date.today()
    start = end - datetime.timedelta(days=28)
    qs = urllib.parse.urlencode({
        "ids": "channel==MINE",
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "metrics": "views,estimatedMinutesWatched,subscribersGained",
    })
    status, resp = call(
        "https://youtubeanalytics.googleapis.com/v2/reports?" + qs,
        headers={"Authorization": "Bearer " + resp["access_token"]},
    )
    if status != 200:
        return False, f"analytics step {status}: {str(resp)[:150]}"
    views = (resp.get("rows") or [[0]])[0][0]
    return True, f"last 28 days views = {views}"


def test_facebook():
    if missing(["FACEBOOK_PAGE_TOKEN"]):
        return False, "missing secrets: FACEBOOK_PAGE_TOKEN"
    token = os.environ["FACEBOOK_PAGE_TOKEN"]
    page_id = os.environ.get("FACEBOOK_PAGE_ID") or DEFAULT_FB_PAGE_ID

    qs = urllib.parse.urlencode({"fields": "name,followers_count", "access_token": token})
    status, resp = call(f"https://graph.facebook.com/{page_id}?{qs}")
    if status != 200:
        return False, f"page step {status}: {resp.get('error', {}).get('message')}"

    qs = urllib.parse.urlencode({
        "metric": "page_media_view", "period": "days_28", "access_token": token,
    })
    status, ins = call(f"https://graph.facebook.com/{page_id}/insights?{qs}")
    if status != 200:
        return False, f"insights step {status}: {ins.get('error', {}).get('message')}"
    return True, f"page '{resp.get('name')}', followers = {resp.get('followers_count')}"


def test_buffer():
    if missing(["BUFFER_API_KEY"]):
        return False, "missing secrets: BUFFER_API_KEY"
    status, resp = call(
        "https://api.buffer.com",
        data=json.dumps({"query": "{ account { id timezone } }"}).encode(),
        headers={
            "Authorization": "Bearer " + os.environ["BUFFER_API_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    if status != 200 or resp.get("errors"):
        return False, f"{status}: {str(resp)[:150]}"
    return True, "account reachable, timezone = " + str(resp["data"]["account"]["timezone"])


def main():
    results = []
    for name, fn in [("YouTube", test_youtube), ("Facebook", test_facebook), ("Buffer", test_buffer)]:
        try:
            ok, msg = fn()
        except Exception as e:  # keep going so we see every result
            ok, msg = False, "error: " + type(e).__name__
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {msg}")
        results.append(ok)
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
