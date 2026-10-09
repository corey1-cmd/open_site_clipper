"""웹 화면 아이콘(PNG)을 만든다 — 개발 때 한 번만 돌리면 된다(Pillow 필요).

남색 바탕에 인주색 도장, 가운데 '공' 한 글자. 화면의 '수집완료' 도장과 같은 모양이다.
    python scripts/make_icons.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent.parent / "public"
FONT = "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"  # 인덱스 1 = KR
INK, SEAL, PAPER = (24, 32, 46), (194, 39, 45), (255, 255, 255)


def icon(size: int, *, maskable: bool) -> Image.Image:
    scale = 4  # 크게 그려 줄이면 가장자리가 매끈하다
    s = size * scale
    img = Image.new("RGB", (s, s), INK)
    d = ImageDraw.Draw(img)
    # 마스커블 아이콘은 가장자리 20%가 잘릴 수 있다 — 도장을 안쪽 안전 영역에 둔다.
    r = s * (0.30 if maskable else 0.40)
    c = s / 2
    d.ellipse((c - r, c - r, c + r, c + r), fill=SEAL)
    ring = r * 0.86
    d.ellipse((c - ring, c - ring, c + ring, c + ring), outline=PAPER, width=max(2, int(r * 0.05)))
    font = ImageFont.truetype(FONT, int(r * 1.05), index=1)
    glyph = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glyph)
    gd.text((c, c), "공", font=font, fill=PAPER, anchor="mm")
    glyph = glyph.rotate(9, resample=Image.BICUBIC, center=(c, c))  # 도장은 살짝 기울게 찍힌다
    img.paste(glyph, (0, 0), glyph)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    icon(180, maskable=False).save(OUT / "icon-180.png", optimize=True)
    icon(192, maskable=False).save(OUT / "icon-192.png", optimize=True)
    icon(512, maskable=False).save(OUT / "icon-512.png", optimize=True)
    icon(512, maskable=True).save(OUT / "icon-maskable-512.png", optimize=True)
    print("아이콘을 만들었습니다:", ", ".join(p.name for p in sorted(OUT.glob("icon-*.png"))))
