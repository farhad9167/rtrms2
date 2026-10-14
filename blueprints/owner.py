import os
import re
import json
from datetime import datetime, date, timedelta
import pandas as pd
from flask import (Blueprint, render_template, request, redirect, url_for,
                    session, current_app, jsonify, send_file)
from werkzeug.utils import secure_filename
from models import (db, Restaurant, CountryConfig, MenuCategory, MenuItem,
                     DailyOffer, Order, PaymentRequest, PlatformSettings,
                     StaffUser, PromoCode, PlatformReview, PortionTier, StaffCall)
from utils.printer import send_to_printer, generate_receipt
from utils.security import generate_table_qr, generate_single_table_qr, save_optimized_image, export_restaurant_backup
from utils.reports import generate_sales_report_pdf
from utils.features import is_feature_enabled
from utils.admin_translations import get_admin_text
from utils.palette import COLOR_PALETTE
from oauth import oauth

owner_bp = Blueprint("owner", __name__)


@owner_bp.context_processor
def inject_demo_video():
    row = PlatformSettings.query.get("demo_video_url")
    return {"demo_video_url": row.value if row else None}


def current_restaurant():
    rid = session.get("owner_restaurant_id") or session.get("staff_restaurant_id")
    if not rid:
        return None
    return Restaurant.query.get(rid)


def is_full_access():
    """True only for the Google-authenticated owner. False for the shared
    staff login, which is limited to day-to-day operations (orders, payment,
    printing) — not settings, menu editing, staff management, or billing."""
    return bool(session.get("owner_restaurant_id"))


def require_full_access():
    """Call at the top of an owner-only route. Returns a redirect if the
    current session is staff-only; returns None if access is fine."""
    if not current_restaurant():
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    return None


def slugify(name):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "restaurant"
    slug = base
    n = 1
    while Restaurant.query.filter_by(slug=slug).first():
        n += 1
        slug = f"{base}-{n}"
    return slug


def atext_for(restaurant):
    return get_admin_text(restaurant.country_code, restaurant.panel_language)


# ---------- Login (Google or Username) ----------

@owner_bp.route("/login")
def login():
    """Chooser page — owners can sign in with Google or with a username/password
    they've set up. Both lead to the same dashboard."""
    return render_template("owner/login_choice.html")


