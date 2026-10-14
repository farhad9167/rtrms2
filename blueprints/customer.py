import json
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, session, current_app
from models import db, Restaurant, MenuCategory, MenuItem, DailyOffer, Order, CountryConfig, PortionTier, StaffCall
from translations import translations
from utils.printer import send_to_printer, generate_receipt
from utils.security import make_qr_token, verify_qr_token, within_radius
from utils.features import is_feature_enabled
from utils.timezones import get_local_time

customer_bp = Blueprint("customer", __name__)


@customer_bp.route("/r/<slug>/menu")
@customer_bp.route("/r/<slug>")
def menu(slug):
    restaurant = Restaurant.query.filter_by(slug=slug).first_or_404()
    country = CountryConfig.query.get(restaurant.country_code)

    if not country:
        # A restaurant with a missing/invalid country_code should never crash
        # the page for a real customer — show a clear message instead.
        return render_template("customer/inactive.html", restaurant=restaurant,
                                reason="This restaurant's menu is temporarily unavailable. "
                                       "Please contact the restaurant directly."), 503

    lang = request.args.get("lang") or session.get(f"lang_{slug}") or (country.lang_primary if country else "en")
    session[f"lang_{slug}"] = lang
    text = translations.get(lang, translations["en"])

    if not restaurant.is_active():
        return render_template("customer/inactive.html", restaurant=restaurant)

    table_no = request.args.get("table", "1")

    # --- QR time-limited token ---
    qr_enabled = is_feature_enabled("qr_time_expiry", restaurant=restaurant)
    token = request.args.get("t")
    if qr_enabled:
        if not token:
            # First scan of the printed QR: issue a fresh token and redirect to a URL that carries it.
            new_token = make_qr_token(current_app.secret_key, slug, table_no)
            from flask import redirect, url_for
            return redirect(url_for("customer.menu", slug=slug, table=table_no, lang=lang, t=new_token))
        if not verify_qr_token(current_app.secret_key, slug, table_no, token, restaurant.qr_expiry_minutes or 10):
            return render_template("customer/qr_expired.html", restaurant=restaurant, table_no=table_no)

    today_dow = datetime.now().weekday()

    categories = MenuCategory.query.filter_by(restaurant_id=restaurant.id).order_by(MenuCategory.sort_order).all()
    items = MenuItem.query.filter_by(restaurant_id=restaurant.id).all()
    all_offers = DailyOffer.query.filter_by(restaurant_id=restaurant.id).all()
    active_offers = [o for o in all_offers if o.day_of_week is None or o.day_of_week == today_dow]
    # Whole-item discounts key on menu_item_id; tier-specific discounts key on (menu_item_id, tier_id).
    item_offers = {o.menu_item_id: o for o in active_offers if o.portion_tier_id is None}
    tier_offers = {(o.menu_item_id, o.portion_tier_id): o for o in active_offers if o.portion_tier_id is not None}

    out_of_stock_enabled = is_feature_enabled("out_of_stock_toggle", restaurant=restaurant)

    menu_data = {}
    for cat in categories:
        cat_name = cat.name_primary if lang == country.lang_primary else cat.name_secondary
        food_list = []
        for i in items:
            if i.category_id != cat.id:
                continue
            if out_of_stock_enabled and not i.in_stock:
                continue

            item_name = i.name_primary if lang == country.lang_primary else i.name_secondary
            offer = item_offers.get(i.id)
            is_best = i.is_best_selling or (offer.highlight_as_best_seller if offer else False)

            if cat.multi_portion_enabled:
                tiers = PortionTier.query.filter_by(menu_item_id=i.id).order_by(PortionTier.sort_order).all()
                if tiers:
                    tier_list = []
                    for t in tiers:
                        t_offer = tier_offers.get((i.id, t.id)) or offer  # tier-specific wins, else whole-item discount
                        discount = t_offer.discount_percent if t_offer else 0
                        final_price = round(t.price * (1 - discount / 100), 2) if discount else t.price
                        tier_list.append({
                            "id": t.id, "label": t.label, "serves_count": t.serves_count,
                            "price": final_price, "original_price": t.price if discount else None,
                        })
                    food_list.append({
                        "id": i.id, "name": item_name, "image": i.image_url,
                        "is_best_selling": is_best, "tiers": tier_list,
                    })
                    continue
                # category has multi-portion on but this item has no tiers yet -> fall through to flat price

            discount = offer.discount_percent if offer else 0
            final_price = round(i.price * (1 - discount / 100), 2) if discount else i.price
            food_list.append({
                "id": i.id,
                "name": item_name,
                "price": final_price,
                "original_price": i.price if discount else None,
                "image": i.image_url,
                "is_best_selling": is_best,
            })
        if food_list:
            menu_data[cat_name] = food_list

    gps_check_enabled = restaurant.gps_enabled and is_feature_enabled("gps_radius_check", restaurant=restaurant)

    return render_template(
        "customer/menu.html",
        restaurant=restaurant, menu_data=menu_data, text=text, lang=lang,
        country=country, table_no=table_no, qr_token=token,
        gps_check_enabled=gps_check_enabled,
        other_lang="en" if lang != "en" else country.lang_primary,
    )


