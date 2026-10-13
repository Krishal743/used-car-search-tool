"""Read public OLX pages. No private API, login or unattended crawling."""
import hashlib
import json
import os
import re
from urllib.parse import quote, urljoin, urlparse, parse_qsl, urlencode, urlunparse
import httpx
from bs4 import BeautifulSoup
from ..config import IMAGES
from ..models import Filters, Listing, safe_olx_url
from ..store import now
from ..analysis import completeness

BENGALURU = 'https://www.olx.in/bengaluru_g4058803/cars_c84'
IMAGE_HOSTS = {'apollo.olx.in', 'images.olx.in'}
MAKES = ['Maruti Suzuki', 'Land Rover', 'Mercedes-Benz', 'Volkswagen', 'Mahindra', 'Hyundai',
         'Toyota', 'Renault', 'Honda', 'Skoda', 'Tata', 'Ford', 'Kia', 'Nissan', 'BMW', 'Audi',
         'Chevrolet', 'MG', 'Jeep', 'Volvo', 'Porsche', 'Lexus', 'Fiat', 'Citroen', 'Mini']


class SourceError(Exception):
    pass


def request_failure(error):
    detail = str(error.__cause__ or error).lower()
    if isinstance(error, httpx.HTTPStatusError):
        return f'OLX returned HTTP {error.response.status_code}. Open the search page in your browser to check access.'
    if 'name resolution' in detail or 'name or service not known' in detail or 'nodename nor servname' in detail:
        return 'DNS could not resolve OLX. Check that this computer can open www.olx.in in your browser.'
    if 'certificate verify failed' in detail:
        return 'The OLX HTTPS certificate could not be verified. Check this computer’s clock and network certificate settings.'
    if isinstance(error, httpx.TimeoutException):
        return 'The connection to OLX timed out. Check connectivity and try again.'
    return f'OLX request failed ({type(error).__name__}: {str(error)[:180]}). Open the search page in your browser to check access.'


def browser_failure(error):
    detail = str(error)
    lower = detail.lower()
    if "executable doesn't exist" in lower or 'browser not found' in lower:
        return 'Playwright Chromium is missing. Run .venv/bin/python -m playwright install chromium.'
    if 'host system is missing dependencies' in lower or 'missing libraries' in lower:
        return 'Playwright Chromium needs Linux libraries. Run .venv/bin/python -m playwright install --with-deps chromium.'
    if 'err_name_not_resolved' in lower:
        return 'Chromium could not resolve www.olx.in. Check DNS or open the search page in your browser.'
    if 'err_cert_' in lower:
        return 'Chromium rejected the OLX HTTPS certificate. Check this computer’s clock and network certificate settings.'
    if 'err_connection_' in lower or 'err_timed_out' in lower:
        return 'Chromium could not connect to OLX. Check connectivity and open the search page in your browser.'
    if 'timeout' in lower:
        return 'Chromium timed out while loading OLX. Try opening the search page in your browser.'
    first_line = detail.splitlines()[0][:180]
    return f'Chromium could not load OLX ({type(error).__name__}: {first_line}).'


def safe_image(url):
    try:
        p = urlparse(url)
        return p.scheme == 'https' and p.hostname in IMAGE_HOSTS and not p.username and not p.password and p.port in (None, 443)
    except (ValueError, TypeError):
        return False


def search_url(filters: Filters):
    base = filters.search_url or BENGALURU
    if not filters.search_url and filters.location.lower() not in ('bengaluru', 'bangalore'):
        raise SourceError('For another region, paste its public OLX Cars search URL in Advanced filters. No search was run in Bengaluru instead.')
    safe_olx_url(base)
    if not filters.search_url:
        query = ' '.join(x.strip() for x in (filters.make, filters.model) if x.strip())
        if query:
            base += '/q-' + quote(query.replace(' ', '-'), safe='-')
    return base


def number(value):
    if isinstance(value, dict):
        for k in ('raw', 'amount', 'value', 'display'):
            if k in value:
                n = number(value[k])
                if n is not None:
                    return n
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return None
    match = re.search(r'\d[\d,]*(?:\.\d+)?', value)
    if not match:
        return None
    amount = float(match[0].replace(',', ''))
    if re.search(r'\b(lakh|lac|lakhs|lacs)\b', value, re.I):
        amount *= 100000
    elif re.search(r'\b(crore|cr)\b', value, re.I):
        amount *= 10000000
    return int(amount)


def scalar(value):
    if isinstance(value, dict):
        for k in ('value', 'name', 'label', 'display', 'raw'):
            if k in value:
                return scalar(value[k])
        return ''
    return str(value) if value is not None else ''


