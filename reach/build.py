#!/usr/bin/env python3
"""
WWJ Reach: nightly build.

Pulls numbers for five channels, saves them, and writes the phone page:
  YouTube    YouTube Analytics API   (OAuth refresh token)
  Facebook   Graph API Page insights (Page token)
  Instagram, TikTok, Pinterest   Buffer API (API key)

Outputs, next to this file:
  history.json  Buffer only keeps 31 days, so every post's running totals are
                saved here each night. This file is the long-term memory.
  data.json     what the page shows
  index.html    template.html with data.json filled in

If one source fails, last night's numbers for that channel are kept and the
page shows a small "not updated" note. Secrets come from environment
variables (GitHub Actions secrets) and are never printed or written.
Standard library only.
"""

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
TZ = ZoneInfo("America/Chicago")
PT = ZoneInfo("America/Los_Angeles")  # Facebook cuts its days at Pacific midnight
WEEKS, DAILY = 26, 14
SPAN = WEEKS * 7
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DOWS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FB_PAGE_ID_DEFAULT = "1200454029823959"

SECRET_VARS = ["YOUTUBE_REFRESH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET",
               "FACEBOOK_PAGE_TOKEN", "BUFFER_API_KEY"]


class SourceError(Exception):
    pass


NOTES = []  # harmless run notes (counts, channel names) saved into data.json


def clean(msg):
    """Strip any secret value out of an error message before it is printed."""
    msg = str(msg)
    for name in SECRET_VARS:
        val = os.environ.get(name)
        if val:
            msg = msg.replace(val, "***")
    return msg[:300]


def need(*names):
    gone = [n for n in names if not os.environ.get(n)]
    if gone:
        raise SourceError("missing secret(s): " + ", ".join(gone))