@owner_bp.route("/login/google")
def login_google():
    redirect_uri = url_for("owner.auth_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@owner_bp.route("/login/username", methods=["GET", "POST"])
def login_username():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        restaurant = Restaurant.query.filter_by(username=username).first() if username else None
        if restaurant and restaurant.check_username_password(password):
            session["owner_restaurant_id"] = restaurant.id
            return redirect(url_for("owner.dashboard"))
        error = "Incorrect username or password."
    return render_template("owner/login_username.html", error=error)


@owner_bp.route("/reset_password_request")
def reset_password_request():
    """'Forgot password?' entry point — re-verifies identity via Google,
    then lets the owner set a brand-new device password (no need to know
    the old one, since Google itself is the identity check)."""
    session["password_reset_mode"] = True
    redirect_uri = url_for("owner.auth_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@owner_bp.route("/auth/callback")
def auth_callback():
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.google.parse_id_token(token)
    google_id = userinfo["sub"]
    email = userinfo["email"]

    restaurant = Restaurant.query.filter_by(google_id=google_id).first()
    if not restaurant:
        session["pending_google_id"] = google_id
        session["pending_email"] = email
        # IP-based country auto-detect happens client-side on the onboarding page
        # (see templates/owner/onboarding.html) so it degrades gracefully offline.
        return redirect(url_for("owner.onboarding"))

    if session.pop("password_reset_mode", False):
        # Google re-confirmed this is really the account owner — let them set
        # a fresh password directly, skipping the "enter old password" check.
        session["pending_verify_restaurant_id"] = restaurant.id
        return redirect(url_for("owner.set_password"))

    # Google identity confirmed, but a device-level password is still required
    # before the dashboard opens — this protects the account if the phone/PC's
    # browser is already signed into the owner's Google account (e.g. a shared
    # or unlocked device), since Google itself won't re-prompt in that case.
    session["pending_verify_restaurant_id"] = restaurant.id
    if not restaurant.owner_password_hash:
        # First time this account reaches this step (e.g. upgraded from an
        # older version) — make them set a password now, once.
        return redirect(url_for("owner.set_password"))
    return redirect(url_for("owner.verify_password"))


@owner_bp.route("/verify_password", methods=["GET", "POST"])
def verify_password():
    rid = session.get("pending_verify_restaurant_id")
    if not rid:
        return redirect(url_for("owner.login"))
    restaurant = Restaurant.query.get(rid)
    if not restaurant:
        session.pop("pending_verify_restaurant_id", None)
        return redirect(url_for("owner.login"))

    error = None
    if request.method == "POST":
        if restaurant.check_owner_password(request.form.get("password", "")):
            session.pop("pending_verify_restaurant_id", None)
            session["owner_restaurant_id"] = restaurant.id
            return redirect(url_for("owner.dashboard"))
        error = "Incorrect password."

    return render_template("owner/verify_password.html", restaurant=restaurant, error=error)


@owner_bp.route("/set_password", methods=["GET", "POST"])
def set_password():
    """Used once, right after Google auth: either for a brand-new signup
    (before onboarding continues) or the first time an existing account
    reaches this step and has no password yet."""
    rid = session.get("pending_verify_restaurant_id")
    new_signup = "pending_google_id" in session and not rid

    if not rid and not new_signup:
        return redirect(url_for("owner.login"))

    if request.method == "POST":
        pw = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if len(pw) < 6:
            return render_template("owner/set_password.html", error="Password must be at least 6 characters.")
        if pw != confirm:
            return render_template("owner/set_password.html", error="Passwords do not match.")

        if new_signup:
            # Stash it in session; onboarding() applies it once the restaurant row exists.
            session["pending_owner_password"] = pw
            return redirect(url_for("owner.onboarding"))
        else:
            restaurant = Restaurant.query.get(rid)
            restaurant.set_owner_password(pw)
            db.session.commit()
            session.pop("pending_verify_restaurant_id", None)
            session["owner_restaurant_id"] = restaurant.id
            return redirect(url_for("owner.dashboard"))

    return render_template("owner/set_password.html", error=None)


@owner_bp.route("/onboarding", methods=["GET", "POST"])
def onboarding():
    if "pending_google_id" not in session:
        return redirect(url_for("owner.login"))
    if "pending_owner_password" not in session:
        # Force the password step first so it can never be skipped.
        return redirect(url_for("owner.set_password"))

    countries = CountryConfig.query.order_by(CountryConfig.name).all()
    lock_active = is_feature_enabled("country_autolock", restaurant=None)

    if request.method == "POST":
        name = request.form["restaurant_name"]
        country_code = request.form["country_code"]
        restaurant = Restaurant(
            name=name,
            slug=slugify(name),
            country_code=country_code,
            country_locked=lock_active,
            owner_email=session["pending_email"],
            google_id=session["pending_google_id"],
            subscription_status="pending_payment",
            referral_code=Restaurant.new_referral_code(),
            referred_by_code=request.form.get("referral_code") or None,
            address=request.form.get("address", ""),
            panel_language=request.form.get("panel_language", "en"),
        )
        restaurant.set_admin_password("changeme")
        restaurant.set_owner_password(session["pending_owner_password"])
        db.session.add(restaurant)
        db.session.commit()

        session.pop("pending_google_id", None)
        session.pop("pending_email", None)
        session.pop("pending_owner_password", None)
        session["owner_restaurant_id"] = restaurant.id
        return redirect(url_for("owner.subscription"))

    return render_template("owner/onboarding.html", countries=countries, lock_active=lock_active)


@owner_bp.route("/logout")
def logout():
    session.pop("owner_restaurant_id", None)
    session.pop("staff_restaurant_id", None)
    return redirect(url_for("owner.login"))


# ---------- Shared staff login (limited access, usable on many devices at once) ----------

@owner_bp.route("/staff_login/<slug>", methods=["GET", "POST"])
def staff_login(slug):
    restaurant = Restaurant.query.filter_by(slug=slug).first_or_404()
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == restaurant.admin_username and restaurant.admin_password_hash and restaurant.check_admin_password(password):
            session["staff_restaurant_id"] = restaurant.id
            return redirect(url_for("owner.dashboard"))
        error = "Incorrect username or password."
    return render_template("owner/staff_login.html", restaurant=restaurant, error=error)


# ---------- Subscription / payment ----------

def _apply_promo(code, months, country_code):
    if not code:
        return 0
    promo = PromoCode.query.filter_by(code=code.strip().upper(), active=True).first()
    if not promo:
        return 0
    if promo.country_code and promo.country_code != country_code:
        return 0
    if promo.expires_at and promo.expires_at < datetime.utcnow():
        return 0
    if months < promo.min_months:
        return 0
    return promo.discount_percent


@owner_bp.route("/subscription", methods=["GET", "POST"])
def subscription():
    restaurant = current_restaurant()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))

    country = CountryConfig.query.get(restaurant.country_code)
    bank_image = PlatformSettings.query.get("bank_details_image")
    bank_text = PlatformSettings.query.get("bank_details_text")
    atext = atext_for(restaurant)

    # Show the next 12 calendar months by name (starting after the current
    # expiry if still active, otherwise starting this month) purely as a
    # friendlier label — the amount is always fee × however many boxes are
    # checked, never tied to which specific month number was clicked.
    base = restaurant.subscription_expiry if (
        restaurant.subscription_expiry and restaurant.subscription_expiry >= date.today()
    ) else date.today().replace(day=1)
    month_options = []
    y, m = base.year, base.month
    for i in range(12):
        month_options.append((i + 1, date(y, m, 1).strftime("%B %Y")))
        m += 1
        if m > 12:
            m = 1
            y += 1

    if request.method == "POST":
        months = max(1, len(request.form.getlist("selected_months")))
        promo_code = request.form.get("promo_code", "").strip()
        discount_pct = _apply_promo(promo_code, months, restaurant.country_code)
        amount = country.monthly_fee * months * (1 - discount_pct / 100)

        pr = PaymentRequest(
            restaurant_id=restaurant.id,
            sender_name=request.form["sender_name"],
            sender_number=request.form["sender_number"],
            transaction_note=request.form.get("note", ""),
            months=months,
            promo_code=promo_code or None,
            amount_quoted=amount,
        )
        db.session.add(pr)
        db.session.commit()
        return render_template("owner/subscription.html", restaurant=restaurant, country=country,
                                bank_image=bank_image, bank_text=bank_text, submitted=True, atext=atext,
                                month_options=month_options)

    return render_template("owner/subscription.html", restaurant=restaurant, country=country,
                            bank_image=bank_image, bank_text=bank_text, submitted=False, atext=atext,
                            month_options=month_options)


