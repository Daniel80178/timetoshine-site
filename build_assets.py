"""
TIMETOSHINE — visual asset builder.

Generates:
  * favicon PNGs at 16/32/180/512 px (logo recreated programmatically)
  * Dynamic Open Graph image (1200x630 PNG) with current stats baked in

Logo recreation: dark circle with gold ring + "T2S" wordmark (matches the SVG aesthetic).
Avoids fragile SVG conversion stack.
"""

from __future__ import annotations
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE          = Path(__file__).resolve().parent

FAVICON_SIZES = [16, 32, 180, 512]   # standard / iOS / Android-PWA
OG_WIDTH      = 1200
OG_HEIGHT     = 630

# Colors lifted directly from the live site palette
PALETTE = {
    "bg":         (10, 14, 20),
    "panel":      (17, 22, 31),
    "panel2":     (22, 28, 39),
    "navy_dark":  (3, 8, 15),
    "navy_mid":   (19, 38, 60),
    "text":       (230, 237, 243),
    "muted":      (139, 155, 176),
    "gold":       (212, 175, 55),
    "gold_soft":  (245, 211, 107),
    "gold_warm":  (229, 168, 42),
    "gold_dark":  (140, 90, 11),
    "green":      (63, 185, 80),
    "blue":       (88, 166, 255),
}


# ---------------------------------------------------------------------
# Font picker (try several Windows fonts; fall back to default)
# ---------------------------------------------------------------------
def _pick_font(size, bold=False):
    bold_paths = [
        r"C:\Windows\Fonts\seguibl.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\calibrib.ttf",
    ]
    reg_paths = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
    ]
    for path in (bold_paths if bold else reg_paths):
        if Path(path).exists():
            try: return ImageFont.truetype(path, size)
            except Exception: continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------
