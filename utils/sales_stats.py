"""
Country-wise total sales, shown on the public landing page. Only counts
real completed/paid orders, refreshed at most once every 24 hours so the
landing page never has to run a heavy aggregate query on every visit.
"""
from datetime import datetime, timedelta
from models import db, CountrySalesCache, Order, Restaurant, CountryConfig

CACHE_LIFETIME = timedelta(hours=24)


def get_country_sales():
    """Returns a list of dicts like {code, name, currency_symbol, total_amount}
    — one entry per country that has at least one real completed sale.
    Countries with zero completed sales are left out entirely."""
    newest = db.session.query(db.func.max(CountrySalesCache.computed_at)).scalar()
    is_stale = newest is None or (datetime.utcnow() - newest) > CACHE_LIFETIME
    if is_stale:
        _recompute_all()

    rows = CountrySalesCache.query.filter(CountrySalesCache.total_amount > 0).all()
    results = []
    for row in rows:
        country = CountryConfig.query.get(row.country_code)
        if not country:
            continue
        results.append({
            "code": row.country_code,
            "name": country.name,
            "currency_symbol": country.currency_symbol,
            "total_amount": row.total_amount,
        })
    results.sort(key=lambda r: -r["total_amount"])
    return results


def _recompute_all():
    country_codes = [c.code for c in CountryConfig.query.all()]
    for code in country_codes:
        total = (
            db.session.query(db.func.coalesce(db.func.sum(Order.total_price), 0.0))
            .join(Restaurant, Order.restaurant_id == Restaurant.id)
            .filter(Restaurant.country_code == code)
            .filter(db.or_(Order.status == "Completed", Order.is_paid == True))  # noqa: E712
            .scalar()
        )
        existing = CountrySalesCache.query.get(code)
        if existing:
            existing.total_amount = total
            existing.computed_at = datetime.utcnow()
        else:
            db.session.add(CountrySalesCache(country_code=code, total_amount=total,
                                              computed_at=datetime.utcnow()))
    db.session.commit()