# ---------- Dashboard ----------

def require_active_login():
    restaurant = current_restaurant()
    if not restaurant:
        return None
    return restaurant


@owner_bp.route("/dashboard")
def dashboard():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not restaurant.is_active():
        return redirect(url_for("owner.subscription"))

    orders = Order.query.filter_by(restaurant_id=restaurant.id).order_by(Order.id.desc()).limit(100).all()
    for o in orders:
        try:
            o.food_list = json.loads(o.items)
        except Exception:
            o.food_list = []

    days_left = restaurant.days_until_expiry()
    show_expiry_notice = days_left is not None and 0 <= days_left <= 3

    settings_map = {s.key: s.value for s in PlatformSettings.query.all()}

    # Today's Sales quick summary (same business-day window as the daily serial number)
    from utils.timezones import get_local_time
    local_now = get_local_time(datetime.utcnow(), restaurant.country_code) or datetime.utcnow()
    reset_hour = restaurant.daily_reset_hour or 0
    today_business_date = local_now.date() if local_now.hour >= reset_hour else (local_now - timedelta(days=1)).date()
    today_orders = [o for o in Order.query.filter_by(
        restaurant_id=restaurant.id, business_date=today_business_date).all()]
    today_item_counts = {}
    today_total = 0
    for o in today_orders:
        today_total += o.total_price or 0
        try:
            for it in json.loads(o.items):
                today_item_counts[it["name"]] = today_item_counts.get(it["name"], 0) + it["count"]
        except Exception:
            pass
    today_sales = {
        "order_count": len(today_orders),
        "total": today_total,
        "top_items": sorted(today_item_counts.items(), key=lambda x: -x[1]),
    }

    return render_template("owner/dashboard.html", restaurant=restaurant, orders=orders,
                            atext=atext_for(restaurant), days_left=days_left,
                            show_expiry_notice=show_expiry_notice,
                            full_access=is_full_access(),
                            demo_video_url=settings_map.get("demo_video_url"),
                            today_sales=today_sales)


@owner_bp.route("/update_status/<int:order_id>/<status>")
def update_status(order_id, status):
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    order = Order.query.filter_by(id=order_id, restaurant_id=restaurant.id).first_or_404()
    order.status = status
    db.session.commit()
    return redirect(url_for("owner.dashboard"))


@owner_bp.route("/complete_payment/<int:order_id>", methods=["POST"])
def complete_payment(order_id):
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    order = Order.query.filter_by(id=order_id, restaurant_id=restaurant.id).first_or_404()
    payment_method = request.form.get("payment_method", "Cash")
    order.status = "Completed"
    order.payment_method = payment_method
    order.is_paid = True
    db.session.commit()

    country = CountryConfig.query.get(restaurant.country_code)
    if restaurant.counter_printer:
        receipt = generate_receipt(order, restaurant, country.currency_symbol, "CUSTOMER", payment_method)
        send_to_printer(restaurant.counter_printer, receipt)
    return redirect(url_for("owner.dashboard"))