def page_objects(soup):
    decoder = json.JSONDecoder()
    for script in soup.find_all('script'):
        text = script.string or script.get_text()
        if not text or len(text) > 12_000_000:
            continue
        if script.get('type') in ('application/ld+json', 'application/json') or script.get('id') == '__NEXT_DATA__':
            try:
                yield json.loads(text)
            except ValueError:
                pass
        else:
            for match in re.finditer(r'(?:__PRELOADED_STATE__|__INITIAL_STATE__|__NEXT_DATA__)\s*=\s*', text):
                try:
                    obj, _ = decoder.raw_decode(text[match.end():].lstrip())
                    yield obj
                except ValueError:
                    pass


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from walk(value)


def listing_links(html, base):
    soup = BeautifulSoup(html, 'html.parser')
    urls = []
    for anchor in soup.select('a[href]'):
        href = urljoin(base, anchor['href']).split('#')[0]
        if '/item/' in urlparse(href).path and re.search(r'(?:iid-|/)(\d{7,})', href):
            try:
                safe_olx_url(href)
                urls.append(href)
            except ValueError:
                pass
    for root in page_objects(soup):
        for obj in walk(root):
            for key in ('url', 'share_url', 'urlPath', 'relative_url'):
                if isinstance(obj.get(key), str):
                    href = urljoin(base, obj[key])
                    if '/item/' in urlparse(href).path:
                        try:
                            safe_olx_url(href)
                            urls.append(href)
                        except ValueError:
                            pass
    return list(dict.fromkeys(urls))


def next_page(html, base, page):
    soup = BeautifulSoup(html, 'html.parser')
    for a in soup.select('a[href]'):
        if a.get('rel') == ['next'] or a.get_text(' ', strip=True).lower() == 'next':
            target = urljoin(base, a['href'])
            try:
                safe_olx_url(target)
                return target
            except ValueError:
                continue
    # OLX public category pages expose pagination. Stop if it repeats IDs.
    p = urlparse(base)
    params = dict(parse_qsl(p.query))
    params['page'] = str(page + 1)
    return urlunparse(p._replace(query=urlencode(params)))


def has_no_results(html):
    text = BeautifulSoup(html, 'html.parser').get_text(' ', strip=True).lower()
    return any(x in text for x in ('no results found', 'no ads found', 'no listings found', 'we couldn’t find', "we couldn't find", 'no results matching'))