# Logo (recreates the TIMETOSHINE circular crest)
# ---------------------------------------------------------------------
def render_logo(size: int, solid_bg: bool = True) -> Image.Image:
    """Square image with the TIMETOSHINE-style logo.

    solid_bg=True  -> full-bleed dark background (iOS home-screen friendly)
    solid_bg=False -> transparent corners (for OG image composition / browser favicons)
    """
    import math

    if solid_bg:
        img = Image.new("RGBA", (size, size), (*PALETTE["navy_dark"], 255))
    else:
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    cx = cy = size / 2

    # Radial dark navy fill (full bleed when solid_bg)
    if solid_bg:
        max_r = size * 0.75
        for r in range(int(max_r), 0, -2):
            t = r / max_r
            color = (
                int(PALETTE["navy_mid"][0]  * (1 - t) + PALETTE["navy_dark"][0] * t),
                int(PALETTE["navy_mid"][1]  * (1 - t) + PALETTE["navy_dark"][1] * t),
                int(PALETTE["navy_mid"][2]  * (1 - t) + PALETTE["navy_dark"][2] * t),
                255,
            )
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    # Logo elements sized relative to the icon — bigger for solid_bg variant so it reads at home-screen size
    if solid_bg:
        r_outer = size * 0.40
        r_inner = size * 0.32
    else:
        r_outer = size * 0.48
        r_inner = size * 0.40

    # When not solid bg, draw the circular dark disc as the logo backdrop
    if not solid_bg:
        for r in range(int(r_outer), 0, -1):
            t = r / r_outer
            color = (
                int(PALETTE["navy_dark"][0] + (PALETTE["navy_mid"][0] - PALETTE["navy_dark"][0]) * (1 - t)),
                int(PALETTE["navy_dark"][1] + (PALETTE["navy_mid"][1] - PALETTE["navy_dark"][1]) * (1 - t)),
                int(PALETTE["navy_dark"][2] + (PALETTE["navy_mid"][2] - PALETTE["navy_dark"][2]) * (1 - t)),
                255,
            )
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    # Sunburst rays — bigger, more prominent for solid_bg
    ray_r_in  = r_inner * 1.08
    ray_r_out = r_outer * 1.18 if solid_bg else r_outer * 0.86
    ray_count = 12
    ray_color = PALETTE["gold_soft"] if solid_bg else PALETTE["gold_warm"]
    for i in range(ray_count * 2):
        ang = (i * 360 / (ray_count * 2)) * math.pi / 180.0
        if i % 2 == 0:
            x1 = cx + ray_r_in  * math.cos(ang)
            y1 = cy + ray_r_in  * math.sin(ang)
            x2 = cx + ray_r_out * math.cos(ang)
            y2 = cy + ray_r_out * math.sin(ang)
            draw.line([x1, y1, x2, y2], fill=ray_color, width=max(2, int(size * 0.012)))

    # Gold outer ring
    ring_w = max(3, int(size * 0.026))
    draw.ellipse(
        [cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
        outline=PALETTE["gold"], width=ring_w
    )

    # Inner gold accent ring (small)
    inner_ring_w = max(2, int(size * 0.015))
    draw.ellipse(
        [cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
        outline=PALETTE["gold_warm"], width=inner_ring_w
    )

    # Inner darker disc inside the inner ring
    inner_fill_r = r_inner - inner_ring_w
    draw.ellipse(
        [cx - inner_fill_r, cy - inner_fill_r, cx + inner_fill_r, cy + inner_fill_r],
        fill=PALETTE["navy_mid"]
    )

    # Wordmark "T2S" in the center — bigger and bolder for home screen
    if size >= 24:
        text_size = int(size * 0.34) if solid_bg else int(size * 0.30)
        font = _pick_font(text_size, bold=True)
        text = "T2S"
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = cx - tw / 2 - bbox[0]
        ty = cy - th / 2 - bbox[1] - size * 0.01
        # shadow + main gold text
        draw.text((tx + 2, ty + 2), text, font=font, fill=(0, 0, 0, 200))
        draw.text((tx, ty),         text, font=font, fill=PALETTE["gold_soft"])

    return img


# ---------------------------------------------------------------------
# Favicons
# ---------------------------------------------------------------------
def build_favicons():
    # Solid-bg version: PWA + iOS home screen icons (needs to look like a real app icon)
    solid_master = render_logo(512, solid_bg=True)
    solid_master.save(HERE / "icon-512.png", "PNG", optimize=True)
    print(f"  -> icon-512.png  (512x512, solid bg)")
    apple = solid_master.resize((180, 180), Image.LANCZOS)
    apple.save(HERE / "apple-touch-icon.png", "PNG", optimize=True)
    print(f"  -> apple-touch-icon.png  (180x180, solid bg)")

    # Transparent-bg version: small browser favicons (sit nicely in any browser tab background)
    trans_master = render_logo(256, solid_bg=False)
    for size in (16, 32):
        img = trans_master.resize((size, size), Image.LANCZOS)
        img.save(HERE / f"favicon-{size}x{size}.png", "PNG", optimize=True)
        print(f"  -> favicon-{size}x{size}.png  (transparent bg)")


# ---------------------------------------------------------------------
# Open Graph image (1200x630)
# ---------------------------------------------------------------------
def build_og_image(stats: dict | None = None, out_name: str = "og-image.png"):
    """Render a branded 1200x630 OG PNG with logo + key stats overlay."""
    stats = stats or {}

    img  = Image.new("RGB", (OG_WIDTH, OG_HEIGHT), PALETTE["bg"])
    draw = ImageDraw.Draw(img, "RGBA")

    # Radial gold glow upper-right
    for r in range(520, 60, -20):
        a = int(60 * (1 - (r - 60) / 460))
        draw.ellipse(
            [OG_WIDTH - r - 80, -r // 2, OG_WIDTH - 80 + r, r],
            fill=(*PALETTE["gold"], max(0, a))
        )
    # Bottom-left blue glow
    for r in range(420, 60, -20):
        a = int(36 * (1 - (r - 60) / 360))
        draw.ellipse(
            [-r // 2, OG_HEIGHT - r, r, OG_HEIGHT + r // 2],
            fill=(*PALETTE["blue"], max(0, a))
        )

    # Thin gold accent at top
    draw.rectangle([0, 0, OG_WIDTH, 5], fill=PALETTE["gold"])

    # Logo (left side) — transparent bg so the gold ring blends with OG bg
    logo = render_logo(260, solid_bg=False)
    img.paste(logo, (75, 185), logo)

    # Wordmark
    wm_font   = _pick_font(56, bold=True)
    draw.text((365, 200), "TIMETOSHINE", font=wm_font, fill=PALETTE["gold"])

    # Tagline
    tag_font  = _pick_font(22, bold=False)
    draw.text((365, 268), "Disciplined Gold Trading  ·  Verified Track Record",
              font=tag_font, fill=PALETTE["muted"])

    # === Stats panel ===
    big_num   = stats.get("total-return", "+101.5%")
    win_rate  = stats.get("win-rate",     "79.6%")
    pf        = stats.get("profit-factor","4.00")
    since_lbl = stats.get("since-label",  "Since Jun 1, 2026")

    # "TOTAL GROWTH" label
    lbl_font  = _pick_font(20, bold=True)
    draw.text((365, 358), "TOTAL GROWTH", font=lbl_font, fill=PALETTE["muted"])

    # Big number
    bn_font   = _pick_font(110, bold=True)
    draw.text((365, 388), big_num, font=bn_font, fill=PALETTE["gold"])

    # Right side stats stack
    val_font   = _pick_font(40, bold=True)
    rx         = 870
    stat_rows  = [("WIN RATE", win_rate), ("PROFIT FACTOR", pf)]
    for i, (label, value) in enumerate(stat_rows):
        y = 388 + i * 78
        draw.text((rx, y),      label, font=lbl_font, fill=PALETTE["muted"])
        draw.text((rx, y + 22), value, font=val_font, fill=PALETTE["text"])

    # Footer line
    footer_font = _pick_font(18, bold=False)
    draw.text((365, 540), f"{since_lbl}   ·   timetoshineofficial.com",
              font=footer_font, fill=PALETTE["muted"])

    out = HERE / out_name
    img.save(out, "PNG", optimize=True)
    print(f"  -> {out.name}  ({OG_WIDTH}x{OG_HEIGHT})")
    return out


def main():
    print("Building TIMETOSHINE visual assets...\n")
    print("Favicons:")
    build_favicons()
    print("\nOG image:")
    build_og_image()
    print("\nDone.")


if __name__ == "__main__":
    main()
