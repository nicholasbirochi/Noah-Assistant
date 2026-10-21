"""One-off script: renders Noah's app icon -- the little bot from the native
app's face (`apple/Compartilhado/Rosto.swift` and the `noah-coucou.html`
prototype): a rounded white cube with two black eyes, alone on a black
squircle. Black and white only, minimalist on purpose (in the spirit of the
monochrome AI-app icons) without copying anyone's logo.

It writes every size both apps need, using only AppKit (PyObjC) and
`iconutil`, both built into macOS:

- `src/assets/AppIcon.icns` for the Python Noah.app (py2app), via an
  .iconset in `src/build/`;
- the PNGs of `apple/App/Assets.xcassets/AppIcon.appiconset/` for the
  native iPhone and Mac app.

Every size is a full-bleed opaque square: iOS and macOS 26+ round the
corners themselves. A Mac icon with its own margin and squircle gets put
inside a second, lighter squircle by macOS 26+ (the "background behind the
background" seen in the Dock), so no margin is drawn any more.

Generated once and committed as static assets -- no need to re-render at
build time. Run it again only when the design changes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from AppKit import (  # noqa: E402
    NSApplication,
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSColorSpace,
    NSDeviceRGBColorSpace,
    NSGradient,
    NSGraphicsContext,
    NSMakePoint,
    NSMakeRect,
    NSShadow,
)

NSApplication.sharedApplication()

SRC_DIR = Path(__file__).resolve().parent.parent
ICONSET_DIR = SRC_DIR / "build" / "Noah.iconset"
ICNS_OUTPUT = SRC_DIR / "assets" / "AppIcon.icns"
APPICONSET_DIR = SRC_DIR.parent / "apple" / "App" / "Assets.xcassets" / "AppIcon.appiconset"
# Ícone do Icon Composer usado pelo app nativo do Mac; o icon.json é fixo e
# versionado, aqui só se redesenha a camada.
ICON_COMPOSER_ASSETS = SRC_DIR.parent / "apple" / "IconeMac" / "NoahIcon.icon" / "Assets"

# (filename, pixel size) -- exactly what `iconutil -c icns` expects to find
# inside an .iconset directory.
SIZES = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]

# Names that `AppIcon.appiconset/Contents.json` references for the Mac.
MAC_SIZES = [
    (f"mac-{pt}@{scale}x.png", pt * scale) for pt in (16, 32, 128, 256, 512) for scale in (1, 2)
]


def _rgb(hex_value: int, alpha: float = 1.0) -> NSColor:
    return NSColor.colorWithSRGBRed_green_blue_alpha_(
        ((hex_value >> 16) & 0xFF) / 255, ((hex_value >> 8) & 0xFF) / 255, (hex_value & 0xFF) / 255, alpha
    )


def _gradient(*stops: tuple[int, float, float]) -> NSGradient:
    """Gradient from (hex, alpha, location) stops."""
    return NSGradient.alloc().initWithColors_atLocations_colorSpace_(
        [_rgb(h, a) for h, a, _ in stops], [loc for _, _, loc in stops], NSColorSpace.sRGBColorSpace()
    )


def _rounded(x: float, y: float, w: float, h: float, r: float) -> NSBezierPath:
    return NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(x, y, w, h), r, r)


def _draw_bot(x: float, y: float, b: float) -> None:
    """The bot inside a b x b tile whose bottom-left corner is (x, y).

    AppKit's y axis grows upwards, so "top" means larger y.
    """
    w = b * 0.62  # cube width; height keeps Rosto's 0.86 ratio
    h = w * 0.86
    bx = x + (b - w) / 2
    by = y + (b - h) / 2 - b * 0.01  # optically centred: a hair below the middle
    corner = w * 0.32
    cx = bx + w / 2

    # Soft shadow under the cube.
    NSGraphicsContext.saveGraphicsState()
    shadow = NSShadow.alloc().init()
    shadow.setShadowColor_(_rgb(0x000000, 0.6))
    shadow.setShadowOffset_((0, -b * 0.025))
    shadow.setShadowBlurRadius_(b * 0.05)
    shadow.set()
    body = _rounded(bx, by, w, h, corner)
    _rgb(0xFFFFFF).setFill()
    body.fill()
    NSGraphicsContext.restoreGraphicsState()

    # Body: Rosto's radial gradient, in greys (white near the top-left, grey towards the bottom).
    NSGraphicsContext.saveGraphicsState()
    body.addClip()
    light = NSMakePoint(bx + w * 0.3, by + h * 0.85)
    _gradient((0xFFFFFF, 1, 0.0), (0xF0F0F0, 1, 0.55), (0xC8C8C8, 1, 1.0)).drawFromCenter_radius_toCenter_radius_options_(
        light, 0, light, w * 1.1, 0
    )
    NSGraphicsContext.restoreGraphicsState()
    _rgb(0xFFFFFF, 0.6).setStroke()
    body.setLineWidth_(max(0.5, w * 0.02))
    body.stroke()

    # Eyes: two black capsules, slightly above centre, each with a tiny glint.
    eye_w, eye_h = w * 0.12, w * 0.2
    gap = w * 0.2
    eye_y = by + h / 2 - eye_h / 2 + w * 0.02
    for ex in (cx - gap / 2 - eye_w, cx + gap / 2):
        _rgb(0x0A0A0A).setFill()
        _rounded(ex, eye_y, eye_w, eye_h, eye_w / 2).fill()
        if b >= 64:  # glints are lost (and look like noise) at the tiny sizes
            g = eye_w * 0.36
            _rgb(0xFFFFFF, 0.9).setFill()
            NSBezierPath.bezierPathWithOvalInRect_(
                NSMakeRect(ex + eye_w * 0.5, eye_y + eye_h - g * 1.5, g, g)
            ).fill()


def _draw_background(path: NSBezierPath, x: float, y: float, b: float) -> None:
    """Black tile: a touch lighter at the top, with a faint highlight at the top-left."""
    NSGraphicsContext.saveGraphicsState()
    path.addClip()
    _gradient((0x2B2B2B, 1, 0.0), (0x141414, 1, 0.55), (0x050505, 1, 1.0)).drawInRect_angle_(
        NSMakeRect(x, y, b, b), -90
    )
    glow = NSMakePoint(x + b * 0.28, y + b * 0.9)
    _gradient((0xFFFFFF, 0.08, 0.0), (0xFFFFFF, 0.0, 1.0)).drawFromCenter_radius_toCenter_radius_options_(
        glow, 0, glow, b * 0.7, 0
    )
    NSGraphicsContext.restoreGraphicsState()


def draw_icon(size: int, output_path: Path) -> None:
    """Opaque full-bleed square; the system applies the rounded mask."""
    # AppKit only draws into bitmaps with alpha (a 3-sample one comes out all
    # black), so draw RGBA and flatten afterwards: the icon must be opaque.
    bitmap = _bitmap(size, alpha=True)

    NSGraphicsContext.saveGraphicsState()
    try:
        NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap))
        b = float(size)
        _draw_background(NSBezierPath.bezierPathWithRect_(NSMakeRect(0, 0, size, size)), 0.0, 0.0, b)
        _draw_bot(0.0, 0.0, b)
    finally:
        NSGraphicsContext.restoreGraphicsState()

    png_data = _sem_alfa(bitmap, size).representationUsingType_properties_(NSBitmapImageFileTypePNG, None)
    png_data.writeToFile_atomically_(str(output_path), True)


def _bitmap(size: int, *, alpha: bool) -> NSBitmapImageRep:
    bitmap = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4 if alpha else 3, alpha, False, NSDeviceRGBColorSpace, 0, 0
    )
    bitmap.setSize_((size, size))
    return bitmap


def _sem_alfa(rgba: NSBitmapImageRep, size: int) -> NSBitmapImageRep:
    """Copies an opaque RGBA bitmap into an RGB one (no alpha channel), byte
    by byte. Safe only because the full-bleed tile covers every pixel, so the
    premultiplied colour equals the real one."""
    rgb = _bitmap(size, alpha=False)
    origem, destino = memoryview(rgba.bitmapData()), memoryview(rgb.bitmapData())
    passo_o, passo_d = rgba.bytesPerRow(), rgb.bytesPerRow()
    for linha in range(size):
        o = origem[linha * passo_o : linha * passo_o + size * 4]
        d = bytearray(size * 3)
        for canal in range(3):
            d[canal::3] = o[canal::4]
        destino[linha * passo_d : linha * passo_d + size * 3] = d
    return rgb


def main() -> None:
    ICONSET_DIR.mkdir(parents=True, exist_ok=True)
    for filename, size in SIZES:
        draw_icon(size, ICONSET_DIR / filename)
        print(f"{filename} ({size}px)")

    ICNS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(ICNS_OUTPUT)], check=True)
    print(f"-> {ICNS_OUTPUT}")

    if APPICONSET_DIR.is_dir():
        draw_icon(1024, APPICONSET_DIR / "icone-ios.png")
        for filename, size in MAC_SIZES:
            draw_icon(size, APPICONSET_DIR / filename)
        print(f"-> {APPICONSET_DIR}")

    if ICON_COMPOSER_ASSETS.is_dir():
        draw_icon(1024, ICON_COMPOSER_ASSETS / "noah.png")
        print(f"-> {ICON_COMPOSER_ASSETS.parent}")


if __name__ == "__main__":
    main()
