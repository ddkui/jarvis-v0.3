"""Delphi mark: the omphalos - the sacred conical stone that marked the
mythical "navel of the world" at Apollo's temple at Delphi, traditionally
shown bound in a knotted net (the agrenon). A fitting emblem for a personal
knowledge hub: a single anchoring stone at the center of everything you know.
Built at high supersampled resolution with PIL for crisp anti-aliased edges,
then downsized.
"""

import math
from PIL import Image, ImageDraw, ImageFont

SS = 4  # supersample factor
SIZE = 1024 * SS

AEGEAN = (18, 56, 92, 255)       # deep blue
AEGEAN_DARK = (12, 40, 68, 255)  # shadow/rim shade
IVORY = (245, 241, 232, 255)     # warm marble white
IVORY_SHADE = (214, 206, 188, 255)  # shaded marble
GOLD = (201, 162, 39, 255)       # antique gold
GOLD_LIGHT = (222, 188, 88, 255)

FONT_DIR = "/mnt/skills/examples/canvas-design/canvas-fonts"
GREEK_FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"


def _dome_polygon(cx, base_y, top_y, base_r, top_r, n=90):
    """A rounded, beehive-like silhouette (fat lower body, narrowing to a
    blunt rounded crown) approximating a hand-carved omphalos stone."""
    H = base_y - top_y
    left, right = [], []
    for i in range(n + 1):
        t = i / n  # 0 at base, 1 at apex
        y = base_y - t * H
        # slow taper through the body, sharper rounding near the crown
        r = top_r + (base_r - top_r) * (1 - t) ** 1.5
        # generous mid-body bulge for an organic, hand-shaped stone profile
        bulge = 1 + 0.30 * math.sin(math.pi * t) * (1 - t) ** 0.6
        r *= bulge
        left.append((cx - r, y))
        right.append((cx + r, y))
    return left + list(reversed(right))