@owner_bp.route("/order/<int:order_id>/print")
def print_order(order_id):
    """A print-styled page for any past order — staff hits Ctrl+P / uses the browser's
    Save-as-PDF to get a PDF copy of any specific order, any time."""
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    order = Order.query.filter_by(id=order_id, restaurant_id=restaurant.id).first_or_404()
    try:
        order.food_list = json.loads(order.items)
    except Exception:
        order.food_list = []
    country = CountryConfig.query.get(restaurant.country_code)
    from utils.timezones import get_local_time
    order.local_dt = get_local_time(order.created_at, restaurant.country_code) or order.created_at
    return render_template("owner/print_order.html", order=order, restaurant=restaurant, country=country)


# ---------- Settings (branding, printers, tables/QR, GPS) ----------

@owner_bp.route("/settings", methods=["GET", "POST"])
def settings():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))

    username_error = session.pop("username_error", None)
    if request.method == "POST":
        restaurant.kitchen_printer = request.form.get("kitchen_printer")
        restaurant.counter_printer = request.form.get("counter_printer")
        restaurant.popup_text = request.form.get("popup_text")
        restaurant.address = request.form.get("address", restaurant.address)
        if request.form.get("panel_language") in ("en", "kr"):
            restaurant.panel_language = request.form.get("panel_language")
        colors = request.form.getlist("colors")
        if colors:
            restaurant.signboard_colors = ",".join(colors[:6])

        restaurant.table_count = int(request.form.get("table_count") or restaurant.table_count)
        restaurant.qr_expiry_minutes = int(request.form.get("qr_expiry_minutes") or 10)
        restaurant.gps_enabled = bool(request.form.get("gps_enabled"))
        lat = request.form.get("gps_lat")
        lng = request.form.get("gps_lng")
        restaurant.gps_lat = float(lat) if lat else None
        restaurant.gps_lng = float(lng) if lng else None
        restaurant.gps_radius_m = int(request.form.get("gps_radius_m") or 30)

        restaurant.daily_reset_hour = int(request.form.get("daily_reset_hour") or 0)
        restaurant.bill_footer_message = request.form.get("bill_footer_message", restaurant.bill_footer_message)

        restaurant.opening_time = request.form.get("opening_time", restaurant.opening_time)
        restaurant.closing_time = request.form.get("closing_time", restaurant.closing_time)
        restaurant.about_text = request.form.get("about_text", restaurant.about_text)

        restaurant.bank_payment_enabled = bool(request.form.get("bank_payment_enabled"))
        restaurant.bank_name = request.form.get("bank_name", restaurant.bank_name)
        restaurant.bank_account_holder = request.form.get("bank_account_holder", restaurant.bank_account_holder)
        restaurant.bank_account_number = request.form.get("bank_account_number", restaurant.bank_account_number)

        if "bg_image" in request.files:
            file = request.files["bg_image"]
            if file and file.filename:
                filename = secure_filename(f"{restaurant.slug}_{file.filename}")
                file.save(os.path.join(current_app.config["BG_FOLDER"], filename))
                restaurant.bg_image = filename

        if "owner_profile_picture" in request.files:
            file = request.files["owner_profile_picture"]
            if file and file.filename:
                filename = secure_filename(f"{restaurant.slug}_owner_{file.filename}")
                file.save(os.path.join(current_app.config["BG_FOLDER"], filename))
                restaurant.profile_image = filename

        db.session.commit()

    return render_template("owner/settings.html", restaurant=restaurant, atext=atext_for(restaurant),
                            palette=COLOR_PALETTE, full_access=True, username_error=username_error,
                            current_colors=restaurant.signboard_colors.split(","))


@owner_bp.route("/update_admin_password", methods=["POST"])
def update_admin_password():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    restaurant.set_admin_password(request.form["password"])
    db.session.commit()
    return redirect(url_for("owner.settings"))


@owner_bp.route("/update_owner_password", methods=["POST"])
def update_owner_password():
    """Changes the extra device-login password (separate from the shared staff ID/password)."""
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    new_pw = request.form.get("password", "")
    if len(new_pw) < 6:
        return redirect(url_for("owner.settings"))
    restaurant.set_owner_password(new_pw)
    db.session.commit()
    return redirect(url_for("owner.settings"))


