from __future__ import annotations

import math
import random
import tempfile

import qrcode
from PIL import Image, ImageDraw, ImageFilter


def _rounded(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None, width: int = 1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _gift_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color=(75, 185, 255, 255), width: int = 6):
    """Small clean gift icon used only as the QR center mark."""
    w = size
    h = int(size * 0.70)
    x0 = cx - w // 2
    y0 = cy - h // 2
    draw.rounded_rectangle((x0, y0 + size // 8, x0 + w, y0 + h), radius=max(6, size // 10), outline=color, width=width)
    draw.line((cx, y0 + size // 8, cx, y0 + h), fill=color, width=width)
    draw.line((x0, y0 + size // 3, x0 + w, y0 + size // 3), fill=color, width=width)
    draw.ellipse((cx - size // 2, y0 - size // 8, cx - 4, y0 + size // 4), outline=color, width=width)
    draw.ellipse((cx + 4, y0 - size // 8, cx + size // 2, y0 + size // 4), outline=color, width=width)


def make_qr_card(
    link: str,
    *,
    title: str = 'VPN BOT',
    subtitle: str = 'VPN',
    username: str = '-',
    plan_title: str = '-',
    volume_gb=None,
    duration_days=None,
    server_name: str = 'Multi Location',
    expire_text: str = '-',
) -> str:
    """
    Create a clean QR delivery card.

    User requested:
    - Keep only the futuristic blue background.
    - Keep only the QR/barcode.
    - Remove all text, service cards, subscription link text, title, status bar, and buttons.
    """
    width, height = 1080, 1350

    # Deep blue futuristic background.
    bg = Image.new('RGB', (width, height), (2, 8, 22))
    px = bg.load()
    for y in range(height):
        for x in range(width):
            dx = (x - width * 0.50) / width
            dy = (y - height * 0.45) / height
            radial = max(0, 1 - math.sqrt(dx * dx * 3.0 + dy * dy * 4.0))
            vertical = 1 - y / height
            blue = int(72 * radial + 32 * vertical)
            px[x, y] = (3 + blue // 10, 12 + blue // 3, 34 + blue)

    bg = bg.convert('RGBA')

    # Soft geometric glow layers.
    overlay = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.polygon([(0, 0), (330, 0), (90, 520), (0, 640)], fill=(20, 140, 255, 30))
    od.polygon([(1080, 0), (820, 0), (1000, 540), (1080, 470)], fill=(0, 180, 255, 24))
    od.polygon([(0, 1050), (330, 900), (1080, 1080), (1080, 1350), (0, 1350)], fill=(0, 90, 210, 34))
    overlay = overlay.filter(ImageFilter.GaussianBlur(5))
    bg = Image.alpha_composite(bg, overlay)

    # Stars and subtle plus marks.
    stars = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stars)
    random.seed(19)
    for _ in range(150):
        x = random.randint(45, width - 45)
        y = random.randint(45, height - 55)
        r = random.choice([1, 1, 1, 2])
        alpha = random.randint(55, 165)
        sd.ellipse((x, y, x + r, y + r), fill=(110, 198, 255, alpha))
    for x, y in [(150, 150), (875, 155), (950, 910), (250, 1120), (175, 600), (805, 570)]:
        sd.line((x - 12, y, x + 12, y), fill=(150, 220, 255, 170), width=2)
        sd.line((x, y - 12, x, y + 12), fill=(150, 220, 255, 170), width=2)
    bg = Image.alpha_composite(bg, stars)

    # Outer neon border only.
    glow = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.rounded_rectangle((40, 32, width - 40, height - 42), radius=62, outline=(45, 160, 255, 225), width=10)
    gd.rounded_rectangle((56, 48, width - 56, height - 58), radius=52, outline=(115, 205, 255, 80), width=2)
    gd.ellipse((250, 430, 830, 1060), fill=(0, 135, 255, 42))
    glow = glow.filter(ImageFilter.GaussianBlur(5))
    bg = Image.alpha_composite(bg, glow)

    # QR code.
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=14, border=2)
    qr.add_data(link or '')
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color=(8, 18, 32), back_color=(255, 255, 255)).convert('RGBA')
    qr_img = qr_img.resize((560, 560), Image.Resampling.NEAREST)

    qx, qy = (width - 640) // 2, (height - 640) // 2

    # QR glow.
    shadow = Image.new('RGBA', (760, 760), (0, 0, 0, 0))
    shd = ImageDraw.Draw(shadow)
    _rounded(shd, (45, 45, 715, 715), 54, fill=(35, 170, 255, 140), outline=None)
    shadow = shadow.filter(ImageFilter.GaussianBlur(30))
    bg.alpha_composite(shadow, (qx - 60, qy - 60))

    # QR white card.
    qr_back = Image.new('RGBA', (640, 640), (0, 0, 0, 0))
    qd = ImageDraw.Draw(qr_back)
    _rounded(qd, (0, 0, 640, 640), 50, fill=(255, 255, 255, 255), outline=(56, 174, 255, 255), width=7)
    qr_back.alpha_composite(qr_img, (40, 40))

    # Center brand mark without extra surrounding text blocks.
    logo_size = 120
    logo = Image.new('RGBA', (logo_size, logo_size), (0, 0, 0, 0))
    ld = ImageDraw.Draw(logo)
    ld.ellipse((0, 0, logo_size, logo_size), fill=(5, 20, 40, 248), outline=(255, 255, 255, 255), width=4)
    _gift_icon(ld, logo_size // 2, logo_size // 2, 58, (65, 190, 255, 255), width=5)
    qr_back.alpha_composite(logo, ((640 - logo_size) // 2, (640 - logo_size) // 2))

    bg.alpha_composite(qr_back, (qx, qy))

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
    tmp.close()
    bg.convert('RGB').save(tmp.name, quality=95)
    return tmp.name
