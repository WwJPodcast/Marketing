"""
WWJ Reach: per-post numbers for every platform.

build.py calls into this file. It keeps one record per post, in one shape for
all five platforms, so post types, platforms and posting cadence can be compared
on equal terms. Results go to reach/posts.json (the page itself is unchanged).

Where each platform's per-post numbers come from:
  YouTube    YouTube Analytics API, one row per video (dimensions=video), plus the
             Data API for title, publish time and length
  Facebook   the Reels/videos list build.py already reads (fetch_facebook_posts)
  Instagram, TikTok, Pinterest   the Buffer posts build.py already reads

Running totals are saved each night in history.json, so a post can be compared
at the same age (views at 1 day and at 7 days old) no matter when it went out:
  history["posts"]   Buffer posts (existing records, now with caption, file, metrics)
  history["extra"]   YouTube ("yt:<id>") and Facebook ("fb:<id>") posts, same shape

Post type comes from the video file name when it is known (nature_, tomorrow_,
promo_, the Scheduler's own names), then from length (over 3 minutes is a full
episode), then from the caption. "tag_by" says which one decided it.

Standard library only.
"""

import datetime as dt
import json
import re
import statistics
import urllib.parse

TYPES = ("nature", "tomorrow", "promo")
EPISODE_SECONDS = 180          # longer than this is a full episode, not a clip
YT_MAX_VIDEOS = 200            # the Analytics API's cap for a per-video report
PLATFORM_OF = {"youtube": "yt", "facebook": "fb", "instagram": "ig", "tiktok": "tt", "pinterest": "pin"}

VERSE_START = re.compile(r"\s*(?:[123]\s*)?[A-Z][a-z]+\.?\s+\d+:\d+")
TOMORROW = re.compile(r"tomorrow'?s\s+episode", re.I)


# ------------------------------------------------------------------ post type

def post_type(file=None, text=None, length=None):
    """-> (type, tag_by). type is nature / tomorrow / promo / episode / other."""
    name = (file or "").rsplit("/", 1)[-1].lower()
    for k in TYPES:
        if name.startswith(k + "_"):
            return k, "file"
    if length and length > EPISODE_SECONDS:
        return "episode", "length"
    t = text or ""
    if not t.strip():
        return "other", "none"
    if TOMORROW.search(t):
        return "tomorrow", "caption"
    if VERSE_START.match(t):
        return "nature", "caption"
    return "promo", "caption"


def snippet(text, n=60):
    return " ".join(str(text or "").split())[:n]


# -------------------------------------------------------- saving running totals

def snap(rec, asof, v, e):
    """Add tonight's totals to a record. Same rules as the Buffer history:
    a second run on the same night replaces, an unchanged total is not repeated."""
    snaps, row = rec.setdefault("snaps", []), [asof, v, e]
    if snaps and snaps[-1][0] == asof:
        snaps[-1] = row
    elif not snaps or (snaps[-1][1], snaps[-1][2]) != (v, e):
        snaps.append(row)
    rec["seen"] = asof


def at_age(rec, days):
    """Views and engaged when the post was `days` days old, or None when that is
    not known (post too young, or tracking began after that age)."""
    snaps, sent, seen = rec.get("snaps") or [], rec.get("sent"), rec.get("seen")
    if not snaps or not sent:
        return None
    target = (dt.date.fromisoformat(sent) + dt.timedelta(days=days)).isoformat()
    seen = seen or snaps[-1][0]
    if seen < target or snaps[0][0] > target:
        return None
    last = [s for s in snaps if s[0] <= target][-1]
    return last[1], last[2]


# ------------------------------------------------------------------- Buffer

# Richer version of build.py's POSTS_Q. If Buffer rejects any of the extra fields,
# build.py falls back to the plain query and the posts simply carry no caption/file.
POSTS_Q_RICH = """query($org: OrganizationId!, $after: String, $ch: [ChannelId!]){
  posts(first:100, after:$after, input:{organizationId:$org, filter:{status:[sent], channelIds:$ch},
        sort:[{field:dueAt, direction:desc}]}){
    edges{ node{ id channelService sentAt text externalLink metrics{ type value }
                 assets{ type source ... on VideoAsset { video { durationMs } } } } }
    pageInfo{ hasNextPage endCursor } } }"""