def make_mark():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx, cy = SIZE / 2, SIZE / 2
    r = SIZE * 0.47

    # Outer gold rim, then deep blue disc inset slightly.
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD)
    r2 = r * 0.955
    d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=AEGEAN)

    # Subtle inner shadow ring for depth.
    r3 = r2 * 0.99
    d.ellipse([cx - r3, cy - r3, cx + r3, cy + r3], outline=AEGEAN_DARK, width=int(SIZE * 0.004))

    # --- Omphalos stone ---
    stone_base_r = SIZE * 0.255
    base_y = cy + SIZE * 0.245
    top_y = cy - SIZE * 0.175
    top_r = SIZE * 0.052

    # Soft cast shadow beneath the stone.
    shadow_w = stone_base_r * 1.35
    shadow_h = shadow_w * 0.22
    d.ellipse(
        [cx - shadow_w, base_y - shadow_h * 0.35, cx + shadow_w, base_y + shadow_h * 0.65],
        fill=(*AEGEAN_DARK[:3], 140),
    )

    # Low plinth the stone rests on.
    plinth_w = stone_base_r * 1.55
    plinth_h = SIZE * 0.035
    d.rounded_rectangle(
        [cx - plinth_w, base_y - SIZE * 0.01, cx + plinth_w, base_y + plinth_h],
        radius=plinth_h * 0.5,
        fill=GOLD,
    )

    # Stone body silhouette.
    poly = _dome_polygon(cx, base_y, top_y, stone_base_r, top_r)
    d.polygon(poly, fill=IVORY)
    # Rounded apex cap.
    d.ellipse([cx - top_r, top_y - top_r, cx + top_r, top_y + top_r], fill=IVORY)

    # Build a mask of the stone silhouette so the carved net pattern and
    # shading stay confined to it.
    mask = Image.new("L", (SIZE, SIZE), 0)
    md = ImageDraw.Draw(mask)
    md.polygon(poly, fill=255)
    md.ellipse([cx - top_r, top_y - top_r, cx + top_r, top_y + top_r], fill=255)

    # One-sided shading: darken the right half slightly for volume, confined
    # to the stone silhouette via the mask.
    right_mask = Image.new("L", (SIZE, SIZE), 0)
    rd = ImageDraw.Draw(right_mask)
    rd.rectangle([cx, top_y - SIZE * 0.02, cx + stone_base_r * 1.4, base_y], fill=255)
    shade_mask = Image.composite(right_mask, Image.new("L", (SIZE, SIZE), 0), mask)
    shaded_fill = Image.new("RGBA", (SIZE, SIZE), IVORY_SHADE)
    img.paste(shaded_fill, (0, 0), shade_mask)

    # The agrenon: a knotted diagonal net draped over the stone. Drawn as a
    # crosshatch of gold lines, clipped to the stone's silhouette, with small
    # discs at each intersection to suggest woven knots.
    net_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    nd = ImageDraw.Draw(net_layer)
    spacing = SIZE * 0.052
    lw = max(2, int(SIZE * 0.0055))
    extent = stone_base_r * 1.6
    knots = []
    n_lines = int((2 * extent) / spacing) + 4
    for i in range(-n_lines, n_lines):
        off = i * spacing
        nd.line([(cx - extent, top_y + off), (cx + extent, top_y - extent + off + extent * 2)], fill=GOLD, width=lw)
        nd.line([(cx + extent, top_y + off), (cx - extent, top_y - extent + off + extent * 2)], fill=GOLD, width=lw)

    net_layer.putalpha(Image.composite(net_layer.split()[3], Image.new("L", (SIZE, SIZE), 0), mask))
    img.paste(net_layer, (0, 0), net_layer)

    # Rim highlight along the stone's left edge for a polished, lit look.
    highlight = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    hd = ImageDraw.Draw(highlight)
    left_edge = [pt for pt in poly[: len(poly) // 2]]
    hd.line(left_edge, fill=(255, 255, 255, 90), width=int(SIZE * 0.006), joint="curve")
    img.paste(highlight, (0, 0), highlight)

    return img.resize((1024, 1024), Image.LANCZOS)


def greek_key_strip(width, height, color=GOLD):
    """A simple repeating meander (Greek key) pattern, tileable horizontally."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    unit = height
    n = max(1, width // unit)
    lw = max(2, int(height * 0.14))
    for i in range(n):
        x0 = i * unit
        pts = [
            (x0 + unit * 0.05, height * 0.85),
            (x0 + unit * 0.05, height * 0.15),
            (x0 + unit * 0.55, height * 0.15),
            (x0 + unit * 0.55, height * 0.60),
            (x0 + unit * 0.30, height * 0.60),
            (x0 + unit * 0.30, height * 0.40),
            (x0 + unit * 0.80, height * 0.40),
            (x0 + unit * 0.80, height * 0.85),
        ]
        d.line(pts, fill=color, width=lw, joint="curve")
    return img


def _draw_tracked(d, xy, text, font, fill, tracking):
    x, y = xy
    cursor = x
    for ch in text:
        d.text((cursor, y), ch, font=font, fill=fill)
        cursor += d.textlength(ch, font=font) + tracking
    return cursor - tracking


def make_lockup():
    """Icon + English wordmark + Greek wordmark + Greek-key rule, on parchment."""
    W, H = 2400, 1000
    bg = (250, 247, 240, 255)
    canvas = Image.new("RGBA", (W, H), bg)

    mark = make_mark()
    mark_size = 660
    mark_img = mark.resize((mark_size, mark_size), Image.LANCZOS)
    mark_x, mark_y = 130, (H - mark_size) // 2
    canvas.paste(mark_img, (mark_x, mark_y), mark_img)

    d = ImageDraw.Draw(canvas)
    text_x = mark_x + mark_size + 90

    en_font = ImageFont.truetype(f"{FONT_DIR}/Gloock-Regular.ttf", 210)
    gr_font = ImageFont.truetype(GREEK_FONT, 140)
    tagline_font = ImageFont.truetype(f"{FONT_DIR}/WorkSans-Regular.ttf", 50)

    en_word = "DELPHI"
    bbox = d.textbbox((0, 0), en_word, font=en_font)
    en_h = bbox[3] - bbox[1]
    en_top = H * 0.26 - en_h / 2
    en_y = en_top - bbox[1]
    en_right = _draw_tracked(d, (text_x, en_y), en_word, en_font, AEGEAN, tracking=14)
    en_bottom = en_top + en_h

    gr_word = "ΔΕΛΦΟΙ"  # ΔΕΛΦΟΙ
    gbbox = d.textbbox((0, 0), gr_word, font=gr_font)
    gr_h = gbbox[3] - gbbox[1]
    gr_top = en_bottom + H * 0.055
    gr_y = gr_top - gbbox[1]
    gr_right = _draw_tracked(d, (text_x + 4, gr_y), gr_word, gr_font, GOLD, tracking=20)
    gr_bottom = gr_top + gr_h

    tagline = "S E C O N D   B R A I N"
    tagline_y = gr_bottom + H * 0.09
    d.text((text_x + 6, tagline_y), tagline, font=tagline_font, fill=(120, 110, 90, 255))

    strip_w = max(en_right, gr_right) - text_x
    strip_h = 24
    strip = greek_key_strip(int(strip_w), strip_h)
    canvas.paste(strip, (text_x, int(tagline_y + 80)), strip)

    return canvas


if __name__ == "__main__":
    out_dir = "/tmp/claude-0/-home-user-jarvis-v0-3/94b04910-0f21-516f-8217-f3eb62d40a7a/scratchpad/logo"

    mark = make_mark()
    mark.save(f"{out_dir}/delphi_mark.png")

    lockup = make_lockup()
    lockup.save(f"{out_dir}/delphi_lockup.png")
    print("done")
