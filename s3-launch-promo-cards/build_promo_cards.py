"""
Build 6 Season 3 launch-announcement promo videos, reusing the same 4
Pixabay background clips, the single music bed, the WwJ logo, and the
verse-card visual style (drop-shadow text, no background box) already
established in wwj_verse_video_cards/build_verse_cards.py -- just with a
headline + CTA line instead of a verse + reference.

Headline lines are manually broken (see promo_cards_data.py) rather than
auto-wrapped, so "Luke + John Harmony" always lands intact on one line;
exactly one of those lines (the "Luke + John Harmony" line itself) renders
in the bold weight for emphasis, regardless of whether it's the first or
last line.

Sequence per card (15s total):
  0:00-10:00  background video (trimmed to first 10s) + headline lines,
              smaller italic CTA block below
  10:00       crossfade (0.75s) into the WwJ logo card
  ~10:00-15:00 logo holds (5s total screen time; the crossfade eats into
              this window, not added on top)
  14:00-15:00 video + music fade out together

Music: same mp3 as the verse cards, staggered 15-second slices per card.

REQUIRES: ffmpeg on PATH.

Run with --preview to render only a single still frame per card (fast, no
audio/logo needed) for layout review before spending time on full builds.
"""

import argparse
import os
import subprocess

from PIL import ImageFont

from promo_cards_data import CARDS

# ---------------------------------------------------------------------
# CONFIG -- carried over verbatim from wwj_verse_video_cards/build_verse_cards.py
# ---------------------------------------------------------------------

BACKGROUND_FOLDER = r"C:\Users\PF579L6W.LAPTOP-U20I826H\Documents\cp\Cowork\Podcast\Video\Background Downloads"
OUTPUT_FOLDER = os.path.join(BACKGROUND_FOLDER, "Output_S3_Promo")
PREVIEW_FOLDER = os.path.join(OUTPUT_FOLDER, "previews")

DAY_VIDEO_MAP = {
    "tue": "135333-761273772.mp4",
    "wed": "326081.mp4",
    "thu": "340515.mp4",
    "fri": "231531.mp4",
}

MUSIC_FILE = "andriig-nature-nature-music-566826.mp3"

LOGO_FILE = r"C:\Users\PF579L6W.LAPTOP-U20I826H\Documents\cp\Cowork\Podcast\WwJ Logo.png"
LOGO_IS_IMAGE = True
LOGO_PAD_COLOR = "0xFDF5EB"

FONT_FILE = r"C:\Windows\Fonts\georgia.ttf"
FONT_FILE_BOLD = r"C:\Windows\Fonts\georgiab.ttf"
FONT_FILE_ITALIC = r"C:\Windows\Fonts\georgiai.ttf"

RESOLUTION = (1080, 1920)
OUTPUT_FPS = 30
HEADLINE_FONT_SIZE = 68
CTA_FONT_SIZE = 42
TEXT_COLOR = "white"
TEXT_SHADOW_COLOR = "black@0.65"
TEXT_SHADOW_OFFSET = 3
HEADLINE_LINE_SPACING = 14
CTA_LINE_SPACING = 10
HEADLINE_CTA_GAP = 70
TEXT_MAX_WIDTH = RESOLUTION[0] - 160

TEXT_DURATION = 10.0
CROSSFADE_DURATION = 0.75
LOGO_HOLD_DURATION = 5.0
FADE_OUT_DURATION = 1.0
MUSIC_FADE_IN = 0.5
MUSIC_STAGGER = 15.0

LOGO_CLIP_LENGTH = LOGO_HOLD_DURATION + CROSSFADE_DURATION
TOTAL_DURATION = TEXT_DURATION + LOGO_CLIP_LENGTH - CROSSFADE_DURATION  # 15.0s

# ---------------------------------------------------------------------


def write_text_file(path, text):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def wrap_text(text, font_path, font_size, max_width):
    font = ImageFont.truetype(font_path, font_size)
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def line_height(font_path, font_size):
    ascent, descent = ImageFont.truetype(font_path, font_size).getmetrics()
    return ascent + descent


def ffpath(path):
    return path.replace("\\", "/").replace(":", "\\:")