def buffer_details(rec, node, tz):
    """Copy caption, file, length, link and every metric Buffer gives onto a history record."""
    if node.get("text") is not None:
        rec["x"] = snippet(node["text"])
    assets = node.get("assets") or []
    if assets:
        a = assets[0]
        if a.get("source"):
            rec["file"] = str(a["source"]).rsplit("/", 1)[-1][:80]
        ms = ((a.get("video") or {}).get("durationMs"))
        if isinstance(ms, (int, float)):
            rec["len"] = round(ms / 1000)
    if node.get("externalLink"):
        rec["url"] = node["externalLink"]
    if node.get("sentAt"):
        rec["at"] = dt.datetime.fromisoformat(node["sentAt"].replace("Z", "+00:00")).astimezone(tz).strftime("%Y-%m-%dT%H:%M")
    rec["m"] = {x["type"]: x.get("value") for x in (node.get("metrics") or []) if x.get("value") is not None}


# ------------------------------------------------------------------ YouTube

def iso_seconds(s):
    """'PT1M5S' -> 65."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + se


def fetch_youtube_posts(history, auth, http, start, yday, tz, notes, clean):
    """One Analytics row per video since `start`, saved into history['extra']."""
    q = {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": yday.isoformat(),
         "dimensions": "video", "sort": "-views", "maxResults": YT_MAX_VIDEOS,
         "metrics": "views,likes,comments,shares,averageViewDuration,averageViewPercentage"}
    j = http("https://youtubeanalytics.googleapis.com/v2/reports?" + urllib.parse.urlencode(q), headers=auth)
    heads = [h.get("name") for h in j.get("columnHeaders") or []]
    rows = [dict(zip(heads, r)) for r in j.get("rows") or []]
    if len(rows) >= YT_MAX_VIDEOS:
        notes.append(f"YouTube per-video: hit the {YT_MAX_VIDEOS}-video cap; the least-viewed videos are left out")

    # Titles, publish times and lengths come from the Data API. This needs the
    # youtube.readonly scope on the same refresh token; without it the numbers are
    # still saved, just with no title, publish time or length.
    meta, ids = {}, [r["video"] for r in rows]
    try:
        for i in range(0, len(ids), 50):
            d = http("https://www.googleapis.com/youtube/v3/videos?" + urllib.parse.urlencode(
                {"part": "snippet,contentDetails", "id": ",".join(ids[i:i + 50]), "maxResults": 50}), headers=auth)
            for it in d.get("items") or []:
                sn = it.get("snippet") or {}
                meta[it["id"]] = {"title": sn.get("title") or "", "desc": sn.get("description") or "",
                                  "pub": sn.get("publishedAt"),
                                  "len": iso_seconds((it.get("contentDetails") or {}).get("duration"))}
    except Exception as ex:
        notes.append(f"YouTube titles/publish times not available (needs youtube.readonly scope?): {clean(ex)}")

    asof = yday.isoformat()
    for r in rows:
        vid = r["video"]
        rec = history.setdefault("extra", {}).setdefault("yt:" + vid, {"ch": "youtube"})
        m = meta.get(vid)
        if m:
            if m["pub"]:
                t = dt.datetime.fromisoformat(m["pub"].replace("Z", "+00:00")).astimezone(tz)
                rec["sent"], rec["at"] = t.date().isoformat(), t.strftime("%Y-%m-%dT%H:%M")
            rec["x"] = snippet(m["title"])
            rec["len"] = m["len"]
            rec["tagtext"] = snippet(m["title"] + " " + m["desc"], 200)
        rec.setdefault("sent", asof)  # no publish time: first night seen
        rec["url"] = "https://youtube.com/shorts/" + vid if (rec.get("len") or 0) <= EPISODE_SECONDS else "https://youtu.be/" + vid
        v = int(r.get("views") or 0)
        e = int(r.get("likes") or 0) + int(r.get("comments") or 0) + int(r.get("shares") or 0)
        rec["m"] = {k: r.get(k) for k in ("views", "likes", "comments", "shares",
                                          "averageViewDuration", "averageViewPercentage")}
        snap(rec, asof, v, e)
    notes.append(f"YouTube per-video: {len(rows)} videos, titles for {len(meta)}")


# ----------------------------------------------------------------- Facebook

def save_facebook_posts(history, rows, yday, tz, notes):
    """rows = fetch_facebook_posts' item list (live time, length, caption, views,
    likes/comments when Meta returns them). Saved so Facebook keeps more than 21 days."""
    asof, n = yday.isoformat(), 0
    for i in rows:
        if i.get("views") is None or i["live"].astimezone(tz).date() > yday:
            continue  # not live yet, or no views number this run
        rec = history.setdefault("extra", {}).setdefault("fb:" + i["id"], {"ch": "facebook"})
        live = i["live"].astimezone(tz)
        rec.update({"sent": live.date().isoformat(), "at": live.strftime("%Y-%m-%dT%H:%M"),
                    "x": snippet(i.get("text")), "len": i.get("len"), "kind": i.get("type")})
        if i.get("url"):
            rec["url"] = i["url"]
        likes, comments = i.get("likes"), i.get("comments")
        rec["m"] = {"views": i["views"], "likes": likes, "comments": comments, "views_metric": i.get("src")}
        snap(rec, asof, int(i["views"]), int(likes or 0) + int(comments or 0))
        n += 1
    notes.append(f"Facebook per-post: {n} saved")


# ------------------------------------------------------------------ output

def one_post(rec, pid, today):
    p = PLATFORM_OF.get(rec["ch"])
    m = rec.get("m") or {}
    typ, tag_by = post_type(rec.get("file"), rec.get("tagtext") or rec.get("x"), rec.get("len"))
    last = rec["snaps"][-1] if rec.get("snaps") else [None, None, None]
    d1, d7 = at_age(rec, 1), at_age(rec, 7)
    watch = m.get("averageViewDuration") if p == "yt" else m.get("averageTimeWatched")
    out = {"p": p, "id": pid, "t": rec.get("at") or rec.get("sent"), "type": typ, "tag_by": tag_by,
           "len": rec.get("len"), "x": rec.get("x"), "url": rec.get("url"),
           "age": (today - dt.date.fromisoformat(rec["sent"])).days if rec.get("sent") else None,
           "v": last[1], "e": last[2],
           "v1": d1 and d1[0], "v7": d7 and d7[0], "e7": d7 and d7[1],
           "watch": round(watch, 1) if isinstance(watch, (int, float)) else None,
           "watch_pct": m.get("averageViewPercentage"),
           "likes": m.get("likes", m.get("reactions")), "comments": m.get("comments"),
           "shares": m.get("shares"), "saves": m.get("saves"), "reach": m.get("reach")}
    if p == "fb":
        out["fb_kind"] = rec.get("kind")
    return out


def med(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return round(statistics.median(xs), 1) if xs else None


def group(posts, keyf):
    g = {}
    for x in posts:
        g.setdefault(keyf(x), []).append(x)
    out = []
    for k, xs in sorted(g.items(), key=lambda kv: str(kv[0])):
        v = sum(x["v"] or 0 for x in xs)
        e = sum(x["e"] or 0 for x in xs)
        out.append({"key": k, "posts": len(xs), "views": v, "engaged": e,
                    "eng_rate_pct": round(100 * e / v, 2) if v else None,
                    "median_views": med(x["v"] for x in xs),
                    "median_views_day1": med(x["v1"] for x in xs),
                    "median_views_day7": med(x["v7"] for x in xs), "with_day7": sum(1 for x in xs if x["v7"] is not None),
                    "median_watch_s": med(x["watch"] for x in xs)})
    return out


def week_of(t):
    d = dt.date.fromisoformat(t[:10])
    return (d - dt.timedelta(days=d.weekday())).isoformat()  # Monday


def write_posts(path, history, now, notes):
    today = now.date()
    recs = [(pid, r) for pid, r in (history.get("posts") or {}).items()]
    recs += [(pid.split(":", 1)[1], r) for pid, r in (history.get("extra") or {}).items()]
    posts = [one_post(r, pid, today) for pid, r in recs if r.get("snaps") and PLATFORM_OF.get(r.get("ch"))]
    posts.sort(key=lambda x: x["t"] or "", reverse=True)
    dated = [x for x in posts if x["t"]]
    summary = {
        # what kind of post works, per platform (compare median_views_day7 when with_day7 is decent)
        "by_type": group(posts, lambda x: f"{x['p']}/{x['type']}"),
        # cadence: posts per week against views per post that week
        "by_week": group(dated, lambda x: f"{x['p']}/{week_of(x['t'])}"),
        # time of day the post went out (local hour)
        "by_hour": group([x for x in dated if len(x["t"]) > 10], lambda x: f"{x['p']}/{x['t'][11:13]}"),
    }
    out = {"updated": now.strftime("%Y-%m-%d %H:%M"),
           "fields": {"p": "platform", "t": "posted (Central)", "type": "nature/tomorrow/promo/episode/other",
                      "tag_by": "file name, length or caption", "len": "seconds",
                      "v": "views to date", "e": "likes+comments+shares(+saves) to date",
                      "v1": "views at 1 day old", "v7": "views at 7 days old", "e7": "engaged at 7 days old",
                      "watch": "average seconds watched", "watch_pct": "average % watched (YouTube)",
                      "age": "days since posted"},
           "notes": notes, "posts": posts, "summary": summary}
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return len(posts)
