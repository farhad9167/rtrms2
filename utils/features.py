"""
Feature flag resolution.

Usage in a route or template:
    from utils.features import is_feature_enabled
    if is_feature_enabled('out_of_stock_toggle', restaurant=restaurant):
        ...

Resolution order (most specific wins): restaurant-level flag > country-level flag
> global flag > default (True — features are ON unless explicitly turned off,
so a brand-new feature doesn't silently disappear for existing restaurants).
"""
from datetime import datetime
from models import FeatureFlag


def _flag_is_currently_active(flag):
    if not flag.enabled:
        return False
    now = datetime.utcnow()
    if flag.active_from and now < flag.active_from:
        return False
    if flag.active_until and now > flag.active_until:
        return False
    return True


def is_feature_enabled(feature_key, restaurant=None):
    if restaurant is not None:
        r_flag = FeatureFlag.query.filter_by(
            feature_key=feature_key, scope="restaurant", scope_value=str(restaurant.id)
        ).first()
        if r_flag is not None:
            return _flag_is_currently_active(r_flag)

        if restaurant.country_code:
            c_flag = FeatureFlag.query.filter_by(
                feature_key=feature_key, scope="country", scope_value=restaurant.country_code
            ).first()
            if c_flag is not None:
                return _flag_is_currently_active(c_flag)

    g_flag = FeatureFlag.query.filter_by(feature_key=feature_key, scope="global").first()
    if g_flag is not None:
        return _flag_is_currently_active(g_flag)

    return True  # no flag set anywhere = on by default


# Central registry of all toggleable features, shown in the super-admin
# Feature Control page. Add a new (key, label) pair here whenever a new
# togglable feature is built — the admin UI reads from this list.
FEATURE_REGISTRY = [
    ("staff_roles", "Staff Roles & Permissions"),
    ("out_of_stock_toggle", "Out of Stock Item Toggle"),
    ("order_status_tracking", "Customer-facing Order Status Tracking"),
    ("referral_system", "Referral / Promo Discount System"),
    ("analytics_dashboard", "Advanced Analytics Dashboard"),
    ("cloud_backup", "Google Drive Auto-Backup"),
    ("qr_time_expiry", "QR Link Time Expiry"),
    ("gps_radius_check", "GPS Radius Order Verification"),
    ("country_autolock", "Lock Owner Country to IP-detected Value"),
]
