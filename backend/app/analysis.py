import re
from statistics import median
from .models import Filters, Listing


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', (value or '').lower())


def match_listing(car: Listing, filters: Filters):
    unknown = []
    wanted_location = normalized(filters.location)
    actual_location = normalized(car.location)
    if wanted_location in ('bengaluru', 'bangalore'):
        actual_location = actual_location.replace('bangalore', 'bengaluru')
        wanted_location = 'bengaluru'
    if not actual_location:
        unknown.append('location')
    elif wanted_location not in actual_location:
        return False, []
    checks = [('price', filters.min_price, filters.max_price), ('year', filters.min_year, filters.max_year),
              ('km', None, filters.max_km), ('owners', None, filters.max_owners)]
    for field, lo, hi in checks:
        if lo is None and hi is None:
            continue
        value = getattr(car, field)
        if value is None:
            unknown.append(field)
        elif (lo is not None and value < lo) or (hi is not None and value > hi):
            return False, []
    for field in ('make', 'model', 'fuel', 'transmission'):
        target = getattr(filters, field)
        if not target:
            continue
        value = getattr(car, field)
        if not value:
            unknown.append(field)
        elif field in ('fuel', 'transmission'):
            if normalized(value) != normalized(target):
                return False, []
        elif normalized(target) not in normalized(value):
            return False, []
    return (not unknown or filters.include_unknown), unknown


def completeness(car):
    return [k for k in ('price', 'make', 'model', 'year', 'km', 'fuel', 'transmission', 'owners', 'description')
            if getattr(car, k) in (None, '')]


def price_comparisons(cars):
    result = {}
    for c in cars:
        peers = []
        essential = ('price', 'make', 'model', 'year', 'km', 'fuel', 'transmission')
        if all(c.get(k) not in (None, '', 0) for k in essential):
            for other in cars:
                if other['id'] == c['id'] or not all(other.get(k) not in (None, '', 0) for k in essential):
                    continue
                if not all(normalized(c[k]) == normalized(other[k]) for k in ('make', 'model', 'fuel', 'transmission')):
                    continue
                if abs(c['year'] - other['year']) > 2 or abs(c['km'] - other['km']) > max(25000, c['km'] * .35):
                    continue
                if c.get('variant') and other.get('variant') and normalized(c['variant']) != normalized(other['variant']):
                    continue
                peers.append(other)
        item = dict(count=len(peers), listing_ids=[p['id'] for p in peers], median=None, difference_percent=None,
                    basis='Retrieved asking prices; subject excluded. Same make/model/fuel/transmission, ±2 years, similar mileage; variant matched where known.')
        if len(peers) >= 3:
            item['median'] = median([p['price'] for p in peers])
            item['difference_percent'] = round((c['price'] / item['median'] - 1) * 100, 1)
        result[c['id']] = item
    return result
