"""Generate multi-resolution Windows icon and Inno Setup wizard bitmaps from Proteus artwork."""

from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
FACE_ART = ROOT / "frontend" / "public" / "art" / "proteus-face.webp"
ALPHA_ART = ROOT / "frontend" / "public" / "art" / "proteus-alpha.png"

COBALT = (38, 65, 230)       # #2641E6
COBALT_DEEP = (18, 33, 148)  # #122194
PAPER = (243, 239, 230)      # #F3EFE6


def _load_engraving_mask(path: Path) -> Image.Image:
    """Convert engraving artwork into an inverted luminance mask (white = ink lines)."""
    img = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    flattened = Image.alpha_composite(bg, img).convert("L")
    # Dark engraving lines become high alpha in the mask; light background becomes transparent.
    return ImageOps.invert(flattened)


def _render_emblem(size: int, art_path: Path) -> Image.Image:
    """Render a square Cobalt badge with crisp Paper engraving artwork."""
    canvas = Image.new("RGBA", (size, size), (*COBALT, 255))
    mask = _load_engraving_mask(art_path)
    pad = max(2, int(size * 0.08))
    target = size - 2 * pad
    mask = mask.resize((target, target), Image.Resampling.LANCZOS)
    ink_layer = Image.new("RGBA", (target, target), (*PAPER, 255))
    ink_layer.putalpha(mask)
    canvas.paste(ink_layer, (pad, pad), ink_layer)
    return canvas


def main() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    art_path = FACE_ART if FACE_ART.is_file() else ALPHA_ART
    if not art_path.is_file():
        raise FileNotFoundError(f"Missing Proteus artwork at {FACE_ART} or {ALPHA_ART}")

    # 1. Multi-resolution proteus.ico
    master = _render_emblem(256, art_path)
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    master.save(ASSETS_DIR / "proteus.ico", format="ICO", sizes=ico_sizes)

    # 2. Inno Setup small header icon (55x58)
    small = Image.new("RGB", (55, 58), COBALT)
    small_emblem = _render_emblem(54, art_path).convert("RGB")
    small.paste(small_emblem, (0, 2))
    small.save(ASSETS_DIR / "wizard_small.bmp", format="BMP")

    # 3. Inno Setup wizard sidebar image (164x314)
    sidebar = Image.new("RGB", (164, 314), COBALT_DEEP)
    hero_art = ALPHA_ART if ALPHA_ART.is_file() else art_path
    mask = _load_engraving_mask(hero_art).resize((164, 164), Image.Resampling.LANCZOS)
    paper_art = Image.new("RGBA", (164, 164), (*PAPER, 255))
    paper_art.putalpha(mask)
    sidebar_rgba = sidebar.convert("RGBA")
    sidebar_rgba.paste(paper_art, (0, 140), paper_art)
    sidebar_rgba.convert("RGB").save(ASSETS_DIR / "wizard_sidebar.bmp", format="BMP")

    print(f"Generated {ASSETS_DIR / 'proteus.ico'}, wizard_sidebar.bmp, wizard_small.bmp")


if __name__ == "__main__":
    main()