@owner_bp.route("/update_username", methods=["POST"])
def update_username():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))

    new_username = (request.form.get("username") or "").strip()
    new_password = request.form.get("username_password", "")

    if new_username and new_username != restaurant.username:
        taken = Restaurant.query.filter(Restaurant.username == new_username,
                                         Restaurant.id != restaurant.id).first()
        if taken:
            session["username_error"] = "That username is already taken — please choose another."
            return redirect(url_for("owner.settings"))
        restaurant.username = new_username

    if new_password:
        if len(new_password) < 6:
            session["username_error"] = "Password must be at least 6 characters."
            return redirect(url_for("owner.settings"))
        restaurant.set_username_password(new_password)

    db.session.commit()
    return redirect(url_for("owner.settings"))


@owner_bp.route("/generate_qr_codes")
def generate_qr_codes():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    filenames = []
    for t in range(1, restaurant.table_count + 1):
        fn = generate_table_qr(current_app.config["PUBLIC_URL"], restaurant.slug, t, current_app.config["QR_FOLDER"])
        filenames.append(fn)
    return render_template("owner/qr_codes.html", restaurant=restaurant, filenames=filenames,
                            atext=atext_for(restaurant), full_access=True)


@owner_bp.route("/generate_single_qr", methods=["GET", "POST"])
def generate_single_qr():
    """One QR label at a time — owner types a table name + a message (any
    language), gets back a printable 2-3 inch card. Nothing is saved; typing
    fresh text each time is by design."""
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))

    if request.method == "POST":
        table_label = request.form.get("table_label", "").strip() or "Table"
        message = request.form.get("message", "").strip()
        qr_filename = generate_single_table_qr(
            current_app.config["PUBLIC_URL"], restaurant.slug, table_label, current_app.config["QR_FOLDER"])
        return render_template("owner/qr_single_result.html", restaurant=restaurant,
                                table_label=table_label, message=message, qr_filename=qr_filename,
                                atext=atext_for(restaurant), full_access=True)

    return render_template("owner/qr_single_form.html", restaurant=restaurant,
                            atext=atext_for(restaurant), full_access=True)


# ---------- Menu manager ----------

@owner_bp.route("/menu_manager", methods=["GET", "POST"])
def menu_manager():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))

    if request.method == "POST":
        file = request.files.get("image")
        filename, hd_filename = "default.jpg", None
        if file and file.filename:
            base = secure_filename(f"{restaurant.slug}_{int(datetime.utcnow().timestamp())}_{file.filename}")
            filename, hd_filename = save_optimized_image(
                file, current_app.config["UPLOAD_FOLDER_HD"], current_app.config["UPLOAD_FOLDER"], base)

        item = MenuItem(
            restaurant_id=restaurant.id,
            category_id=request.form["category_id"],
            name_primary=request.form["name_primary"],
            name_secondary=request.form["name_secondary"],
            price=float(request.form.get("price") or 0),
            image_url=filename,
            image_url_hd=hd_filename,
        )
        db.session.add(item)
        db.session.commit()

    categories = MenuCategory.query.filter_by(restaurant_id=restaurant.id).all()
    items = MenuItem.query.filter_by(restaurant_id=restaurant.id).order_by(MenuItem.id.desc()).all()
    tiers_by_item = {}
    for i in items:
        tiers_by_item[i.id] = PortionTier.query.filter_by(menu_item_id=i.id).order_by(PortionTier.sort_order).all()
    out_of_stock_enabled = is_feature_enabled("out_of_stock_toggle", restaurant=restaurant)
    return render_template("owner/menu_manager.html", categories=categories, items=items, restaurant=restaurant,
                            atext=atext_for(restaurant), out_of_stock_enabled=out_of_stock_enabled, full_access=True,
                            tiers_by_item=tiers_by_item)


@owner_bp.route("/menu_item/<int:item_id>/toggle_stock")
def toggle_stock(item_id):
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    item = MenuItem.query.filter_by(id=item_id, restaurant_id=restaurant.id).first_or_404()
    item.in_stock = not item.in_stock
    db.session.commit()
    return redirect(url_for("owner.menu_manager"))


@owner_bp.route("/menu_item/<int:item_id>/delete")
def delete_menu_item(item_id):
    """Permanently removes an item from the menu. Past orders keep their own
    saved item name/price (stored as JSON per order), so old sales history
    and reports are completely unaffected."""
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    item = MenuItem.query.filter_by(id=item_id, restaurant_id=restaurant.id).first_or_404()

    PortionTier.query.filter_by(menu_item_id=item.id).delete()
    DailyOffer.query.filter_by(menu_item_id=item.id).delete()
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("owner.menu_manager"))


