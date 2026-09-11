# 6 Season 3 promo cards, reusing the same 4 background videos and the
# single music clip already used for the verse cards. Only 4 backgrounds
# for 6 cards, so the cycle repeats: tue, wed, thu, fri, tue, wed.
#
# headline_lines: manually-broken lines (not auto-wrapped) so "Luke + John
# Harmony" always lands intact on its own line -- auto word-wrap kept
# splitting it awkwardly ("...The Luke" / "+ John Harmony"). Each line is
# (text, bold) -- exactly one line per card is bold (the "Luke + John
# Harmony" line itself, wherever it falls), so the emphasis is on that
# phrase specifically, not on "whichever line happens to be second."
#
# cta: still auto-wrapped by build_promo_cards.py's wrap_text(), no manual
# breaks needed there.

CARDS = [
    {
        "output_name": "promo1_starts_monday",
        "video_key": "tue",
        "headline_lines": [
            ("Luke + John Harmony", True),
            ("— Starts Monday", False),
        ],
        "cta": "Five weeks. Two Gospels. One unforgettable walk with Jesus.",
    },
    {
        "output_name": "promo2_beginning_monday",
        "video_key": "wed",
        "headline_lines": [
            ("Beginning Monday:", False),
            ("Luke + John Harmony", True),
        ],
        "cta": "Join us on a five-week journey through two beautifully "
               "paired Gospels — each one a little different, together "
               "the fuller story.",
    },
    {
        "output_name": "promo3_new_season",
        "video_key": "thu",
        "headline_lines": [
            ("A New Season", False),
            ("Begins Monday —", False),
            ("Luke + John Harmony", True),
        ],
        "cta": "Five weeks to walk with Jesus, one day at a time.",
    },
    {
        "output_name": "promo4_coming_monday",
        "video_key": "fri",
        "headline_lines": [
            ("Luke + John Harmony", True),
            ("— Coming Monday", False),
        ],
        "cta": "Two Gospels, side by side, for five weeks — walk with "
               "Jesus in the fullest story yet.",
    },
    {
        "output_name": "promo5_same_jesus",
        "video_key": "tue",
        "headline_lines": [
            ("New Season Monday:", False),
            ("Luke + John Harmony", True),
        ],
        "cta": "Same Jesus. Two different witnesses. Five weeks to walk it "
               "with them.",
    },
    {
        "output_name": "promo6_starts_monday_v2",
        "video_key": "wed",
        "headline_lines": [
            ("Starts Monday:", False),
            ("Luke + John Harmony", True),
        ],
        "cta": "Five weeks through two beautifully paired Gospels — walk "
               "with Jesus, one day at a time.",
    },
]
