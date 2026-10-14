import secrets
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class PlatformSettings(db.Model):
    """Global settings controlled by the super-admin (platform owner)."""
    __tablename__ = "platform_settings"
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text)


class CountryConfig(db.Model):
    """Per-country config: languages, currency, monthly fee. Editable from super-admin panel."""
    __tablename__ = "country_config"
    code = db.Column(db.String(4), primary_key=True)  # e.g. 'KR', 'BD'
    name = db.Column(db.String(64))
    lang_primary = db.Column(db.String(8))     # e.g. 'kr', 'bn'
    lang_secondary = db.Column(db.String(8), default="en")
    currency_symbol = db.Column(db.String(8))  # e.g. '₩', '৳'
    monthly_fee = db.Column(db.Integer)        # in the country's currency, whole units


class Restaurant(db.Model):
    __tablename__ = "restaurants"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    slug = db.Column(db.String(128), unique=True, nullable=False)
    country_code = db.Column(db.String(4), db.ForeignKey("country_config.code"))
    country_locked = db.Column(db.Boolean, default=True)  # super-admin can flip this off platform-wide
    owner_email = db.Column(db.String(128), unique=True, nullable=False)
    google_id = db.Column(db.String(128), unique=True)

    subscription_status = db.Column(db.String(24), default="pending_payment")
    subscription_expiry = db.Column(db.Date, nullable=True)
    notified_since = db.Column(db.DateTime, nullable=True)

    admin_username = db.Column(db.String(64), default="admin")
    admin_password_hash = db.Column(db.String(255))

    # Personal owner password — required on top of Google auth, on every new
    # device/session, so a shared/already-signed-in Google session alone
    # isn't enough to reach the dashboard.
    owner_password_hash = db.Column(db.String(255), nullable=True)

    address = db.Column(db.Text, default="")
    profile_image = db.Column(db.String(255), nullable=True)

    bg_image = db.Column(db.String(255), default="default.jpg")
    signboard_colors = db.Column(db.Text, default="#E2725B,#E8C872,#333333,#FDFBF7,#F5F0E6")
    popup_text = db.Column(db.Text, default="")
    kitchen_printer = db.Column(db.String(128))
    counter_printer = db.Column(db.String(128))

    table_count = db.Column(db.Integer, default=10)

    qr_expiry_minutes = db.Column(db.Integer, default=10)
    gps_enabled = db.Column(db.Boolean, default=False)
    gps_lat = db.Column(db.Float, nullable=True)
    gps_lng = db.Column(db.Float, nullable=True)
    gps_radius_m = db.Column(db.Integer, default=30)

    referral_code = db.Column(db.String(16), unique=True)
    referred_by_code = db.Column(db.String(16), nullable=True)

    daily_reset_hour = db.Column(db.Integer, default=0)  # 0-23, when the daily order-serial counter resets
    bill_footer_message = db.Column(db.Text, default="")  # shown on counter & customer bill copies (not kitchen)

    # Landing-page profile
    opening_time = db.Column(db.String(8), nullable=True)   # e.g. "10:00"
    closing_time = db.Column(db.String(8), nullable=True)   # e.g. "22:00"
    about_text = db.Column(db.Text, default="")

    # Owner's own bank details, shown to customers for in-app bill payment.
    # Separate from the platform's own bank details (which owners use to pay
    # US, the super-admin, their subscription).
    bank_payment_enabled = db.Column(db.Boolean, default=False)
    bank_name = db.Column(db.String(128), default="")
    bank_account_holder = db.Column(db.String(128), default="")
    bank_account_number = db.Column(db.String(64), default="")

    # Alternate login: an independent username+password, separate from the
    # device-verification password (owner_password_hash). Google signup stays
    # mandatory the first time; this is just an optional way back in after.
    username = db.Column(db.String(64), unique=True, nullable=True)
    username_password_hash = db.Column(db.String(255), nullable=True)

    # Owner-chosen dashboard/report language, independent of restaurant.country_code.
    # 'kr' or 'en' for now. Falls back to country-based default if not set.
    panel_language = db.Column(db.String(4), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_admin_password(self, raw_password):
        self.admin_password_hash = generate_password_hash(raw_password)

    def check_admin_password(self, raw_password):
        return check_password_hash(self.admin_password_hash, raw_password)

    def set_owner_password(self, raw_password):
        self.owner_password_hash = generate_password_hash(raw_password)

    def check_owner_password(self, raw_password):
        if not self.owner_password_hash:
            return False
        return check_password_hash(self.owner_password_hash, raw_password)

    def set_username_password(self, raw_password):
        self.username_password_hash = generate_password_hash(raw_password)

    def check_username_password(self, raw_password):
        if not self.username_password_hash:
            return False
        return check_password_hash(self.username_password_hash, raw_password)

    def is_active(self):
        if self.subscription_status != "active":
            return False
        if self.subscription_expiry and self.subscription_expiry < datetime.utcnow().date():
            return False
        return True

    def days_until_expiry(self):
        if not self.subscription_expiry:
            return None
        return (self.subscription_expiry - datetime.utcnow().date()).days

    @staticmethod
    def new_referral_code():
        return secrets.token_hex(4).upper()


class StaffUser(db.Model):
    __tablename__ = "staff_users"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    name = db.Column(db.String(64))
    username = db.Column(db.String(64))
    password_hash = db.Column(db.String(255))
    role = db.Column(db.String(24), default="waiter")  # waiter | manager

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def can_manage_menu(self):
        return self.role == "manager"


class MenuCategory(db.Model):
    __tablename__ = "menu_categories"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    name_primary = db.Column(db.String(128))
    name_secondary = db.Column(db.String(128))
    sort_order = db.Column(db.Integer, default=0)
    # When on, items in this category can define multiple size/portion tiers
    # (e.g. Small/Serves 2, Medium/Serves 3) instead of one flat price.
    multi_portion_enabled = db.Column(db.Boolean, default=False)


class MenuItem(db.Model):
    __tablename__ = "menu_items"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("menu_categories.id"))
    name_primary = db.Column(db.String(128))
    name_secondary = db.Column(db.String(128))
    price = db.Column(db.Float, nullable=False)  # ignored/base fallback when portion tiers exist
    image_url = db.Column(db.String(255), default="default.jpg")
    image_url_hd = db.Column(db.String(255), nullable=True)
    is_best_selling = db.Column(db.Boolean, default=False)
    in_stock = db.Column(db.Boolean, default=True)