def build_headline_and_cta_filter(card, out_folder, w, h):
    """Returns (filter_str, cleanup_paths). Headline lines render one
    drawtext per line (regular or bold font per line, per
    promo_cards_data.py); CTA renders as one auto-wrapped block below it,
    all centered together as a single group using real font metrics."""
    headline_lines = card["headline_lines"]
    cta_lines = wrap_text(card["cta"], FONT_FILE_ITALIC, CTA_FONT_SIZE, TEXT_MAX_WIDTH)

    line_h = line_height(FONT_FILE, HEADLINE_FONT_SIZE)  # regular/bold share metrics closely enough
    cta_line_h = line_height(FONT_FILE_ITALIC, CTA_FONT_SIZE)

    headline_block_h = len(headline_lines) * line_h + (len(headline_lines) - 1) * HEADLINE_LINE_SPACING
    cta_block_h = len(cta_lines) * cta_line_h + (len(cta_lines) - 1) * CTA_LINE_SPACING
    total_h = headline_block_h + HEADLINE_CTA_GAP + cta_block_h
    top = (h - total_h) // 2

    draws = []
    cleanup = []
    y = top
    for i, (text, bold) in enumerate(headline_lines):
        font_file = FONT_FILE_BOLD if bold else FONT_FILE
        txt_path = os.path.join(out_folder, f"{card['output_name']}_headline{i}.txt")
        write_text_file(txt_path, text)
        cleanup.append(txt_path)
        draws.append(
            f"drawtext=fontfile='{ffpath(font_file)}':textfile='{ffpath(txt_path)}':"
            f"fontsize={HEADLINE_FONT_SIZE}:fontcolor={TEXT_COLOR}:"
            f"shadowx={TEXT_SHADOW_OFFSET}:shadowy={TEXT_SHADOW_OFFSET}:shadowcolor={TEXT_SHADOW_COLOR}:"
            f"x=(w-text_w)/2:y={y}"
        )
        y += line_h + HEADLINE_LINE_SPACING

    cta_top = top + headline_block_h + HEADLINE_CTA_GAP
    cta_txt_path = os.path.join(out_folder, f"{card['output_name']}_cta.txt")
    write_text_file(cta_txt_path, "\n".join(cta_lines))
    cleanup.append(cta_txt_path)
    draws.append(
        f"drawtext=fontfile='{ffpath(FONT_FILE_ITALIC)}':textfile='{ffpath(cta_txt_path)}':"
        f"fontsize={CTA_FONT_SIZE}:fontcolor={TEXT_COLOR}:line_spacing={CTA_LINE_SPACING}:"
        f"shadowx={TEXT_SHADOW_OFFSET}:shadowy={TEXT_SHADOW_OFFSET}:shadowcolor={TEXT_SHADOW_COLOR}:"
        f"x=(w-text_w)/2:y={cta_top}"
    )

    return ",".join(draws), cleanup


def build_preview(card):
    os.makedirs(PREVIEW_FOLDER, exist_ok=True)
    bg_path = os.path.join(BACKGROUND_FOLDER, DAY_VIDEO_MAP[card["video_key"]])
    out_path = os.path.join(PREVIEW_FOLDER, card["output_name"] + "_preview.png")
    w, h = RESOLUTION

    text_filter, cleanup = build_headline_and_cta_filter(card, PREVIEW_FOLDER, w, h)
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,"
        + text_filter
    )
    cmd = [
        "ffmpeg", "-y", "-i", bg_path, "-ss", "2", "-vframes", "1",
        "-update", "1", "-vf", vf, out_path,
    ]
    print(f"Rendering preview: {card['output_name']} ...")
    subprocess.run(cmd, check=True)
    print(f"  -> {out_path}")
    for p in cleanup:
        os.remove(p)
    return out_path


def build_card(card, index):
    bg_path = os.path.join(BACKGROUND_FOLDER, DAY_VIDEO_MAP[card["video_key"]])
    music_path = os.path.join(BACKGROUND_FOLDER, MUSIC_FILE)
    logo_path = LOGO_FILE
    out_path = os.path.join(OUTPUT_FOLDER, card["output_name"] + ".mp4")
    w, h = RESOLUTION

    text_filter, cleanup = build_headline_and_cta_filter(card, OUTPUT_FOLDER, w, h)
    music_start = index * MUSIC_STAGGER

    v1 = (
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1,trim=duration={TEXT_DURATION},"
        f"setpts=PTS-STARTPTS,{text_filter},fps={OUTPUT_FPS}[v1]"
    )

    logo_input_idx = 1
    if LOGO_IS_IMAGE:
        logo_input_opts = ["-loop", "1", "-t", str(LOGO_CLIP_LENGTH), "-i", logo_path]
    else:
        logo_input_opts = ["-stream_loop", "-1", "-t", str(LOGO_CLIP_LENGTH), "-i", logo_path]

    v2 = (
        f"[{logo_input_idx}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color={LOGO_PAD_COLOR},setsar=1,"
        f"trim=duration={LOGO_CLIP_LENGTH},"
        f"setpts=PTS-STARTPTS,fps={OUTPUT_FPS}[v2]"
    )

    xfade_offset = TEXT_DURATION - CROSSFADE_DURATION
    vcombine = (
        f"[v1][v2]xfade=transition=fade:duration={CROSSFADE_DURATION}:"
        f"offset={xfade_offset}[vx]"
    )
    vfadeout = (
        f"[vx]fade=t=out:st={TOTAL_DURATION - FADE_OUT_DURATION}:"
        f"d={FADE_OUT_DURATION}[vout]"
    )

    afilter = (
        f"[2:a]atrim=start={music_start}:end={music_start + TOTAL_DURATION},"
        f"asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d={MUSIC_FADE_IN},"
        f"afade=t=out:st={TOTAL_DURATION - FADE_OUT_DURATION}:"
        f"d={FADE_OUT_DURATION}[aout]"
    )

    filter_complex = ";".join([v1, v2, vcombine, vfadeout, afilter])

    cmd = [
        "ffmpeg", "-y",
        "-i", bg_path,
        *logo_input_opts,
        "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "[vout]", "-map", "[aout]",
        "-t", str(TOTAL_DURATION),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        out_path,
    ]

    print(f"\nBuilding {card['output_name']} ...")
    subprocess.run(cmd, check=True)
    print(f"  -> {out_path}")
    for p in cleanup:
        os.remove(p)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview", action="store_true",
                         help="render one still frame per card instead of the full video")
    args = parser.parse_args()

    if args.preview:
        for card in CARDS:
            build_preview(card)
        print(f"\nDone. {len(CARDS)} preview stills in {PREVIEW_FOLDER}")
        return

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    for i, card in enumerate(CARDS):
        build_card(card, i)
    print(f"\nDone. {len(CARDS)} clips in {OUTPUT_FOLDER}")


if __name__ == "__main__":
    main()
