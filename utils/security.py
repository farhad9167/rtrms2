import io
import json
import math
import os
import time
import hmac
import hashlib
import secrets
import zipfile
from datetime import datetime

from PIL import Image
import qrcode


# ---------- QR time-limited token ----------
# A lightweight signed token (not a full JWT lib, to keep dependencies minimal):
# payload = "<slug>:<table>:<issued_at>", signed with the app's secret key.

def make_qr_token(secret_key, slug, table_no):
    issued_at = int(time.time())
    payload = f"{slug}:{table_no}:{issued_at}"
    sig = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{issued_at}.{sig}"


def verify_qr_token(secret_key, slug, table_no, token, expiry_minutes):
    try:
        issued_at_str, sig = token.split(".", 1)
        issued_at = int(issued_at_str)
    except (ValueError, AttributeError):
        return False

    payload = f"{slug}:{table_no}:{issued_at}"
    expected_sig = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(sig, expected_sig):
        return False

    age_seconds = time.time() - issued_at
    return 0 <= age_seconds <= expiry_minutes * 60


# ---------- GPS radius check ----------

def distance_meters(lat1, lng1, lat2, lng2):
    """Haversine formula."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def within_radius(restaurant, customer_lat, customer_lng):
    if not restaurant.gps_lat or not restaurant.gps_lng:
        return True  # owner hasn't set a location yet -> don't block anyone
    d = distance_meters(restaurant.gps_lat, restaurant.gps_lng, customer_lat, customer_lng)
    return d <= (restaurant.gps_radius_m or 30)


# ---------- Image handling: keep HD original, serve an optimized copy ----------

def save_optimized_image(file_storage, hd_folder, web_folder, base_filename):
    """
    Saves the uploaded file as-is (full HD/original) into hd_folder, and a
    resized/compressed copy (max width 900px, JPEG quality 80) into web_folder.
    Returns (web_filename, hd_filename).
    """
    hd_path = os.path.join(hd_folder, base_filename)
    file_storage.save(hd_path)

    web_filename = base_filename
    web_path = os.path.join(web_folder, web_filename)
    try:
        img = Image.open(hd_path).convert("RGB")
        if img.width > 900:
            ratio = 900 / img.width
            img = img.resize((900, int(img.height * ratio)))
        img.save(web_path, "JPEG", quality=80, optimize=True)
    except Exception:
        import shutil
        shutil.copyfile(hd_path, web_path)

    return web_filename, base_filename


# ---------- QR code image generation for tables ----------

def generate_table_qr(public_url, slug, table_no, qr_folder):
    url = f"{public_url}/r/{slug}/menu?table={table_no}"
    img = qrcode.make(url)
    filename = f"{slug}_table{table_no}.png"
    img.save(os.path.join(qr_folder, filename))
    return filename


def generate_single_table_qr(public_url, slug, table_label, qr_folder):
    """
    Table labels are free text in any language (e.g. 'Table 7', '테이블 7'),
    so the saved filename uses a random token instead of the label itself
    (keeps it filesystem-safe on any OS/encoding).
    """
    from urllib.parse import quote
    url = f"{public_url}/r/{slug}/menu?table={quote(table_label)}"
    img = qrcode.make(url)
    filename = f"{slug}_{secrets.token_hex(6)}.png"
    img.save(os.path.join(qr_folder, filename))
    return filename


# ---------- Central-server backup export ----------

def export_restaurant_backup(restaurant, categories, items, orders, backup_folder):
    """
    Bundles a restaurant's data into a timestamped zip file.
    In production this file would then be uploaded/synced to the central
    server (e.g. via a scheduled POST to a /api/backup endpoint, or an
    rsync/rclone job) — that transport step depends on where the central
    server ends up being hosted, so it's left as a clearly-marked hook below.
    """
    data = {
        "restaurant": {"id": restaurant.id, "name": restaurant.name, "slug": restaurant.slug},
        "categories": [{"id": c.id, "name_primary": c.name_primary, "name_secondary": c.name_secondary} for c in categories],
        "items": [{"id": i.id, "name_primary": i.name_primary, "price": i.price} for i in items],
        "orders": [{"id": o.id, "total_price": o.total_price, "status": o.status,
                     "created_at": o.created_at.isoformat()} for o in orders],
        "exported_at": datetime.utcnow().isoformat(),
    }

    os.makedirs(backup_folder, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    zip_path = os.path.join(backup_folder, f"{restaurant.slug}_{ts}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("backup.json", json.dumps(data, indent=2))

    # --- HOOK: send zip_path to the central server here once it's deployed ---
    # e.g. requests.post(f"{CENTRAL_SERVER_URL}/api/backup/{restaurant.slug}",
    #                     files={"file": open(zip_path, "rb")},
    #                     headers={"Authorization": f"Bearer {RESTAURANT_API_KEY}"})

    return zip_path