class PortionTier(db.Model):
    """
    A size/serving-size option for a menu item (e.g. 'Small — Serves 2' at one
    price, 'Large — Serves 4' at another). Only used when the item's category
    has multi_portion_enabled turned on. A customer can add several different
    tiers of the same item to one order — each tier is its own cart line.
    """
    __tablename__ = "portion_tiers"
    id = db.Column(db.Integer, primary_key=True)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"), nullable=False)
    label = db.Column(db.String(64))           # e.g. "Small", "Medium", "Large"
    serves_count = db.Column(db.Integer, nullable=True)  # e.g. 2, 3, 4 — optional
    price = db.Column(db.Float, nullable=False)
    sort_order = db.Column(db.Integer, default=0)


class DailyOffer(db.Model):
    __tablename__ = "daily_offers"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    menu_item_id = db.Column(db.Integer, db.ForeignKey("menu_items.id"), nullable=False)
    # If set, the discount applies to just this one portion tier instead of
    # the whole item (e.g. 10% off only the Large size). Leave blank for a
    # plain (non-tiered) item, or to discount every tier of a tiered item.
    portion_tier_id = db.Column(db.Integer, db.ForeignKey("portion_tiers.id"), nullable=True)
    day_of_week = db.Column(db.Integer)
    discount_percent = db.Column(db.Integer, default=0)
    highlight_as_best_seller = db.Column(db.Boolean, default=False)


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    items = db.Column(db.Text)
    total_price = db.Column(db.Float)
    table_no = db.Column(db.String(64))
    dining_mode = db.Column(db.String(24))
    status = db.Column(db.String(24), default="Pending")
    payment_method = db.Column(db.String(24), default="N/A")
    print_failed = db.Column(db.Boolean, default=False)
    daily_serial = db.Column(db.Integer, nullable=True)   # resets per restaurant.daily_reset_hour
    business_date = db.Column(db.Date, nullable=True)      # the "business day" this order belongs to
    special_instructions = db.Column(db.Text, nullable=True)  # one whole-order note, e.g. "No onion, extra cheese"

    # In-app bill payment (only used when restaurant.bank_payment_enabled is on)
    is_paid = db.Column(db.Boolean, default=False)
    payment_sender_name = db.Column(db.String(128), nullable=True)
    payment_sender_number = db.Column(db.String(64), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class StaffCall(db.Model):
    """A 'Call Staff' press from the customer menu. Owner/staff dashboards
    poll for undismissed calls and read them aloud (queued, repeating) until
    someone dismisses it."""
    __tablename__ = "staff_calls"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    table_no = db.Column(db.String(64))
    dismissed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class FeatureFlag(db.Model):
    __tablename__ = "feature_flags"
    id = db.Column(db.Integer, primary_key=True)
    feature_key = db.Column(db.String(64), nullable=False)
    scope = db.Column(db.String(16), default="global")
    scope_value = db.Column(db.String(64), nullable=True)
    enabled = db.Column(db.Boolean, default=True)
    active_from = db.Column(db.DateTime, nullable=True)
    active_until = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class PaymentRequest(db.Model):
    __tablename__ = "payment_requests"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    sender_name = db.Column(db.String(128))
    sender_number = db.Column(db.String(64))
    transaction_note = db.Column(db.Text)
    payment_method = db.Column(db.String(24), default="manual_bank")
    months = db.Column(db.Integer, default=1)
    promo_code = db.Column(db.String(32), nullable=True)
    amount_quoted = db.Column(db.Float, nullable=True)
    status = db.Column(db.String(24), default="pending")
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)


class PromoCode(db.Model):
    __tablename__ = "promo_codes"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    discount_percent = db.Column(db.Integer, default=0)
    min_months = db.Column(db.Integer, default=1)
    country_code = db.Column(db.String(4), nullable=True)
    active = db.Column(db.Boolean, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)


class PlatformReview(db.Model):
    __tablename__ = "platform_reviews"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    rating = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CountrySalesCache(db.Model):
    """Total completed-sales amount per country, shown on the public landing
    page. Recomputed at most once every 24 hours (see utils.sales_stats) —
    real orders from restaurants, not a live query on every page view."""
    __tablename__ = "country_sales_cache"
    country_code = db.Column(db.String(4), primary_key=True)
    total_amount = db.Column(db.Float, default=0)
    computed_at = db.Column(db.DateTime, default=datetime.utcnow)


class BackupLog(db.Model):
    __tablename__ = "backup_logs"
    id = db.Column(db.Integer, primary_key=True)
    restaurant_id = db.Column(db.Integer, db.ForeignKey("restaurants.id"), nullable=False)
    status = db.Column(db.String(16), default="success")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
