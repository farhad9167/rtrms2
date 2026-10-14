from flask import Blueprint, render_template, request, jsonify
from models import Restaurant, CountryConfig, PlatformReview, PlatformSettings, MenuCategory, MenuItem, PortionTier
from datetime import date
import random
from utils.sales_stats import get_country_sales

public_bp = Blueprint("public", __name__)

# Only these countries are shown on the public landing page's filter tabs and
# sales stats, regardless of how many countries are seeded in CountryConfig
# for onboarding. This does NOT restrict which countries owners can sign up
# from — see blueprints/owner.py's onboarding() for that list.
LANDING_PAGE_COUNTRIES = ["BD", "KR"]

# The umbrella landing page lives on a different subdomain (sellovateai.com),
# so its JS has to fetch these as cross-origin JSON — allow that origin only.
UMBRELLA_ORIGIN = "https://sellovateai.com"


def _with_cors(response):
    response.headers["Access-Control-Allow-Origin"] = UMBRELLA_ORIGIN
    return response


def _restaurant_card_data(r):
    reviews = PlatformReview.query.filter_by(restaurant_id=r.id).order_by(PlatformReview.created_at.desc()).all()
    return {
        "id": r.id, "name": r.name, "slug": r.slug, "address": r.address, "about_text": r.about_text,
        "profile_image": r.profile_image, "opening_time": r.opening_time, "closing_time": r.closing_time,
        "joined_date": r.created_at.date(),
        "avg_rating": round(sum(rv.rating for rv in reviews) / len(reviews), 1) if reviews else None,
        "review_count": len(reviews),
        "reviews": reviews[:2],
    }


@public_bp.route("/")
def landing():
    show_all = request.args.get("all") == "1"
    country_filter = request.args.get("country")

    q = Restaurant.query.filter_by(subscription_status="active")
    if country_filter:
        q = q.filter_by(country_code=country_filter)
    active_restaurants = q.all()

    if show_all:
        chosen = active_restaurants
    else:
        # Reshuffled on every single page load, per your instruction — not a
        # fixed daily set. Every active restaurant gets an equal chance each visit.
        chosen = active_restaurants[:]
        random.shuffle(chosen)
        chosen = chosen[:6]

    restaurants = [_restaurant_card_data(r) for r in chosen]
    countries = CountryConfig.query.filter(CountryConfig.code.in_(LANDING_PAGE_COUNTRIES)).all()
    settings = {s.key: s.value for s in PlatformSettings.query.all()}
    country_sales = get_country_sales()
    return render_template("public/landing.html", restaurants=restaurants, countries=countries,
                            selected_country=country_filter, settings=settings, show_all=show_all,
                            total_active=len(active_restaurants), country_sales=country_sales)


@public_bp.route("/preview/<slug>")
def restaurant_preview(slug):
    """Read-only public profile — name, address, menu, prices, reviews.
    No ordering here on purpose; this is what a restaurant card on the
    landing page links to, distinct from the real /r/<slug>/menu ordering
    page (which requires a table QR scan)."""
    restaurant = Restaurant.query.filter_by(slug=slug, subscription_status="active").first_or_404()
    country = CountryConfig.query.get(restaurant.country_code)

    categories = MenuCategory.query.filter_by(restaurant_id=restaurant.id).order_by(MenuCategory.sort_order).all()
    items = MenuItem.query.filter_by(restaurant_id=restaurant.id).all()

    menu_data = {}
    for cat in categories:
        food_list = []
        for i in items:
            if i.category_id != cat.id:
                continue
            tiers = PortionTier.query.filter_by(menu_item_id=i.id).order_by(PortionTier.sort_order).all() \
                if cat.multi_portion_enabled else []
            food_list.append({
                "name": i.name_secondary or i.name_primary,
                "price": i.price,
                "image": i.image_url,
                "tiers": [{"label": t.label, "price": t.price, "serves_count": t.serves_count} for t in tiers],
            })
        if food_list:
            menu_data[cat.name_secondary or cat.name_primary] = food_list

    reviews = PlatformReview.query.filter_by(restaurant_id=restaurant.id).order_by(PlatformReview.created_at.desc()).all()
    avg_rating = round(sum(rv.rating for rv in reviews) / len(reviews), 1) if reviews else None

    return render_template("public/restaurant_preview.html", restaurant=restaurant, country=country,
                            menu_data=menu_data, reviews=reviews, avg_rating=avg_rating)


@public_bp.route("/terms")
def terms():
    return render_template("public/terms.html")


@public_bp.route("/privacy")
def privacy():
    return render_template("public/privacy.html")


@public_bp.route("/refund-policy")
def refund_policy():
    return render_template("public/refund_policy.html")


@public_bp.route("/contact")
def contact():
    return render_template("public/contact.html")


# ---------- Public JSON API for the umbrella landing page (sellovateai.com) ----------

@public_bp.route("/api/public/settings")
def api_public_settings():
    settings = {s.key: s.value for s in PlatformSettings.query.all()}
    data = {
        "demo_video_url": settings.get("demo_video_url"),
        "facebook_url": settings.get("facebook_url"),
        "instagram_url": settings.get("instagram_url"),
        "youtube_url": settings.get("youtube_url"),
    }
    return _with_cors(jsonify(data))


@public_bp.route("/api/public/reviews")
def api_public_reviews():
    reviews = PlatformReview.query.order_by(PlatformReview.created_at.desc()).limit(12).all()
    data = []
    for rv in reviews:
        r = Restaurant.query.get(rv.restaurant_id)
        if not r or r.subscription_status != "active":
            continue
        data.append({
            "restaurant_name": r.name,
            "restaurant_address": r.address,
            "profile_image": f"https://restaurant.sellovateai.com/static/images/bg/{r.profile_image}" if r.profile_image else None,
            "rating": rv.rating,
            "review_text": rv.review_text,
        })
    return _with_cors(jsonify(data))


@public_bp.route("/api/public/restaurants")
def api_public_restaurants():
    """Powers the restaurant directory on the umbrella landing page
    (sellovateai.com) — reshuffled fresh on every request, since ?all=1
    is only used by the 'See All' view, which wants the full list."""
    show_all = request.args.get("all") == "1"
    active_restaurants = Restaurant.query.filter_by(subscription_status="active").all()

    if show_all:
        chosen = active_restaurants
    else:
        chosen = active_restaurants[:]
        random.shuffle(chosen)
        chosen = chosen[:6]

    data = []
    for r in chosen:
        card = _restaurant_card_data(r)
        card["joined_date"] = card["joined_date"].isoformat()
        card["profile_image"] = f"https://restaurant.sellovateai.com/static/images/bg/{r.profile_image}" if r.profile_image else None
        card["reviews"] = [{"rating": rv.rating, "review_text": rv.review_text} for rv in card["reviews"]]
        data.append(card)

    return _with_cors(jsonify({"restaurants": data, "total_active": len(active_restaurants)}))
