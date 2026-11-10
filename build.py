import argparse
import math
import os
import re
from pathlib import Path
from types import SimpleNamespace

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables.O_S_2f_2 import Panose
from fontTools.ufoLib import UFOReader

ROOT = Path(__file__).resolve().parent
UFO = ROOT / "sources" / "MK8D-Digital.ufo"
REPO_URL = "https://github.com/otoneko-mk/Font-MK8DNum"

FAMILY = "MK8DNum"
VERSION = "1.900"

UPM = 1000
ASCENDER = 950
DESCENDER = -250
CAP_HEIGHT = 730

PIXEL_SCALE = 10.841154805750266
TIMER_CHARACTER_SPACE_PX = 3
SPACE_WIDTH = 260
ITALIC_ANGLE = 10.0
DEFAULT_EPOCH = 1791763200


def read_glyph(glyphset, name):
    data = SimpleNamespace()
    glyphset.readGlyph(name, glyphObject=data)
    return data


def compile_font(style, output):
    italic = style == "Italic"

    reader = UFOReader(UFO)
    glyphset = reader.getGlyphSet()
    order = reader.readLib()["public.glyphOrder"]

    if not order or order[0] != ".notdef":
        raise ValueError("Invalid glyph order")

    if set(order) != set(glyphset.keys()):
        raise ValueError("Glyph order does not match the UFO source")

    cmap = {}
    metrics = {}
    charstrings = {}

    shear = math.tan(math.radians(ITALIC_ANGLE)) if italic else 0.0
    italic_angle = -ITALIC_ANGLE if italic else 0.0

    for name in order:
        glyph = read_glyph(glyphset, name)

        for cp in getattr(glyph, "unicodes", []):
            if cp in cmap:
                raise ValueError(f"Duplicate Unicode mapping: U+{cp:04X}")
            cmap[cp] = name

        if name == "space":
            advance = SPACE_WIDTH
        elif name == ".notdef":
            advance = round((48 + TIMER_CHARACTER_SPACE_PX) * PIXEL_SCALE)
        else:
            source_px = round(glyph.width / PIXEL_SCALE)
            advance = round(
                (source_px + TIMER_CHARACTER_SPACE_PX) * PIXEL_SCALE
            )

        if advance <= 0:
            raise ValueError(f"Invalid advance for {name}")

        transform = (1, 0, shear, 1, 0, 0)

        pen = T2CharStringPen(advance, glyphset)
        glyphset[name].draw(TransformPen(pen, transform))
        charstrings[name] = pen.getCharString()

        bounds = BoundsPen(glyphset)
        glyphset[name].draw(TransformPen(bounds, transform))

        left_side_bearing = (
            round(bounds.bounds[0]) if bounds.bounds else 0
        )

        metrics[name] = (advance, left_side_bearing)

    tag = os.environ.get("MK8D_BUILD_TAG", "").strip()

    if tag and not re.fullmatch(
        r"\d{4}\.\d{2}\.\d{2}\.\d{2}", tag
    ):
        raise ValueError("MK8D_BUILD_TAG must use yyyy.MM.dd.nn")

    version = "Version " + VERSION

    if tag:
        version += "; build " + tag

    ps_name = f"{FAMILY}-{style}"
    full_name = f"{FAMILY} {style}"

    fb = FontBuilder(UPM, isTTF=False)

    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(
        ascent=ASCENDER,
        descent=DESCENDER,
        lineGap=0,
    )

    fb.setupNameTable({
        "familyName": FAMILY,
        "styleName": style,
        "fullName": full_name,
        "psName": ps_name,
        "typographicFamily": FAMILY,
        "typographicSubfamily": style,
        "uniqueFontIdentifier": ps_name + "; " + version,
        "version": version,
        "vendorURL": REPO_URL,
        "manufacturer": "otoneko-mk",
        "designer": "otoneko-mk",
        "sampleText": "０:２０.２５５ 0123456789",
    })

    panose = Panose()
    panose.bProportion = 0

    fb.setupOS2(
        version=4,
        usWeightClass=400,
        usWidthClass=5,
        xAvgCharWidth=round(
            (48 + TIMER_CHARACTER_SPACE_PX) * PIXEL_SCALE
        ),
        panose=panose,
        achVendID="UNKN",
        fsType=0,
        fsSelection=0x80 | (0x01 if italic else 0x40),
        sTypoAscender=ASCENDER,
        sTypoDescender=DESCENDER,
        sTypoLineGap=0,
        usWinAscent=ASCENDER,
        usWinDescent=-DESCENDER,
        sCapHeight=CAP_HEIGHT,
        sxHeight=0,
        usDefaultChar=0,
        usBreakChar=32,
        usMaxContext=0,
    )

    fb.setupPost(
        keepGlyphNames=True,
        isFixedPitch=0,
        italicAngle=italic_angle,
        underlinePosition=-110,
        underlineThickness=45,
    )

    fb.setupCFF(
        ps_name,
        {
            "FullName": full_name,
            "FamilyName": FAMILY,
            "Weight": style,
            "ItalicAngle": italic_angle,
            "UnderlinePosition": -110,
            "UnderlineThickness": 45,
        },
        charstrings,
        {},
    )

    fb.setupMaxp()

    epoch = int(
        os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH)
    )

    timestamp = epoch + 2082844800

    fb.setupHead(
        fontRevision=float(VERSION),
        macStyle=2 if italic else 0,
        created=timestamp,
        modified=timestamp,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    fb.save(output)

    with TTFont(output) as font:
        assert font.sfntVersion == "OTTO"
        assert font.getGlyphOrder()[0] == ".notdef"
        assert font.getBestCmap() == cmap
        assert font["name"].getDebugName(1) == FAMILY
        assert font["name"].getDebugName(2) == style
        assert font["name"].getDebugName(6) == ps_name
        assert font["name"].getDebugName(5) == version

        assert not any(
            key in font
            for key in ("GSUB", "GPOS", "kern")
        )

        assert bool(
            font["OS/2"].fsSelection & 1
        ) == italic

        digit_width = font["hmtx"].metrics[
            cmap[ord("0")]
        ][0]

        assert all(
            font["hmtx"].metrics[
                cmap[ord(str(i))]
            ][0] == digit_width
            for i in range(10)
        )

    return output


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "build" / "otf",
    )

    args = parser.parse_args()

    for style in ("Regular", "Italic"):
        filename = f"MK8DNum-{style}.otf"
        path = args.output_dir / filename
        compile_font(style, path)
        print("Generated", path)


if __name__ == "__main__":
    main()