def parse_listing(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    id_match = re.search(r'iid-(\d+)', url) or re.search(r'/(\d{7,})(?:\D|$)', url)
    raw_id = id_match[1] if id_match else None
    if not raw_id:
        raise SourceError('The page does not contain a recognized OLX listing ID.')
    data = {}
    objects = [obj for root in page_objects(soup) for obj in walk(root)]
    candidates = [obj for obj in objects if str(obj.get('id', '')) == raw_id and ('title' in obj or 'description' in obj)]
    if candidates:
        data = max(candidates, key=lambda x: len(json.dumps(x)))
    else:
        products = [o for o in objects if o.get('@type') in ('Product', 'Vehicle', 'Car')]
        if products:
            data = products[0]
    params = {}
    for p in data.get('parameters', []) if isinstance(data.get('parameters'), list) else []:
        if not isinstance(p, dict):
            continue
        key = str(p.get('key') or p.get('name') or p.get('label') or '').lower().replace(' ', '_')
        params[key] = scalar(p.get('value_name') or p.get('value') or p.get('formatted_value'))
    attrs = data.get('attributes', {})
    if isinstance(attrs, dict):
        params.update({str(k).lower(): scalar(v) for k, v in attrs.items()})
    # Semantic selectors complement the page state without depending on hashed CSS classes.
    for element in soup.select('[data-aut-id]'):
        key = element.get('data-aut-id', '')
        if key in ('itemBrand', 'itemMake', 'itemModel', 'itemYear', 'itemFuel', 'itemTransmission', 'itemMileage', 'itemOwners'):
            params[key.removeprefix('item').lower()] = element.get_text(' ', strip=True)
    body = soup.get_text('\n', strip=True)
    def label(*names):
        for name in names:
            match = re.search(r'(?:^|\n)' + re.escape(name) + r'\s*[:：]?\s*\n?([^\n]+)', body, re.I)
            if match and match[1].strip() not in ('--', '-'):
                return match[1].strip()
        return ''
    def param(*keys):
        for key in keys:
            if params.get(key):
                return params[key]
            if data.get(key):
                return scalar(data[key])
        return ''
    def aut(name):
        node = soup.select_one(f'[data-aut-id="{name}"]')
        return node.get_text(' ', strip=True) if node else ''
    title = scalar(data.get('title') or data.get('name')) or aut('itemTitle')
    h1 = soup.find('h1')
    title = title or (h1.get_text(' ', strip=True) if h1 else '')
    if not title:
        raise SourceError('OLX did not expose a readable listing title. The page may be removed or access may be blocked.')
    offers = data.get('offers', {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = number(data.get('price')) or number(offers.get('price') if isinstance(offers, dict) else None) or number(aut('itemPrice'))
    if price is None:
        price_match = re.search(r'₹\s*([\d,]+)', body)
        price = number(price_match[1]) if price_match else None
    description = scalar(data.get('description')) or aut('itemDescription')
    if description:
        description = BeautifulSoup(description, 'html.parser').get_text('\n', strip=True)
    else:
        heading = soup.find(lambda tag: tag.name in ('h2', 'h3', 'h4', 'div', 'span') and tag.get_text(strip=True).lower() == 'description')
        if heading:
            parts = []
            for sibling in heading.next_siblings:
                if getattr(sibling, 'name', None) in ('h1', 'h2', 'h3', 'h4'):
                    break
                text = sibling.get_text('\n', strip=True) if hasattr(sibling, 'get_text') else str(sibling).strip()
                if text:
                    parts.append(text)
            description = '\n'.join(parts)
        if not description:
            desc_match = re.search(r'\nDescription\n(.+?)(?:\n₹|\nPosted by|\nAD ID|\nReport this ad|$)', body, re.I | re.S)
            description = desc_match[1] if desc_match else ''
    make = param('make', 'brand') or label('Make', 'Brand')
    if not make:
        make = next((m for m in MAKES if m.lower().replace('-', ' ') in title.lower().replace('-', ' ')), '')
    model = param('model') or label('Model')
    if not model and make:
        remainder = re.sub(re.escape(make), '', title, count=1, flags=re.I).strip(' -')
        model = re.split(r'\s*\(?\b(?:19|20)\d{2}\b', remainder)[0].strip(' (),-')
    year = number(param('year') or label('Year'))
    if not year:
        year_match = re.search(r'\b(?:19|20)\d{2}\b', title)
        year = int(year_match[0]) if year_match else None
    km = number(param('mileage', 'km_driven', 'km', 'mileage_km') or label('KM driven', 'Odometer reading', 'Mileage'))
    if km is None:
        km_match = re.search(r'([\d,]+)\s*km\b', body, re.I)
        km = number(km_match[1]) if km_match else None
    owners = number(param('owners', 'no_of_owners', 'owner') or label('Owner', 'No. of Owners'))
    fuel = param('fuel', 'fuel_type') or label('Fuel', 'Fuel Type')
    transmission = param('transmission') or label('Transmission')
    if not fuel:
        fuel = next((x for x in ['Petrol', 'Diesel', 'Electric', 'CNG', 'Hybrid', 'LPG'] if re.search(r'\b'+x+r'\b', body, re.I)), '')
    if not transmission:
        transmission = next((x for x in ['Manual', 'Automatic'] if re.search(r'\b'+x+r'\b', body, re.I)), '')
    loc = data.get('locations_resolved') or data.get('location') or {}
    location = ''
    if isinstance(loc, dict):
        location = ', '.join(scalar(loc.get(k)) for k in ('SUBLOCALITY_LEVEL_1_name', 'ADMIN_LEVEL_3_name', 'city', 'name') if loc.get(k))
    location = location or aut('itemLocation') or label('Location', 'Posted in')
    images = []
    raw_images = data.get('images', data.get('image', []))
    if not isinstance(raw_images, list):
        raw_images = [raw_images]
    for im in raw_images:
        if isinstance(im, str):
            images.append(im)
        elif isinstance(im, dict):
            for key in ('url', 'full', 'big', 'medium', 'large'):
                val = im.get(key)
                if isinstance(val, str):
                    images.append(val)
                    break
                if isinstance(val, dict) and isinstance(val.get('url'), str):
                    images.append(val['url'])
                    break
    for img in soup.select('img[src], img[data-src]'):
        images.append(img.get('data-src') or img.get('src'))
    for meta in soup.select('meta[property="og:image"]'):
        images.append(meta.get('content', ''))
    images = list(dict.fromkeys(x for x in images if safe_image(x)))[:20]
    try:
        car = Listing(id='olx-'+raw_id, url=url, title=title[:300], price=price, make=make or None, model=model or None,
                      variant=param('variant') or None, year=year, km=km, owners=owners, fuel=fuel or None,
                      transmission=transmission or None, location=location[:150], description=description[:30000],
                      images=images, retrieved_at=now(), posted_at=scalar(data.get('created_at')) or None)
    except ValueError as e:
        raise SourceError('The listing contains invalid or unsupported specifications.') from e
    car.missing = completeness(car)
    return car


class PageReader:
    def __init__(self):
        self.client = httpx.Client(timeout=25, follow_redirects=False, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; MotorwiseStudentProject/0.1)',
            'Accept-Language': 'en-IN,en;q=0.9'})
        self.playwright = self.browser = self.page = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        finally:
            self.client.close()

    def get(self, url):
        safe_olx_url(url)
        failure = None
        try:
            current = url
            for _ in range(4):
                with self.client.stream('GET', current) as response:
                    if response.is_redirect:
                        current = urljoin(current, response.headers.get('location', ''))
                        safe_olx_url(current)
                        continue
                    response.raise_for_status()
                    chunks = bytearray()
                    for chunk in response.iter_bytes():
                        chunks.extend(chunk)
                        if len(chunks) > 12_000_000:
                            raise SourceError('OLX returned an unexpectedly large page.')
                    html = bytes(chunks).decode('utf-8', errors='replace')
                    if self.useful(html, current):
                        return html
                    failure = 'OLX returned a challenge or a page that requires browser rendering.'
                    break
            else:
                failure = 'OLX redirected too many times.'
        except (httpx.HTTPError, ValueError) as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (404, 410):
                raise SourceError('This OLX listing or search page is no longer available.') from e
            failure = request_failure(e)
        if os.getenv('OLX_BROWSER_FALLBACK', 'true').lower() != 'true':
            raise SourceError(failure or 'OLX retrieval failed.')
        try:
            if self.page is None:
                from playwright.sync_api import sync_playwright
                self.playwright = sync_playwright().start()
                self.browser = self.playwright.chromium.launch(headless=True)
                self.page = self.browser.new_page(locale='en-IN')
                # Public OLX pages and listing media only, no redirects into private hosts.
                def route(request_route):
                    p = urlparse(request_route.request.url)
                    host = p.hostname or ''
                    if p.scheme == 'https' and (host == 'olx.in' or host.endswith('.olx.in')):
                        request_route.continue_()
                    else:
                        request_route.abort()
                self.page.route('**/*', route)
            self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
            try:
                self.page.wait_for_selector('a[href*="/item/"], h1', timeout=6000)
            except Exception:
                pass
            html = self.page.content()
            if not self.useful(html, url):
                raise SourceError('OLX is showing an access challenge. Open its search page or add a listing manually.')
            return html
        except ImportError as e:
            raise SourceError(f'{failure} Browser fallback is not installed. Run setup with browser support or add listings manually.') from e
        except SourceError:
            raise
        except Exception as e:
            raise SourceError(f'{failure} Browser fallback: {browser_failure(e)}') from e

    @staticmethod
    def readable(html):
        soup = BeautifulSoup(html, 'html.parser')
        text = soup.get_text(' ', strip=True).lower()
        if any(x in text for x in ('verify you are human', 'access denied', 'checking your browser', 'unusual traffic', 'request blocked')):
            return False
        return bool(soup.find('h1') or soup.select_one('a[href*="/item/"]') or has_no_results(html))

    @classmethod
    def useful(cls, html, url):
        if not cls.readable(html):
            return False
        if '/item/' in urlparse(url).path:
            return bool(BeautifulSoup(html, 'html.parser').find('h1'))
        return bool(listing_links(html, url) or has_no_results(html))

    def cache_images(self, images, cancel=None):
        cached = []
        for url in images[:3]:
            if cancel and cancel.is_set():
                break
            if not safe_image(url):
                continue
            filename = hashlib.sha256(url.encode()).hexdigest() + '.img'
            path = IMAGES / filename
            if path.exists():
                cached.append('/api/images/'+filename)
                continue
            try:
                with self.client.stream('GET', url, timeout=8) as r:
                    r.raise_for_status()
                    if r.headers.get('content-type', '').split(';')[0] not in ('image/jpeg', 'image/png', 'image/webp', 'image/avif'):
                        continue
                    content = bytearray()
                    for chunk in r.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 3_000_000:
                            break
                    else:
                        path.write_bytes(content)
                        cached.append('/api/images/'+filename)
            except (httpx.HTTPError, OSError):
                continue
        return cached