@owner_bp.route("/category_add", methods=["POST"])
def category_add():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    cat = MenuCategory(
        restaurant_id=restaurant.id,
        name_primary=request.form["name_primary"],
        name_secondary=request.form["name_secondary"],
        multi_portion_enabled=bool(request.form.get("multi_portion_enabled")),
    )
    db.session.add(cat)
    db.session.commit()
    return redirect(url_for("owner.menu_manager"))


@owner_bp.route("/category/<int:category_id>/toggle_multi_portion")
def toggle_multi_portion(category_id):
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    cat = MenuCategory.query.filter_by(id=category_id, restaurant_id=restaurant.id).first_or_404()
    cat.multi_portion_enabled = not cat.multi_portion_enabled
    db.session.commit()
    return redirect(url_for("owner.menu_manager"))


# ---------- Portion tiers (multi-portion pricing) ----------

@owner_bp.route("/menu_item/<int:item_id>/tier_add", methods=["POST"])
def tier_add(item_id):
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    item = MenuItem.query.filter_by(id=item_id, restaurant_id=restaurant.id).first_or_404()

    existing_count = PortionTier.query.filter_by(menu_item_id=item.id).count()
    serves = request.form.get("serves_count")
    tier = PortionTier(
        menu_item_id=item.id,
        label=request.form["label"],
        serves_count=int(serves) if serves else None,
        price=float(request.form["price"]),
        sort_order=existing_count,
    )
    db.session.add(tier)
    db.session.commit()
    return redirect(url_for("owner.menu_manager"))


@owner_bp.route("/tier/<int:tier_id>/delete")
def tier_delete(tier_id):
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    tier = PortionTier.query.join(MenuItem).filter(
        PortionTier.id == tier_id, MenuItem.restaurant_id == restaurant.id
    ).first_or_404()
    db.session.delete(tier)
    db.session.commit()
    return redirect(url_for("owner.menu_manager"))


# ---------- Daily offers ----------

@owner_bp.route("/offers", methods=["GET", "POST"])
def offers():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))

    if request.method == "POST":
        dow = request.form.get("day_of_week")
        tier_id = request.form.get("portion_tier_id")
        offer = DailyOffer(
            restaurant_id=restaurant.id,
            menu_item_id=request.form["menu_item_id"],
            portion_tier_id=int(tier_id) if tier_id else None,
            day_of_week=int(dow) if dow != "" else None,
            discount_percent=int(request.form.get("discount_percent") or 0),
            highlight_as_best_seller=bool(request.form.get("highlight_best_seller")),
        )
        db.session.add(offer)
        db.session.commit()

    items = MenuItem.query.filter_by(restaurant_id=restaurant.id).all()
    tiers_by_item = {}
    for i in items:
        tiers_by_item[i.id] = PortionTier.query.filter_by(menu_item_id=i.id).order_by(PortionTier.sort_order).all()
    current_offers = DailyOffer.query.filter_by(restaurant_id=restaurant.id).all()
    return render_template("owner/offers.html", items=items, offers=current_offers, restaurant=restaurant,
                            atext=atext_for(restaurant), full_access=True, tiers_by_item=tiers_by_item)


# ---------- Staff accounts ----------

@owner_bp.route("/staff", methods=["GET", "POST"])
def staff():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    if not is_feature_enabled("staff_roles", restaurant=restaurant):
        return redirect(url_for("owner.dashboard"))

    if request.method == "POST":
        s = StaffUser(
            restaurant_id=restaurant.id,
            name=request.form["name"],
            username=request.form["username"],
            role=request.form.get("role", "waiter"),
        )
        s.set_password(request.form["password"])
        db.session.add(s)
        db.session.commit()

    staff_list = StaffUser.query.filter_by(restaurant_id=restaurant.id).all()
    return render_template("owner/staff.html", restaurant=restaurant, staff_list=staff_list,
                            atext=atext_for(restaurant), full_access=True)


# ---------- Sales calendar / history ----------

