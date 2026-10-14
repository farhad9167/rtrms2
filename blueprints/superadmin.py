import os
from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, request, redirect, url_for, session, current_app
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import (db, Restaurant, CountryConfig, PaymentRequest, PlatformSettings,
                     FeatureFlag, PromoCode, PlatformReview)
from utils.features import FEATURE_REGISTRY
from oauth import oauth

superadmin_bp = Blueprint("superadmin", __name__)

# Only a Google sign-in from one of these emails can reset the super-admin
# password. Not stored in the DB — deliberately hardcoded here so it can't be
# changed by anyone who merely gets database access.
AUTHORIZED_RESET_EMAILS = {"sellovateai@gmail.com", "mdfarhadhossain9167@gmail.com"}


def logged_in():
    return session.get("superadmin_logged_in")


def _get_or_init_password_hash():
    """The super-admin password now lives in the database (hashed), so it can
    be reset without editing .env. The very first time this runs, it seeds
    the DB from the .env value so nothing breaks on upgrade."""
    row = PlatformSettings.query.get("superadmin_password_hash")
    if row and row.value:
        return row.value
    new_hash = generate_password_hash(current_app.config["SUPERADMIN_PASSWORD"])
    db.session.add(PlatformSettings(key="superadmin_password_hash", value=new_hash))
    db.session.commit()
    return new_hash


@superadmin_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"]
        p = request.form["password"]
        stored_hash = _get_or_init_password_hash()
        if u == current_app.config["SUPERADMIN_USERNAME"] and check_password_hash(stored_hash, p):
            session["superadmin_logged_in"] = True
            return redirect(url_for("superadmin.dashboard"))
    return render_template("superadmin/login.html")


@superadmin_bp.route("/logout")
def logout():
    session.pop("superadmin_logged_in", None)
    return redirect(url_for("superadmin.login"))


# ---------- Forgot password (Google-verified, authorized emails only) ----------

