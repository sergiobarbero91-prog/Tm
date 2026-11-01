"""Printable business card (85x55 mm @ 300 dpi) with the driver's fixed QR + client code."""
import io
from pathlib import Path
from typing import Optional

import qrcode
from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).parent / "assets" / "fonts"
W, H = 1004, 650  # 85 x 55 mm at 300 dpi
NAVY, AMBER, WHITE, MUTED = (15, 23, 42), (245, 158, 11), (241, 245, 249), (148, 163, 184)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf")), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, max_w: int, size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    while size > 18 and draw.textlength(text, font=_font(size, bold)) > max_w:
        size -= 2
    return _font(size, bold)


def render_business_card(driver_name: str, url: str, code: str, phone: Optional[str] = None,
                         license_number: Optional[str] = None, site: str = "") -> bytes:
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 14, H], fill=AMBER)

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((380, 380), Image.NEAREST)
    qx, qy = W - 380 - 50, 60
    d.rounded_rectangle([qx - 14, qy - 14, qx + 394, qy + 394], radius=22, fill=WHITE)
    img.paste(qr_img, (qx, qy))
    d.text((qx + 190, qy + 412), "Escanéame", font=_font(26, True), fill=AMBER, anchor="ma")

    x, max_w = 60, qx - 60 - 50
    d.text((x, 58), "TAXI", font=_font(30, True), fill=AMBER)
    d.text((x, 100), driver_name, font=_fit(d, driver_name, max_w, 54), fill=WHITE)
    y = 178
    for line in filter(None, [f"Tel. {phone}" if phone else None, f"Licencia {license_number}" if license_number else None]):
        d.text((x, y), line, font=_font(28), fill=MUTED)
        y += 40

    d.text((x, 300), "Pide tu taxi conmigo:", font=_font(28, True), fill=WHITE)
    d.text((x, 342), "1. Escanea el QR", font=_font(26), fill=MUTED)
    d.text((x, 378), "2. Introduce este código", font=_font(26), fill=MUTED)

    d.rounded_rectangle([x, 430, x + max_w, 540], radius=18, fill=AMBER)
    d.text((x + max_w // 2, 485), " ".join(code), font=_fit(d, " ".join(code), max_w - 30, 64), fill=NAVY, anchor="mm")
    if site:
        d.text((x, 578), site, font=_font(22), fill=MUTED)

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(300, 300))
    return buf.getvalue()
