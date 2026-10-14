"""
Run once to populate initial platform data:
  - country config (Korea, Bangladesh) with your monthly fees
  - platform bank details (for subscription verification)
  - two example restaurants (one per country) with real menu items,
    so you can see the whole flow working end-to-end.

Usage: python seed.py
"""
from datetime import date
from app import create_app
from models import (db, CountryConfig, PlatformSettings, Restaurant,
                     MenuCategory, MenuItem, FeatureFlag)

app = create_app()

with app.app_context():
    # ---------- Country config ----------
    # Korea and Bangladesh keep the exact fees you set. Every other Asian
    # country is seeded with a rough placeholder fee (~$15 USD equivalent,
    # using approximate exchange rates) so the dropdown isn't empty — these
    # placeholder fees MUST be reviewed and adjusted per country from the
    # Super Admin → Platform Settings page before real owners sign up there.
    if not CountryConfig.query.get("KR"):
        db.session.add(CountryConfig(
            code="KR", name="Korea", lang_primary="kr", lang_secondary="en",
            currency_symbol="₩", monthly_fee=150000
        ))
    if not CountryConfig.query.get("BD"):
        db.session.add(CountryConfig(
            code="BD", name="Bangladesh", lang_primary="bn", lang_secondary="en",
            currency_symbol="৳", monthly_fee=5000
        ))

    # code, name, lang, currency symbol, placeholder monthly fee (~$15 USD equiv.)
    OTHER_ASIAN_COUNTRIES = [
        ("AF", "Afghanistan", "fa", "؋", 1200),
        ("AM", "Armenia", "hy", "֏", 6000),
        ("AZ", "Azerbaijan", "az", "₼", 25),
        ("BH", "Bahrain", "ar", ".د.ب", 6),
        ("BT", "Bhutan", "dz", "Nu.", 1250),
        ("BN", "Brunei", "ms", "$", 20),
        ("KH", "Cambodia", "km", "៛", 60000),
        ("CN", "China", "zh", "¥", 105),
        ("CY", "Cyprus", "el", "€", 14),
        ("GE", "Georgia", "ka", "₾", 40),
        ("IN", "India", "hi", "₹", 1250),
        ("ID", "Indonesia", "id", "Rp", 230000),
        ("IR", "Iran", "fa", "﷼", 630000),
        ("IQ", "Iraq", "ar", "ع.د", 19000),
        ("IL", "Israel", "he", "₪", 55),
        ("JP", "Japan", "ja", "¥", 2200),
        ("JO", "Jordan", "ar", "د.ا", 11),
        ("KZ", "Kazakhstan", "kk", "₸", 6800),
        ("KW", "Kuwait", "ar", "د.ك", 5),
        ("KG", "Kyrgyzstan", "ky", "с", 1300),
        ("LA", "Laos", "lo", "₭", 310000),
        ("LB", "Lebanon", "ar", "ل.ل", 225000),
        ("MY", "Malaysia", "ms", "RM", 65),
        ("MV", "Maldives", "dv", "Rf", 230),
        ("MN", "Mongolia", "mn", "₮", 52000),
        ("MM", "Myanmar", "my", "K", 31000),
        ("NP", "Nepal", "ne", "रू", 2000),
        ("OM", "Oman", "ar", "ر.ع.", 6),
        ("PK", "Pakistan", "ur", "₨", 4200),
        ("PS", "Palestine", "ar", "₪", 55),
        ("PH", "Philippines", "tl", "₱", 850),
        ("QA", "Qatar", "ar", "ر.ق", 55),
        ("SA", "Saudi Arabia", "ar", "ر.س", 56),
        ("SG", "Singapore", "en", "$", 20),
        ("LK", "Sri Lanka", "si", "Rs", 4700),
        ("SY", "Syria", "ar", "ل.س", 13000),
        ("TW", "Taiwan", "zh", "NT$", 470),
        ("TJ", "Tajikistan", "tg", "ЅМ", 165),
        ("TH", "Thailand", "th", "฿", 530),
        ("TL", "Timor-Leste", "pt", "$", 15),
        ("TR", "Turkey", "tr", "₺", 500),
        ("TM", "Turkmenistan", "tk", "m", 52),
        ("AE", "United Arab Emirates", "ar", "د.إ", 55),
        ("UZ", "Uzbekistan", "uz", "so'm", 190000),
        ("VN", "Vietnam", "vi", "₫", 370000),
        ("YE", "Yemen", "ar", "﷼", 3750),
    ]
    for code, name, lang, symbol, fee in OTHER_ASIAN_COUNTRIES:
        if not CountryConfig.query.get(code):
            db.session.add(CountryConfig(
                code=code, name=name, lang_primary=lang, lang_secondary="en",
                currency_symbol=symbol, monthly_fee=fee
            ))
    db.session.commit()

    # ---------- Country auto-lock: OFF, platform-wide ----------
    if not FeatureFlag.query.filter_by(feature_key="country_autolock", scope="global").first():
        db.session.add(FeatureFlag(feature_key="country_autolock", scope="global", enabled=False))
        db.session.commit()

    # ---------- Remaining Asian countries ----------
    # Fee left at 0 (placeholder) for every country below except KR/BD, since no
    # real pricing was given for them — set the real monthly fee for each from
    # Super Admin -> Platform Settings before accepting live payments from that country.
    other_asian_countries = [
        ("AF", "Afghanistan", "ps", "؋"), ("AM", "Armenia", "hy", "֏"),
        ("AZ", "Azerbaijan", "az", "₼"), ("BH", "Bahrain", "ar", ".د.ب"),
        ("BT", "Bhutan", "dz", "Nu."), ("BN", "Brunei", "ms", "B$"),
        ("KH", "Cambodia", "km", "៛"), ("CN", "China", "zh", "¥"),
        ("CY", "Cyprus", "el", "€"), ("GE", "Georgia", "ka", "₾"),
        ("IN", "India", "hi", "₹"), ("ID", "Indonesia", "id", "Rp"),
        ("IR", "Iran", "fa", "﷼"), ("IQ", "Iraq", "ar", "ع.د"),
        ("IL", "Israel", "he", "₪"), ("JP", "Japan", "ja", "¥"),
        ("JO", "Jordan", "ar", "د.ا"), ("KZ", "Kazakhstan", "kk", "₸"),
        ("KW", "Kuwait", "ar", "د.ك"), ("KG", "Kyrgyzstan", "ky", "с"),
        ("LA", "Laos", "lo", "₭"), ("LB", "Lebanon", "ar", "ل.ل"),
        ("MY", "Malaysia", "ms", "RM"), ("MV", "Maldives", "dv", "Rf"),
        ("MN", "Mongolia", "mn", "₮"), ("MM", "Myanmar", "my", "K"),
        ("NP", "Nepal", "ne", "रू"), ("OM", "Oman", "ar", "ر.ع."),
        ("PK", "Pakistan", "ur", "₨"), ("PH", "Philippines", "tl", "₱"),
        ("QA", "Qatar", "ar", "ر.ق"), ("SA", "Saudi Arabia", "ar", "﷼"),
        ("SG", "Singapore", "en", "S$"), ("LK", "Sri Lanka", "si", "Rs"),
        ("SY", "Syria", "ar", "£S"), ("TW", "Taiwan", "zh", "NT$"),
        ("TJ", "Tajikistan", "tg", "ЅМ"), ("TH", "Thailand", "th", "฿"),
        ("TR", "Turkey", "tr", "₺"), ("TM", "Turkmenistan", "tk", "m"),
        ("AE", "UAE", "ar", "د.إ"), ("UZ", "Uzbekistan", "uz", "лв"),
        ("VN", "Vietnam", "vi", "₫"), ("YE", "Yemen", "ar", "﷼"),
    ]
    for code, name, lang_primary, currency in other_asian_countries:
        if not CountryConfig.query.get(code):
            db.session.add(CountryConfig(
                code=code, name=name, lang_primary=lang_primary, lang_secondary="en",
                currency_symbol=currency, monthly_fee=0
            ))
    db.session.commit()

    # ---------- Country auto-lock: turned OFF platform-wide per your request ----------
    from models import FeatureFlag
    existing_flag = FeatureFlag.query.filter_by(feature_key="country_autolock", scope="global").first()
    if not existing_flag:
        db.session.add(FeatureFlag(feature_key="country_autolock", scope="global", enabled=False))
        db.session.commit()

    # ---------- Platform settings (bank details for manual subscription payment) ----------
    def set_setting(key, value):
        row = PlatformSettings.query.get(key)
        if not row:
            db.session.add(PlatformSettings(key=key, value=value))
        else:
            row.value = value

    set_setting("platform_name", "RTRMS")  # change anytime from super-admin panel
    set_setting("bank_details_image", "bank_passbook.jpg")
    set_setting("bank_details_text",
                "Gwangju Bank (광주은행)\n"
                "Account holder: HOSSAIN MD FARHAD\n"
                "Account number: 1121-030-959562\n"
                "Account type: Savings")
    db.session.commit()

    # ---------- Example restaurant 1: Bangladesh ----------
    if not Restaurant.query.filter_by(slug="menu-restaurant-khulna").first():
        r_bd = Restaurant(
            name="Me'nu Restaurant",
            slug="menu-restaurant-khulna",
            country_code="BD",
            owner_email="demo-owner-bd@example.com",
            google_id="demo-google-id-bd",
            subscription_status="active",
            subscription_expiry=date(2026, 12, 31),
            address="323, BEDIC Road, Khalishpur, Khulna-9000, Bangladesh",
        )
        r_bd.set_admin_password("changeme")
        r_bd.set_owner_password("changeme")
        db.session.add(r_bd)
        db.session.commit()

        cat_biryani = MenuCategory(restaurant_id=r_bd.id, name_primary="বিরিয়ানী", name_secondary="Biryani", sort_order=1)
        cat_snacks = MenuCategory(restaurant_id=r_bd.id, name_primary="নাস্তা", name_secondary="Snacks", sort_order=2)
        cat_drinks = MenuCategory(restaurant_id=r_bd.id, name_primary="পানীয়", name_secondary="Drinks", sort_order=3)
        db.session.add_all([cat_biryani, cat_snacks, cat_drinks])
        db.session.commit()

        items_bd = [
            (cat_biryani, "গরুর বিরিয়ানী (হাফ)", "Beef Biryani (Half)", 130),
            (cat_biryani, "গরুর বিরিয়ানী (ফুল)", "Beef Biryani (Full)", 255),
            (cat_biryani, "খাসীর বিরিয়ানী (হাফ)", "Mutton Biryani (Half)", 130),
            (cat_biryani, "মুরগীর বিরিয়ানী (হাফ)", "Chicken Biryani (Half)", 120),
            (cat_biryani, "মুরগীর বিরিয়ানী (ফুল)", "Chicken Biryani (Full)", 240),
            (cat_snacks, "হালিম", "Haleem", 35),
            (cat_snacks, "চটপটি", "Chotpoti", 20),
            (cat_snacks, "ফুচকা", "Fuchka", 20),
            (cat_snacks, "কাবাব", "Kabab", 20),
            (cat_drinks, "লাচ্ছি", "Lassi", 35),
            (cat_drinks, "ফালুদা", "Faluda", 45),
            (cat_drinks, "বুরহানী (প্রতি গ্লাস)", "Borhani (per glass)", 20),
        ]
        for cat, name_bn, name_en, price in items_bd:
            db.session.add(MenuItem(restaurant_id=r_bd.id, category_id=cat.id,
                                     name_primary=name_bn, name_secondary=name_en, price=price))
        db.session.commit()
        print(f"Created BD demo restaurant: /r/{r_bd.slug}/menu")

    # ---------- Example restaurant 2: Korea ----------
    if not Restaurant.query.filter_by(slug="hansikdang").first():
        r_kr = Restaurant(
            name="한식당",
            slug="hansikdang",
            country_code="KR",
            owner_email="demo-owner-kr@example.com",
            google_id="demo-google-id-kr",
            subscription_status="active",
            subscription_expiry=date(2026, 12, 31),
            address="Seoul, South Korea",
        )
        r_kr.set_admin_password("changeme")
        r_kr.set_owner_password("changeme")
        db.session.add(r_kr)
        db.session.commit()

        cat_meal = MenuCategory(restaurant_id=r_kr.id, name_primary="식사류", name_secondary="Meals", sort_order=1)
        cat_noodle = MenuCategory(restaurant_id=r_kr.id, name_primary="면류", name_secondary="Noodles", sort_order=2)
        cat_drink = MenuCategory(restaurant_id=r_kr.id, name_primary="음료", name_secondary="Drinks", sort_order=3)
        db.session.add_all([cat_meal, cat_noodle, cat_drink])
        db.session.commit()

        items_kr = [
            (cat_meal, "비빔밥", "Bibimbap", 12000),
            (cat_meal, "떡볶이", "Stir-fried Rice Cake", 8000),
            (cat_meal, "김치볶음밥", "Kimchi Fried Rice", 9000),
            (cat_meal, "갈비구이", "Grilled Marinated Galbi", 18000),
            (cat_meal, "김치전", "Kimchi Pancake", 13000),
            (cat_meal, "해물파전", "Seafood & Green Onion Pancake", 15000),
            (cat_noodle, "라면", "Ramen", 5000),
            (cat_noodle, "냉면", "Cold Noodles", 7000),
            (cat_noodle, "멸치국수", "Anchovy Noodle Soup", 8000),
            (cat_drink, "탄산음료", "Soda", 3000),
            (cat_drink, "오렌지 주스", "Orange Juice", 3000),
        ]
        for cat, name_kr, name_en, price in items_kr:
            db.session.add(MenuItem(restaurant_id=r_kr.id, category_id=cat.id,
                                     name_primary=name_kr, name_secondary=name_en, price=price))
        db.session.commit()
        print(f"Created KR demo restaurant: /r/{r_kr.slug}/menu")

    print("Seeding complete.")