@superadmin_bp.route("/reset_password_request")
def reset_password_request():
    session["superadmin_reset_mode"] = True
    redirect_uri = url_for("superadmin.reset_password_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@superadmin_bp.route("/reset_password_callback")
def reset_password_callback():
    if not session.pop("superadmin_reset_mode", False):
        return redirect(url_for("superadmin.login"))
    token = oauth.google.authorize_access_token()
    userinfo = token.get("userinfo") or oauth.google.parse_id_token(token)
    email = userinfo.get("email", "")

    if email not in AUTHORIZED_RESET_EMAILS:
        return render_template("superadmin/reset_denied.html", email=email)

    session["superadmin_reset_verified"] = True
    return redirect(url_for("superadmin.reset_password_set"))


@superadmin_bp.route("/reset_password_set", methods=["GET", "POST"])
def reset_password_set():
    if not session.get("superadmin_reset_verified"):
        return redirect(url_for("superadmin.login"))

    error = None
    if request.method == "POST":
        pw = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if len(pw) < 6:
            error = "Password must be at least 6 characters."
        elif pw != confirm:
            error = "Passwords do not match."
        else:
            new_hash = generate_password_hash(pw)
            row = PlatformSettings.query.get("superadmin_password_hash")
            if not row:
                row = PlatformSettings(key="superadmin_password_hash")
                db.session.add(row)
            row.value = new_hash
            db.session.commit()
            session.pop("superadmin_reset_verified", None)
            return redirect(url_for("superadmin.login"))

    return render_template("superadmin/reset_password_set.html", error=error)


@superadmin_bp.route("/")
@superadmin_bp.route("/dashboard")
def dashboard():
    if not logged_in():
        return redirect(url_for("superadmin.login"))
    restaurants = Restaurant.query.order_by(Restaurant.id.desc()).all()
    pending_payments = PaymentRequest.query.filter_by(status="pending").all()
    active_count = sum(1 for r in restaurants if r.subscription_status == "active")
    return render_template("superadmin/dashboard.html", restaurants=restaurants,
                            pending_payments=pending_payments, active_count=active_count, active="dashboard")


@superadmin_bp.route("/payment/<int:pr_id>/<action>")
def review_payment(pr_id, action):
    if not logged_in():
        return redirect(url_for("superadmin.login"))
    pr = PaymentRequest.query.get_or_404(pr_id)
    restaurant = Restaurant.query.get(pr.restaurant_id)

    if action == "approve":
        pr.status = "approved"
        months = pr.months or 1
        # If the restaurant is still active and renewing early, extend from the
        # current expiry date rather than from today, so early renewal doesn't
        # lose the days they already paid for.
        base_date = restaurant.subscription_expiry if (
            restaurant.subscription_expiry and restaurant.subscription_expiry >= date.today()
        ) else date.today()
        restaurant.subscription_status = "active"
        restaurant.subscription_expiry = base_date + timedelta(days=30 * months)
        restaurant.notified_since = None  # renewing clears any pending expiry notice
    elif action == "reject":
        pr.status = "rejected"

    pr.reviewed_at = datetime.utcnow()
    db.session.commit()
    return redirect(url_for("superadmin.dashboard"))


@superadmin_bp.route("/restaurant/<int:rid>/<action>")
def restaurant_action(rid, action):
    if not logged_in():
        return redirect(url_for("superadmin.login"))
    restaurant = Restaurant.query.get_or_404(rid)
    if action == "suspend":
        restaurant.subscription_status = "suspended"
    elif action == "activate":
        restaurant.subscription_status = "active"
        restaurant.subscription_expiry = date.today() + timedelta(days=30)
    db.session.commit()
    return redirect(url_for("superadmin.dashboard"))


@superadmin_bp.route("/settings", methods=["GET", "POST"])
def settings():
    if not logged_in():
        return redirect(url_for("superadmin.login"))

    if request.method == "POST":
        def upsert(key, value):
            row = PlatformSettings.query.get(key)
            if not row:
                row = PlatformSettings(key=key, value=value)
                db.session.add(row)
            else:
                row.value = value

        upsert("platform_name", request.form.get("platform_name", ""))
        upsert("bank_details_text", request.form.get("bank_details_text", ""))
        upsert("demo_video_url", request.form.get("demo_video_url", ""))
        upsert("facebook_url", request.form.get("facebook_url", ""))
        upsert("instagram_url", request.form.get("instagram_url", ""))
        upsert("youtube_url", request.form.get("youtube_url", ""))

        if "logo" in request.files and request.files["logo"].filename:
            f = request.files["logo"]
            fn = secure_filename(f.filename)
            f.save(os.path.join(current_app.config["BG_FOLDER"], fn))
            upsert("platform_logo", fn)

        if "bank_details_image" in request.files and request.files["bank_details_image"].filename:
            f = request.files["bank_details_image"]
            fn = secure_filename(f.filename)
            f.save(os.path.join(current_app.config["BG_FOLDER"], fn))
            upsert("bank_details_image", fn)

        db.session.commit()

    settings_map = {s.key: s.value for s in PlatformSettings.query.all()}
    countries = CountryConfig.query.all()
    return render_template("superadmin/settings.html", settings=settings_map, countries=countries, active="settings")


@superadmin_bp.route("/country/<code>/fee", methods=["POST"])
def update_country_fee(code):
    if not logged_in():
        return redirect(url_for("superadmin.login"))
    country = CountryConfig.query.get_or_404(code)
    country.monthly_fee = int(request.form["monthly_fee"])
    db.session.commit()
    return redirect(url_for("superadmin.settings"))


# ---------- Feature flags ----------

@superadmin_bp.route("/features", methods=["GET", "POST"])
def features():
    if not logged_in():
        return redirect(url_for("superadmin.login"))

    if request.method == "POST":
        flag = FeatureFlag(
            feature_key=request.form["feature_key"],
            scope=request.form["scope"],
            scope_value=request.form.get("scope_value") or None,
            enabled=bool(request.form.get("enabled")),
            active_from=datetime.fromisoformat(request.form["active_from"]) if request.form.get("active_from") else None,
            active_until=datetime.fromisoformat(request.form["active_until"]) if request.form.get("active_until") else None,
        )
        db.session.add(flag)
        db.session.commit()

    flags = FeatureFlag.query.order_by(FeatureFlag.updated_at.desc()).all()
    restaurants = Restaurant.query.all()
    countries = CountryConfig.query.all()
    return render_template("superadmin/features.html", flags=flags, restaurants=restaurants,
                            countries=countries, registry=FEATURE_REGISTRY, active="features")


@superadmin_bp.route("/features/<int:flag_id>/delete")
def delete_flag(flag_id):
    if not logged_in():
        return redirect(url_for("superadmin.login"))
    flag = FeatureFlag.query.get_or_404(flag_id)
    db.session.delete(flag)
    db.session.commit()
    return redirect(url_for("superadmin.features"))


# ---------- Promo codes ----------

@superadmin_bp.route("/promos", methods=["GET", "POST"])
def promos():
    if not logged_in():
        return redirect(url_for("superadmin.login"))

    if request.method == "POST":
        expires = request.form.get("expires_at")
        promo = PromoCode(
            code=request.form["code"].strip().upper(),
            discount_percent=int(request.form["discount_percent"]),
            min_months=int(request.form.get("min_months") or 1),
            country_code=request.form.get("country_code") or None,
            expires_at=datetime.fromisoformat(expires) if expires else None,
        )
        db.session.add(promo)
        db.session.commit()

    promo_list = PromoCode.query.order_by(PromoCode.id.desc()).all()
    countries = CountryConfig.query.all()
    return render_template("superadmin/promos.html", promo_list=promo_list, countries=countries, active="promos")


@superadmin_bp.route("/promos/<int:promo_id>/toggle")
def toggle_promo(promo_id):
    if not logged_in():
        return redirect(url_for("superadmin.login"))
    promo = PromoCode.query.get_or_404(promo_id)
    promo.active = not promo.active
    db.session.commit()
    return redirect(url_for("superadmin.promos"))


# ---------- Reviews moderation ----------

@superadmin_bp.route("/reviews")
def reviews():
    if not logged_in():
        return redirect(url_for("superadmin.login"))
    review_list = PlatformReview.query.order_by(PlatformReview.created_at.desc()).all()
    return render_template("superadmin/reviews.html", review_list=review_list, active="reviews")


@superadmin_bp.route("/reviews/<int:review_id>/delete")
def delete_review(review_id):
    if not logged_in():
        return redirect(url_for("superadmin.login"))
    review = PlatformReview.query.get_or_404(review_id)
    db.session.delete(review)
    db.session.commit()
    return redirect(url_for("superadmin.reviews"))