@customer_bp.route("/r/<slug>/place_order", methods=["POST"])
def place_order(slug):
    restaurant = Restaurant.query.filter_by(slug=slug).first_or_404()
    if not restaurant.is_active():
        return jsonify({"success": False, "error": "restaurant inactive"}), 403
    if not CountryConfig.query.get(restaurant.country_code):
        return jsonify({"success": False, "error": "restaurant_misconfigured"}), 503

    data = request.get_json()

    # Re-validate the QR token server-side (never trust the client alone)
    if is_feature_enabled("qr_time_expiry", restaurant=restaurant):
        token = data.get("qr_token")
        table_no_check = data.get("table_no", "1")
        if not verify_qr_token(current_app.secret_key, slug, table_no_check, token, restaurant.qr_expiry_minutes or 10):
            return jsonify({"success": False, "error": "qr_expired"}), 403

    # Re-validate GPS radius server-side
    if restaurant.gps_enabled and is_feature_enabled("gps_radius_check", restaurant=restaurant):
        lat, lng = data.get("lat"), data.get("lng")
        if lat is None or lng is None or not within_radius(restaurant, float(lat), float(lng)):
            return jsonify({"success": False, "error": "outside_radius"}), 403

    order = Order(
        restaurant_id=restaurant.id,
        items=json.dumps(data["cart"]),
        total_price=data["total"],
        table_no=data.get("table_no", "1"),
        dining_mode=data.get("dining_mode", "Eat Here"),
        status="Pending",
        special_instructions=(data.get("special_instructions") or "").strip() or None,
    )

    # ---- In-app bill payment (only meaningful when the owner has this on) ----
    if restaurant.bank_payment_enabled:
        payment_choice = data.get("payment_method")  # "bank_transfer" | "cash_card"
        if payment_choice == "bank_transfer":
            order.payment_method = "Bank Transfer"
            order.payment_sender_name = (data.get("sender_name") or "").strip() or None
            order.payment_sender_number = (data.get("sender_number") or "").strip() or None
            order.is_paid = True
        else:
            order.payment_method = "Cash/Card (pay at counter)"
            order.is_paid = False

    # ---- Daily serial number (resets at restaurant.daily_reset_hour local time) ----
    local_dt = get_local_time(datetime.utcnow(), restaurant.country_code) or datetime.utcnow()
    reset_hour = restaurant.daily_reset_hour or 0
    business_date = local_dt.date() if local_dt.hour >= reset_hour else (local_dt - timedelta(days=1)).date()
    existing_count = Order.query.filter_by(restaurant_id=restaurant.id, business_date=business_date).count()
    order.business_date = business_date
    order.daily_serial = existing_count + 1

    db.session.add(order)
    db.session.commit()

    country = CountryConfig.query.get(restaurant.country_code)
    flask_app = current_app._get_current_object()
    order_id = order.id

    def _mark_print_failed(success):
        if success:
            return
        with flask_app.app_context():
            o = Order.query.get(order_id)
            if o:
                o.print_failed = True
                db.session.commit()

    # Kitchen ticket (items + prices, no payment/footer)
    if restaurant.kitchen_printer:
        kitchen_receipt = generate_receipt(order, restaurant, country.currency_symbol, "KITCHEN")
        send_to_printer(restaurant.kitchen_printer, kitchen_receipt, on_result=_mark_print_failed)

    # Counter ticket — printed immediately at order time too, per the unified-bill design
    if restaurant.counter_printer:
        counter_receipt = generate_receipt(order, restaurant, country.currency_symbol, "COUNTER")
        send_to_printer(restaurant.counter_printer, counter_receipt, on_result=_mark_print_failed)

    # Data for the customer's own phone screen — same info as the printed copies
    try:
        cart_items = json.loads(order.items)
    except Exception:
        cart_items = []
    receipt_data = {
        "restaurant_name": restaurant.name,
        "table_no": order.table_no,
        "daily_serial": order.daily_serial,
        "date": local_dt.strftime("%Y-%m-%d"),
        "time": local_dt.strftime("%H:%M"),
        "currency_symbol": country.currency_symbol,
        "items": cart_items,
        "total": order.total_price,
        "footer_message": restaurant.bill_footer_message or None,
        "special_instructions": order.special_instructions,
        "is_paid": order.is_paid,
        "payment_method": order.payment_method,
        "pay_at_counter": restaurant.bank_payment_enabled and not order.is_paid,
    }

    return jsonify({"success": True, "order_id": order.id, "receipt": receipt_data})


@customer_bp.route("/r/<slug>/order/<int:order_id>/status")
def order_status(slug, order_id):
    """Lets a customer poll their own order's status from their phone."""
    restaurant = Restaurant.query.filter_by(slug=slug).first_or_404()
    if not is_feature_enabled("order_status_tracking", restaurant=restaurant):
        return jsonify({"error": "feature_disabled"}), 404
    order = Order.query.filter_by(id=order_id, restaurant_id=restaurant.id).first_or_404()
    return jsonify({"status": order.status})


@customer_bp.route("/r/<slug>/call_staff", methods=["POST"])
def call_staff(slug):
    restaurant = Restaurant.query.filter_by(slug=slug).first_or_404()
    if not restaurant.is_active():
        return jsonify({"success": False}), 403
    data = request.get_json(silent=True) or {}
    table_no = str(data.get("table_no", "1"))[:64]
    call = StaffCall(restaurant_id=restaurant.id, table_no=table_no)
    db.session.add(call)
    db.session.commit()
    return jsonify({"success": True})