@owner_bp.route("/sales_calendar")
def sales_calendar():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))

    selected_date_str = request.args.get("date")
    if selected_date_str:
        selected_date = datetime.strptime(selected_date_str, "%Y-%m-%d").date()
    else:
        selected_date = date.today()

    day_start = datetime.combine(selected_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    day_orders = Order.query.filter(
        Order.restaurant_id == restaurant.id,
        Order.created_at >= day_start, Order.created_at < day_end
    ).order_by(Order.id.desc()).all()

    total_sales = sum(o.total_price for o in day_orders)

    item_counts = {}
    for o in day_orders:
        try:
            for it in json.loads(o.items):
                item_counts[it["name"]] = item_counts.get(it["name"], 0) + it["count"]
        except Exception:
            pass
    best_sellers = sorted(item_counts.items(), key=lambda x: -x[1])[:5]

    return render_template("owner/sales_calendar.html", restaurant=restaurant, orders=day_orders,
                            selected_date=selected_date, total_sales=total_sales, best_sellers=best_sellers,
                            atext=atext_for(restaurant), full_access=is_full_access())


@owner_bp.route("/sales_data/delete", methods=["POST"])
def delete_sales_data():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    scope = request.form.get("scope")  # day | month | year
    ref_date_str = request.form.get("ref_date")
    ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d").date() if ref_date_str else date.today()

    q = Order.query.filter(Order.restaurant_id == restaurant.id)
    if scope == "day":
        q = q.filter(db.func.date(Order.created_at) == ref_date)
    elif scope == "month":
        q = q.filter(db.extract("year", Order.created_at) == ref_date.year,
                     db.extract("month", Order.created_at) == ref_date.month)
    elif scope == "year":
        q = q.filter(db.extract("year", Order.created_at) == ref_date.year)
    q.delete(synchronize_session=False)
    db.session.commit()
    return redirect(url_for("owner.sales_calendar"))


# ---------- Analytics ----------

@owner_bp.route("/analytics")
def analytics():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_feature_enabled("analytics_dashboard", restaurant=restaurant):
        return redirect(url_for("owner.dashboard"))

    orders = Order.query.filter_by(restaurant_id=restaurant.id).all()
    daily_totals = {}
    for o in orders:
        d = o.created_at.strftime("%Y-%m-%d")
        daily_totals[d] = daily_totals.get(d, 0) + o.total_price
    sorted_days = sorted(daily_totals.items())[-30:]  # last 30 days with data

    return render_template("owner/analytics.html", restaurant=restaurant, sorted_days=sorted_days,
                            atext=atext_for(restaurant), full_access=is_full_access())


# ---------- Backup ----------

@owner_bp.route("/backup_now")
def backup_now():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    categories = MenuCategory.query.filter_by(restaurant_id=restaurant.id).all()
    items = MenuItem.query.filter_by(restaurant_id=restaurant.id).all()
    orders = Order.query.filter_by(restaurant_id=restaurant.id).all()
    zip_path = export_restaurant_backup(restaurant, categories, items, orders, current_app.config["BACKUP_FOLDER"])
    return send_file(zip_path, as_attachment=True)


# ---------- Platform review ----------

@owner_bp.route("/leave_review", methods=["GET", "POST"])
def leave_review():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    if not is_full_access():
        return redirect(url_for("owner.dashboard"))
    if not restaurant.is_active():
        return redirect(url_for("owner.subscription"))

    if request.method == "POST":
        review = PlatformReview(
            restaurant_id=restaurant.id,
            rating=int(request.form["rating"]),
            review_text=request.form.get("review_text", ""),
        )
        db.session.add(review)
        db.session.commit()
        return redirect(url_for("owner.dashboard"))

    return render_template("owner/leave_review.html", restaurant=restaurant, atext=atext_for(restaurant), full_access=True)


# ---------- Reports ----------

@owner_bp.route("/download_report_pdf")
def download_report_pdf():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))

    scope = request.args.get("scope", "day")  # day | month | year
    ref_date_str = request.args.get("ref_date")
    ref_date = datetime.strptime(ref_date_str, "%Y-%m-%d").date() if ref_date_str else date.today()

    q = Order.query.filter(Order.restaurant_id == restaurant.id)
    if scope == "day":
        q = q.filter(db.func.date(Order.created_at) == ref_date)
        label = f"Report for {ref_date}"
    elif scope == "month":
        q = q.filter(db.extract("year", Order.created_at) == ref_date.year,
                     db.extract("month", Order.created_at) == ref_date.month)
        label = f"Report for {ref_date.strftime('%B %Y')}"
    else:
        q = q.filter(db.extract("year", Order.created_at) == ref_date.year)
        label = f"Report for {ref_date.year}"

    orders = q.order_by(Order.id).all()
    country = CountryConfig.query.get(restaurant.country_code)
    path = os.path.join("static", f"Sales_Report_{restaurant.slug}_{scope}.pdf")
    generate_sales_report_pdf(path, restaurant.name, country.currency_symbol, label, orders)
    return send_file(path, as_attachment=True)


@owner_bp.route("/download_report")
def download_report():
    restaurant = require_active_login()
    if not restaurant:
        return redirect(url_for("owner.login"))
    orders = Order.query.filter_by(restaurant_id=restaurant.id).all()
    rows = [{
        "id": o.id, "table": o.table_no, "mode": o.dining_mode, "total": o.total_price,
        "status": o.status, "payment_method": o.payment_method, "time": o.created_at
    } for o in orders]
    df = pd.DataFrame(rows)
    path = os.path.join("static", f"Sales_Report_{restaurant.slug}.xlsx")
    df.to_excel(path, index=False)
    return redirect(url_for("static", filename=os.path.basename(path)))


