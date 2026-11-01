"""Printable business card built on the designed template (assets/card/template.png, 1536x1024)."""
import io
import re
from pathlib import Path
from typing import Optional

import qrcode
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ASSETS = Path(__file__).parent / "assets"
TEMPLATE = ASSETS / "card" / "template.png"
NAVY, WHITE = (1, 20, 52), (255, 255, 255)
CODE_NAVY = (14, 27, 58)

# Template regions (pixels on the 1536x1024 template)
NAME_BOX = (180, 110, 850, 270)
QR_BOX = (982, 162, 1488, 640)
CODE_BOX = (58, 795, 434, 873)
PHONE_BOX = (642, 780, 1038, 862)


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / "fonts" / name), size)


def _fit(draw: ImageDraw.ImageDraw, text: str, font: str, max_w: int, max_h: int, size: int) -> ImageFont.FreeTypeFont:
    while size > 20:
        f = _font(font, size)
        l, t, r, b = draw.textbbox((0, 0), text, font=f)
        if r - l <= max_w and b - t <= max_h:
            return f
        size -= 4
    return _font(font, size)


def format_phone(phone: Optional[str]) -> Optional[str]:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("34") and len(digits) == 11:
        digits = digits[2:]
    if len(digits) == 9:
        return f"{digits[:3]} {digits[3:6]} {digits[6:]}"
    return phone.strip() if phone and phone.strip() else None


def _center(box):
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)


def render_business_card(driver_name: str, url: str, code: str, phone: Optional[str] = None,
                         license_number: Optional[str] = None, site: str = "") -> bytes:
    img = Image.open(TEMPLATE).convert("RGB")
    d = ImageDraw.Draw(img)

    # Driver first name only, with soft shadow (replaces "admin")
    name = ((driver_name or "").split() or ["Taxista"])[0]
    f = _fit(d, name, "Poppins-ExtraBoldItalic.ttf", NAME_BOX[2] - NAME_BOX[0], NAME_BOX[3] - NAME_BOX[1], 150)
    cx, cy = _center(NAME_BOX)
    shadow = Image.new("L", img.size, 0)
    ImageDraw.Draw(shadow).text((cx + 6, cy + 8), name, font=f, fill=200, anchor="mm")
    img.paste((0, 0, 0), mask=shadow.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(img)
    d.text((cx, cy), name, font=f, fill=WHITE, anchor="mm")

    # QR
    d.rectangle(QR_BOX, fill=WHITE)
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    side = min(QR_BOX[2] - QR_BOX[0], QR_BOX[3] - QR_BOX[1]) - 10
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB").resize((side, side), Image.NEAREST)
    qx, qy = _center(QR_BOX)
    img.paste(qr_img, (qx - side // 2, qy - side // 2))

    # Client code
    d.rectangle(CODE_BOX, fill=WHITE)
    f = _fit(d, code, "Poppins-ExtraBold.ttf", CODE_BOX[2] - CODE_BOX[0] - 20, CODE_BOX[3] - CODE_BOX[1] - 6, 96)
    d.text(_center(CODE_BOX), code, font=f, fill=CODE_NAVY, anchor="mm")

    # Phone
    d.rectangle(PHONE_BOX, fill=NAVY)
    phone_txt = format_phone(phone) or "Pide tu taxi en la app"
    f = _fit(d, phone_txt, "Poppins-Bold.ttf", PHONE_BOX[2] - PHONE_BOX[0] - 16, PHONE_BOX[3] - PHONE_BOX[1] - 10, 80)
    d.text(_center(PHONE_BOX), phone_txt, font=f, fill=WHITE, anchor="mm")

    buf = io.BytesIO()
    img.save(buf, format="PNG", dpi=(450, 450))
    return buf.getvalue()
