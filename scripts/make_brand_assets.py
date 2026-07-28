"""Generate the brand artwork.

Kept as a script rather than committed-and-forgotten binaries so the artwork can
be regenerated or tweaked without a design tool. Output matches the
home-assistant/brands layout, so the files are ready if the domain is ever
submitted there -- see custom_components/tailscale_helper/brand/.

    uv run --with pillow python scripts/make_brand_assets.py

The mark is a T with a plus: Tailscale, but more. Drawn from rectangles rather
than set in a typeface so it stays crisp at the 48px Home Assistant actually
renders it at, and owes nothing to Tailscale's own marks, which are theirs.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SS = 4  # supersampling factor; everything is drawn big and shrunk down

BG = (16, 22, 31, 255)  # deep slate, sits well on light and dark HA themes
GLYPH = (230, 237, 243, 255)
PLUS = (48, 209, 88, 255)  # the "more", in a connected green
TEXT = (230, 237, 243, 255)

BRAND_DIR = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "tailscale_helper"
    / "brand"
)


def _draw_mark(size: int) -> Image.Image:
    """Draw the T+ mark on a transparent square of the given size."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    def px(value: float) -> float:
        return value * big

    # The T sits slightly left and low, leaving the top-right for the plus.
    bar_w, bar_h = px(0.47), px(0.135)
    bar_x, bar_y = px(0.125), px(0.300)
    stem_w = px(0.150)
    stem_x = bar_x + (bar_w - stem_w) / 2
    stem_bottom = px(0.775)
    radius = px(0.030)

    draw.rounded_rectangle(
        [bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=radius, fill=GLYPH
    )
    draw.rounded_rectangle(
        [stem_x, bar_y, stem_x + stem_w, stem_bottom], radius=radius, fill=GLYPH
    )

    # Plus, tucked into the top-right corner. Kept clear of the bar's right tip
    # -- overlapping reads as a collision rather than a lockup.
    arm = px(0.082)
    reach = px(0.235)
    cx, cy = px(0.775), px(0.235)
    draw.rounded_rectangle(
        [cx - reach / 2, cy - arm / 2, cx + reach / 2, cy + arm / 2],
        radius=arm / 2,
        fill=PLUS,
    )
    draw.rounded_rectangle(
        [cx - arm / 2, cy - reach / 2, cx + arm / 2, cy + reach / 2],
        radius=arm / 2,
        fill=PLUS,
    )

    return img


def make_icon(size: int) -> Image.Image:
    """A rounded square with the mark on it."""
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.22), fill=BG)
    img.alpha_composite(_draw_mark(size))
    return img.resize((size, size), Image.Resampling.LANCZOS)


def _font(px: int) -> ImageFont.FreeTypeFont:
    for path, index in (
        ("/System/Library/Fonts/HelveticaNeue.ttc", 0),
        ("/System/Library/Fonts/Avenir Next.ttc", 0),
    ):
        try:
            return ImageFont.truetype(path, px, index=index)
        except (OSError, ValueError):
            continue
    raise RuntimeError("no usable font found for the wordmark")


def make_logo(height: int) -> Image.Image:
    """Horizontal lockup: the mark beside the name, on its own card.

    The card matters -- a transparent lockup with light text vanishes against a
    light README, and dark text vanishes against a dark one. Carrying its own
    background is the only version that reads everywhere.
    """
    big_h = height * SS
    pad = int(big_h * 0.16)
    mark = int(big_h - pad * 2)

    font = _font(int(mark * 0.40))
    text = "Tailscale Helper"

    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_w = int(probe.textlength(text, font=font))
    gap = int(mark * 0.30)
    big_w = pad + mark + gap + text_w + pad

    img = Image.new("RGBA", (big_w, big_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [0, 0, big_w - 1, big_h - 1], radius=int(big_h * 0.18), fill=BG
    )

    # _draw_mark supersamples internally, so it must be given the final pixel
    # size, not the already-supersampled one.
    img.alpha_composite(_draw_mark(mark // SS), (pad, pad))
    draw.text((pad + mark + gap, big_h // 2), text, font=font, fill=TEXT, anchor="lm")

    return img.resize((big_w // SS, height), Image.Resampling.LANCZOS)


def main() -> None:
    """Write the four brand files."""
    BRAND_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "icon.png": make_icon(256),
        "icon@2x.png": make_icon(512),
        "logo.png": make_logo(128),
        "logo@2x.png": make_logo(256),
    }
    for name, image in outputs.items():
        path = BRAND_DIR / name
        image.save(path)
        print(f"{path.relative_to(BRAND_DIR.parents[2])}  {image.width}x{image.height}")


if __name__ == "__main__":
    main()