def http(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            j = json.loads(body)
        except Exception:
            j = {}
        err = j.get("error")
        if isinstance(err, dict):
            why = err.get("message") or str(err)[:150]
        else:
            why = j.get("error_description") or err or body[:150]
        raise SourceError(f"HTTP {e.code}: {why}")
    except urllib.error.URLError as e:
        raise SourceError(f"network error: {e.reason}")


# ---------------------------------------------------------------- series maths

def iso(d):
    return d.isoformat()


def build_series(daymap, first_date, yday):
    """daymap {date: (views, engaged)} -> (daily 14, weekly 26), ending yesterday.
    Weeks are rolling 7-day blocks ending yesterday, so the newest week is
    exactly the 'last 7 days' on the page. Days before tracking began are None."""
    days = [yday - dt.timedelta(days=i) for i in range(SPAN - 1, -1, -1)]

    def one(d):
        if first_date is None or d < first_date:
            return None
        return daymap.get(d, (0, 0))

    daily = []
    for d in days[-DAILY:]:
        x = one(d)
        daily.append({"d": iso(d), "v": None if x is None else x[0], "e": None if x is None else x[1]})

    weekly = []
    for k in range(WEEKS):
        block = days[k * 7:(k + 1) * 7]
        vals = [one(d) for d in block]
        have = [x for x in vals if x is not None]
        if not have:
            weekly.append({"d": iso(block[0]), "v": None, "e": None})
        else:
            weekly.append({"d": iso(block[0]), "v": sum(x[0] for x in have), "e": sum(x[1] for x in have)})
    return daily, weekly


def entry(key, name, via, views, daymap, first_date, lifetime, yday):
    daily, weekly = build_series(daymap, first_date, yday)
    wv = sum(w["v"] or 0 for w in weekly)
    we = sum(w["e"] or 0 for w in weekly)
    out = {"key": key, "name": name, "via": via, "views": views,
           "since": f"{MONTHS[first_date.month - 1]} {first_date.year}" if first_date else None,
           "daily": daily, "weekly": weekly}
    if lifetime is not None:
        # all-time on the page = the 26 weeks shown + this "before" amount
        out["before"] = {"v": max(0, lifetime[0] - wv), "e": max(0, lifetime[1] - we)}
    return out


def empty_entry(key, name, via, views="views"):
    return {"key": key, "name": name, "via": via, "views": views, "since": None,
            "daily": None, "weekly": None}


# --------------------------------------------------------------------- YouTube

def fetch_youtube(yday):
    need("YOUTUBE_REFRESH_TOKEN", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET")
    tok = http("https://oauth2.googleapis.com/token", method="POST",
               data=urllib.parse.urlencode({
                   "client_id": os.environ["GOOGLE_CLIENT_ID"],
                   "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
                   "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
                   "grant_type": "refresh_token"}).encode())
    auth = {"Authorization": "Bearer " + tok["access_token"]}

    def report(start, dims=None):
        q = {"ids": "channel==MINE", "startDate": iso(start), "endDate": iso(yday),
             "metrics": "views,likes,comments,shares"}
        if dims:
            q["dimensions"] = dims
            q["sort"] = dims
        return http("https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode(q),
                    headers=auth).get("rows") or []

    daymap, first = {}, None
    for r in report(dt.date(2024, 1, 1), "day"):
        d = dt.date.fromisoformat(r[0])
        v, e = int(r[1]), int(r[2]) + int(r[3]) + int(r[4])
        daymap[d] = (v, e)
        if first is None and (v or e):
            first = d
    life = report(dt.date(2015, 1, 1))
    lifetime = (int(life[0][0]), int(life[0][1]) + int(life[0][2]) + int(life[0][3])) if life else (0, 0)
    return entry("yt", "YouTube", "YouTube API", "views", daymap, first, lifetime, yday)


# -------------------------------------------------------------------- Facebook

def fetch_facebook(yday):
    need("FACEBOOK_PAGE_TOKEN")
    token = os.environ["FACEBOOK_PAGE_TOKEN"]
    page = os.environ.get("FACEBOOK_PAGE_ID") or FB_PAGE_ID_DEFAULT
    end0 = int(dt.datetime.combine(yday + dt.timedelta(days=1), dt.time.min, tzinfo=PT).timestamp())

    def series(metric):
        out = {}
        for i in range(8):  # 92-day chunks, newest first, stop once old chunks are empty
            until = end0 - i * 92 * 86400
            q = {"metric": metric, "period": "day", "since": until - 92 * 86400,
                 "until": until, "access_token": token}
            try:
                data = http(f"https://graph.facebook.com/{page}/insights?" + urllib.parse.urlencode(q))
            except SourceError:
                if i == 0:
                    raise
                break
            vals = (data.get("data") or [{}])[0].get("values") or []
            got = False
            for x in vals:
                t = dt.datetime.strptime(x["end_time"], "%Y-%m-%dT%H:%M:%S%z") - dt.timedelta(seconds=1)
                d = t.astimezone(PT).date()
                n = int(x.get("value") or 0)
                if n:
                    got = True
                out[d] = n
            if i >= 2 and not got:
                break
        return out

    views, eng = series("page_media_view"), series("page_post_engagements")
    daymap = {d: (views.get(d, 0), eng.get(d, 0)) for d in set(views) | set(eng) if d <= yday}
    first = min((d for d, x in daymap.items() if x[0] or x[1]), default=None)
    lifetime = (sum(x[0] for x in daymap.values()), sum(x[1] for x in daymap.values()))
    return entry("fb", "Facebook", "Facebook API", "views", daymap, first, lifetime, yday)


# ---------------------------------------------------------------------- Buffer

BUFFER_KEYS = {"instagram": ("ig", "Instagram"), "tiktok": ("tt", "TikTok"), "pinterest": ("pin", "Pinterest")}

POSTS_Q = """query($org: OrganizationId!, $after: String, $ch: [ChannelId!]){
  posts(first:100, after:$after, input:{organizationId:$org, filter:{status:[sent], channelIds:$ch},
        sort:[{field:dueAt, direction:desc}]}){
    edges{ node{ id channelService sentAt metrics{ type value } } }
    pageInfo{ hasNextPage endCursor } } }"""


def gql(query, variables=None):
    need("BUFFER_API_KEY")
    r = http("https://api.buffer.com", method="POST",
             data=json.dumps({"query": query, "variables": variables or {}}).encode(),
             headers={"Authorization": "Bearer " + os.environ["BUFFER_API_KEY"],
                      "Content-Type": "application/json"})
    if r.get("errors"):
        raise SourceError("Buffer: " + str(r["errors"][0].get("message"))[:150])
    return r["data"]


def post_numbers(metrics):
    m = {x["type"]: x.get("value") or 0 for x in metrics}
    views = m["views"] if "views" in m else m.get("impressions", 0)
    eng = sum(m.get(k, 0) for k in ("reactions", "comments", "shares", "saves"))
    return int(round(views)), int(round(eng))


def update_history(history, yday):
    orgs = gql("{ account { organizations { id } } }")["account"]["organizations"]
    NOTES.append(f"Buffer: {len(orgs)} organization(s) visible to the API key")
    org = orgs[0]["id"]
    chans = gql("query($o: OrganizationId!){ channels(input:{organizationId:$o}){ id service isLocked isDisconnected } }",
                {"o": org})["channels"]
    if not chans:
        raise SourceError("this Buffer API key can see no channels (key made under a different Buffer login?)")
    locked = {c["service"]: bool(c.get("isLocked")) for c in chans if c["service"] in BUFFER_KEYS}
    ids = [c["id"] for c in chans if c["service"] in BUFFER_KEYS and not c.get("isLocked") and not c.get("isDisconnected")]
    NOTES.append("Buffer channels: " + ", ".join(
        f"{c['service']}{' (locked)' if c.get('isLocked') else ''}{' (disconnected)' if c.get('isDisconnected') else ''}"
        for c in chans) + f"; tracking {len(ids)}")
    asof = iso(yday)
    if ids:
        after, seen = None, 0
        for _ in range(30):
            page = gql(POSTS_Q, {"org": org, "after": after, "ch": ids})["posts"]
            for edge in page["edges"]:
                n = edge["node"]
                seen += 1
                if n["metrics"] is None or n["channelService"] not in BUFFER_KEYS:
                    continue  # no numbers yet: nothing to save, try again tomorrow
                v, e = post_numbers(n["metrics"])
                sent = dt.datetime.fromisoformat(n["sentAt"].replace("Z", "+00:00")).astimezone(TZ).date()
                rec = history["posts"].setdefault(n["id"], {"ch": n["channelService"], "sent": iso(sent), "snaps": []})
                snaps, row = rec["snaps"], [asof, v, e]
                if snaps and snaps[-1][0] == asof:
                    snaps[-1] = row  # same night run twice: replace
                elif not snaps or (snaps[-1][1], snaps[-1][2]) != (v, e):
                    snaps.append(row)
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        NOTES.append(f"Buffer posts read: {seen}; saved with numbers: {len(history['posts'])}")
    return locked


def history_daymap(history, channel):
    """Turn saved running totals into per-day numbers.
    A post's first saved total lands on the day it was sent; every later change
    lands on the night it was seen."""
    dm = {}

    def add(d, v, e):
        a, b = dm.get(d, (0, 0))
        dm[d] = (a + v, b + e)

    for rec in history["posts"].values():
        if rec["ch"] != channel or not rec["snaps"]:
            continue
        snaps = rec["snaps"]
        first_seen = dt.date.fromisoformat(snaps[0][0])
        add(min(dt.date.fromisoformat(rec["sent"]), first_seen), snaps[0][1], snaps[0][2])
        for prev, cur in zip(snaps, snaps[1:]):
            add(dt.date.fromisoformat(cur[0]), cur[1] - prev[1], cur[2] - prev[2])
    return {d: (max(0, v), max(0, e)) for d, (v, e) in dm.items()}


def buffer_entries(history, locked, yday):
    out = {}
    for service, (key, name) in BUFFER_KEYS.items():
        via = "Buffer" + (" · locked on the free plan" if locked.get(service) else "")
        dm = history_daymap(history, service)
        if not dm:
            out[key] = empty_entry(key, name, via)
            continue
        first = min(dm)
        lifetime = (sum(x[0] for x in dm.values()), sum(x[1] for x in dm.values()))
        out[key] = entry(key, name, via, "views", dm, first, lifetime, yday)
    return out


# ------------------------------------------------------------------------ main

def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def label(now):
    h = now.hour % 12 or 12
    return f"{DOWS[now.weekday()]} {now.month}/{now.day} {h}:{now.minute:02d} {'AM' if now.hour < 12 else 'PM'}"


def main():
    now = dt.datetime.now(TZ)
    yday = now.date() - dt.timedelta(days=1)
    history = load(HERE / "history.json", {"posts": {}})
    prev = load(HERE / "data.json", {})
    prev_by_key = {p["key"]: p for p in prev.get("platforms", [])}
    prev_day = prev.get("updated_date")
    prev_short = None
    if prev_day:
        d = dt.date.fromisoformat(prev_day)
        prev_short = f"{d.month}/{d.day}"

    results, failures = {}, {}

    for key, fn in (("yt", fetch_youtube), ("fb", fetch_facebook)):
        try:
            results[key] = fn(yday)
        except Exception as ex:  # keep going; one source must not sink the page
            failures[key] = clean(ex)

    try:
        locked = update_history(history, yday)
        results.update(buffer_entries(history, locked, yday))
    except Exception as ex:
        for k in ("ig", "tt", "pin"):
            failures[k] = clean(ex)
        # still rebuild what history already knows so the page is not stale
        results.update(buffer_entries(history, {}, yday))
        for k in ("ig", "tt", "pin"):
            if results[k].get("daily"):
                results[k]["stale"] = prev_short or "last run"

    names = {"yt": "YouTube", "fb": "Facebook", "ig": "Instagram", "tt": "TikTok", "pin": "Pinterest"}
    vias = {"yt": "YouTube API", "fb": "Facebook API", "ig": "Buffer", "tt": "Buffer", "pin": "Buffer"}
    platforms = []
    for key in ("yt", "fb", "ig", "tt", "pin"):
        if key in results:
            platforms.append(results[key])
            continue
        old = prev_by_key.get(key)
        if old and old.get("daily"):
            old = dict(old)
            old["stale"] = old.get("stale") or prev_short or "last run"
            platforms.append(old)
        else:
            platforms.append(empty_entry(key, names[key], vias[key]))

    for key, why in failures.items():
        print(f"::warning::{names[key]} not updated: {why}")

    if not any(p.get("daily") for p in platforms):
        print("::error::No channel produced numbers; leaving the page as it was.")
        sys.exit(1)

    data = {"updated": label(now), "updated_date": iso(now.date()), "platforms": platforms, "notes": NOTES}
    (HERE / "data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    (HERE / "history.json").write_text(json.dumps(history, separators=(",", ":")), encoding="utf-8")

    page = (HERE / "template.html").read_text(encoding="utf-8")
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    assert page.count("__DATA_JSON__") == 1
    (HERE / "index.html").write_text(page.replace("__DATA_JSON__", blob), encoding="utf-8")

    for p in platforms:
        status = "ok" if p["key"] in results else ("kept last night's" if p.get("daily") else "empty")
        week = p["daily"] and sum(x["v"] or 0 for x in p["daily"][7:])
        print(f"{p['name']:<10} {status:<18} last 7 days views: {week if p['daily'] else '-'}")


if __name__ == "__main__":
    main()