# ---------- Print Agent API (for the local Windows print-agent script) ----------
# Authenticated with HTTP Basic Auth using the same shared admin_username /
# admin_password the owner already uses for the staff login page — no new
# credential to create or share.

def _authenticate_agent():
    """Returns the Restaurant if Basic Auth + ?slug= match, else None."""
    auth = request.authorization
    slug = request.args.get("slug", "")
    if not auth or not slug:
        return None
    restaurant = Restaurant.query.filter_by(slug=slug).first()
    if not restaurant:
        return None
    if auth.username != restaurant.admin_username:
        return None
    if not restaurant.admin_password_hash or not restaurant.check_admin_password(auth.password):
        return None
    return restaurant


@owner_bp.route("/api/pending_print")
def api_pending_print():
    restaurant = _authenticate_agent()
    if not restaurant:
        return jsonify({"error": "unauthorized"}), 401

    from utils.timezones import get_local_time

    orders = Order.query.filter_by(restaurant_id=restaurant.id, print_failed=True).order_by(Order.id).limit(20).all()
    country = CountryConfig.query.get(restaurant.country_code)

    order_list = []
    for o in orders:
        try:
            items = json.loads(o.items)
        except Exception:
            items = []
        local_dt = get_local_time(o.created_at, restaurant.country_code) if o.created_at else None
        order_list.append({
            "id": o.id, "table_no": o.table_no, "dining_mode": o.dining_mode,
            "items": items, "total_price": o.total_price,
            "daily_serial": o.daily_serial, "payment_method": o.payment_method,
            "special_instructions": getattr(o, "special_instructions", None),
            "is_paid": getattr(o, "is_paid", False),
            "status": o.status,
            "created_at": o.created_at.isoformat() if o.created_at else None,
            "local_datetime": local_dt.strftime("%Y-%m-%d %H:%M") if local_dt else "",
        })

    return jsonify({
        "restaurant_name": restaurant.name,
        "kitchen_printer": restaurant.kitchen_printer,
        "counter_printer": restaurant.counter_printer,
        "currency_symbol": country.currency_symbol if country else "",
        "bill_footer_message": restaurant.bill_footer_message or "",
        "country_code": restaurant.country_code,
        "orders": order_list,
    })


@owner_bp.route("/api/mark_printed", methods=["POST"])
def api_mark_printed():
    restaurant = _authenticate_agent()
    if not restaurant:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    order_ids = data.get("order_ids", [])
    if not order_ids:
        return jsonify({"success": True, "updated": 0})

    updated = Order.query.filter(
        Order.restaurant_id == restaurant.id, Order.id.in_(order_ids)
    ).update({"print_failed": False}, synchronize_session=False)
    db.session.commit()
    return jsonify({"success": True, "updated": updated})


# ---------- Call Staff (voice-alert queue) + silent order polling ----------

@owner_bp.route("/api/staff_calls")
def api_staff_calls():
    """Polled every few seconds by any owner/staff panel page that's open."""
    restaurant = current_restaurant()
    if not restaurant:
        return jsonify({"error": "unauthorized"}), 401
    calls = StaffCall.query.filter_by(restaurant_id=restaurant.id, dismissed=False) \
        .order_by(StaffCall.created_at).all()
    lang = restaurant.panel_language or ("kr" if restaurant.country_code == "KR" else "en")
    return jsonify({
        "calls": [{"id": c.id, "table_no": c.table_no} for c in calls],
        "panel_language": lang,
    })


@owner_bp.route("/api/dismiss_call/<int:call_id>", methods=["POST"])
def api_dismiss_call(call_id):
    restaurant = current_restaurant()
    if not restaurant:
        return jsonify({"error": "unauthorized"}), 401
    call = StaffCall.query.filter_by(id=call_id, restaurant_id=restaurant.id).first_or_404()
    call.dismissed = True
    db.session.commit()
    return jsonify({"success": True})


@owner_bp.route("/api/latest_order_id")
def api_latest_order_id():
    """Used by the dashboard to silently detect a new order and refresh."""
    restaurant = current_restaurant()
    if not restaurant:
        return jsonify({"error": "unauthorized"}), 401
    latest = Order.query.filter_by(restaurant_id=restaurant.id).order_by(Order.id.desc()).first()
    return jsonify({"latest_id": latest.id if latest else 0})
