import argparse
import math
import os
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
UFO = ROOT / "sources" / "MK8DNum.ufo"

VERSION = "1.0.0"

MAJOR, MINOR, PATCH = map(int, VERSION.split("."))

if not (0 <= MINOR <= 99 and 0 <= PATCH <= 99):
    raise ValueError("Minor and patch versions must be between 0 and 99")

FONT_REVISION = MAJOR + MINOR / 100 + PATCH / 10000

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

    info = SimpleNamespace()
    reader.readInfo(info)

    family = info.familyName
    upm = info.unitsPerEm
    ascender = info.ascender
    descender = info.descender
    cap_height = info.capHeight
    weight = info.openTypeOS2WeightClass
    width = info.openTypeOS2WidthClass
    vendor_id = info.openTypeOS2VendorID
    underline_position = info.postscriptUnderlinePosition
    underline_thickness = info.postscriptUnderlineThickness

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
            advance = round((source_px + TIMER_CHARACTER_SPACE_PX) * PIXEL_SCALE)

        if advance <= 0:
            raise ValueError(f"Invalid advance for {name}")

        transform = (1, 0, shear, 1, 0, 0)

        pen = T2CharStringPen(advance, glyphset)
        glyphset[name].draw(TransformPen(pen, transform))
        charstrings[name] = pen.getCharString()

        bounds = BoundsPen(glyphset)
        glyphset[name].draw(TransformPen(bounds, transform))

        left_side_bearing = round(bounds.bounds[0]) if bounds.bounds else 0

        metrics[name] = (advance, left_side_bearing)

    version = f"Version {FONT_REVISION:.4f}; release v{VERSION}"

    ps_name = f"{family}-{style}"
    full_name = f"{family} {style}"

    fb = FontBuilder(upm, isTTF=False)

    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupHorizontalMetrics(metrics)

    fb.setupHorizontalHeader(
        ascent=ascender,
        descent=descender,
        lineGap=0,
    )

    fb.setupNameTable(
        {
            "familyName": family,
            "styleName": style,
            "fullName": full_name,
            "psName": ps_name,
            "typographicFamily": family,
            "typographicSubfamily": style,
            "uniqueFontIdentifier": ps_name + "; " + version,
            "version": version,
            "vendorURL": info.openTypeNameManufacturerURL,
            "manufacturer": info.openTypeNameManufacturer,
            "designer": info.openTypeNameDesigner,
            "sampleText": info.openTypeNameSampleText,
        }
    )

    panose = Panose()
    panose.bProportion = 0

    fb.setupOS2(
        version=4,
        usWeightClass=weight,
        usWidthClass=width,
        xAvgCharWidth=round((48 + TIMER_CHARACTER_SPACE_PX) * PIXEL_SCALE),
        panose=panose,
        achVendID=vendor_id,
        fsType=0,
        fsSelection=0x80 | (0x01 if italic else 0x40),
        sTypoAscender=ascender,
        sTypoDescender=descender,
        sTypoLineGap=0,
        usWinAscent=ascender,
        usWinDescent=-descender,
        sCapHeight=cap_height,
        sxHeight=0,
        usDefaultChar=0,
        usBreakChar=32,
        usMaxContext=0,
    )

    fb.setupPost(
        keepGlyphNames=True,
        isFixedPitch=0,
        italicAngle=italic_angle,
        underlinePosition=underline_position,
        underlineThickness=underline_thickness,
    )

    fb.setupCFF(
        ps_name,
        {
            "FullName": full_name,
            "FamilyName": family,
            "Weight": style,
            "ItalicAngle": italic_angle,
            "UnderlinePosition": underline_position,
            "UnderlineThickness": underline_thickness,
        },
        charstrings,
        {},
    )

    fb.setupMaxp()

    epoch = int(os.environ.get("SOURCE_DATE_EPOCH", DEFAULT_EPOCH))

    timestamp = epoch + 2082844800

    fb.setupHead(
        fontRevision=FONT_REVISION,
        macStyle=2 if italic else 0,
        created=timestamp,
        modified=timestamp,
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fb.save(output)

    with TTFont(output) as font:
        assert font.sfntVersion == "OTTO"
        assert font.getGlyphOrder()[0] == ".notdef"
        assert font.getBestCmap() == cmap

        assert font["name"].getDebugName(1) == family
        assert font["name"].getDebugName(2) == style
        assert font["name"].getDebugName(6) == ps_name
        assert font["name"].getDebugName(5) == version

        assert font["OS/2"].usWeightClass == weight
        assert font["OS/2"].usWidthClass == width
        assert font["head"].unitsPerEm == upm

        assert not any(key in font for key in ("GSUB", "GPOS", "kern"))

        assert bool(font["OS/2"].fsSelection & 1) == italic

        digit_width = font["hmtx"].metrics[cmap[ord("0")]][0]

        assert all(
            font["hmtx"].metrics[cmap[ord(str(i))]][0] == digit_width for i in range(10)
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
