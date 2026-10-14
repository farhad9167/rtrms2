"""
Maps each seeded country to its primary IANA timezone, so bills/receipts show
the restaurant's local date & time instead of the server's UTC clock.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

COUNTRY_TIMEZONES = {
    "AF": "Asia/Kabul", "AM": "Asia/Yerevan", "AZ": "Asia/Baku", "BH": "Asia/Bahrain",
    "BD": "Asia/Dhaka", "BT": "Asia/Thimphu", "BN": "Asia/Brunei", "KH": "Asia/Phnom_Penh",
    "CN": "Asia/Shanghai", "CY": "Asia/Nicosia", "GE": "Asia/Tbilisi", "IN": "Asia/Kolkata",
    "ID": "Asia/Jakarta", "IR": "Asia/Tehran", "IQ": "Asia/Baghdad", "IL": "Asia/Jerusalem",
    "JP": "Asia/Tokyo", "JO": "Asia/Amman", "KZ": "Asia/Almaty", "KR": "Asia/Seoul",
    "KW": "Asia/Kuwait", "KG": "Asia/Bishkek", "LA": "Asia/Vientiane", "LB": "Asia/Beirut",
    "MY": "Asia/Kuala_Lumpur", "MV": "Indian/Maldives", "MN": "Asia/Ulaanbaatar", "MM": "Asia/Yangon",
    "NP": "Asia/Kathmandu", "OM": "Asia/Muscat", "PK": "Asia/Karachi", "PS": "Asia/Gaza",
    "PH": "Asia/Manila", "QA": "Asia/Qatar", "SA": "Asia/Riyadh", "SG": "Asia/Singapore",
    "LK": "Asia/Colombo", "SY": "Asia/Damascus", "TW": "Asia/Taipei", "TJ": "Asia/Dushanbe",
    "TH": "Asia/Bangkok", "TL": "Asia/Dili", "TR": "Europe/Istanbul", "TM": "Asia/Ashgabat",
    "AE": "Asia/Dubai", "UZ": "Asia/Tashkent", "VN": "Asia/Ho_Chi_Minh", "YE": "Asia/Aden",
}


def get_local_time(dt_utc, country_code):
    """dt_utc is a naive datetime known to be UTC (e.g. from datetime.utcnow()).
    Returns the equivalent local time for the restaurant's country, still naive
    (tzinfo stripped) so it prints/formats normally. Falls back to UTC if the
    country isn't in the map."""
    if dt_utc is None:
        return None
    tz_name = COUNTRY_TIMEZONES.get(country_code, "UTC")
    aware_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
    local = aware_utc.astimezone(ZoneInfo(tz_name))
    return local.replace(tzinfo=None)


def local_now(country_code):
    return get_local_time(datetime.utcnow(), country_code)
