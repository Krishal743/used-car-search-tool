import threading
from concurrent.futures import ThreadPoolExecutor
from . import store
from .config import request_delay
from .models import Filters
from .analysis import match_listing
from .sources.olx import PageReader, SourceError, search_url, listing_links, parse_listing, next_page, has_no_results

executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='olx-search')
lock = threading.Lock()
active = {}


def start(filters: Filters):
    with lock:
        if active:
            raise RuntimeError('A search is already running. Cancel it or wait for it to finish.')
        search_url(filters)  # Validate location before creating a job.
        result = store.create_search(filters.model_dump())
        event = threading.Event()
        active[result['id']] = event
        executor.submit(run, result['id'], filters, event)
    return result


def cancel(sid):
    with lock:
        event = active.get(sid)
        if event:
            event.set()
            store.update_search(sid, message='Cancellation requested. Finishing the current request…')
            return True
    return False


def shutdown():
    with lock:
        for event in active.values():
            event.set()
    executor.shutdown(wait=True, cancel_futures=True)


def run(sid, filters, event):
    scanned = excluded = failures = matched = 0
    seen = set()
    warnings = []
    source_ok = False
    try:
        current = search_url(filters)
        store.update_search(sid, status='running', search_url=current, message='Connecting to OLX public car listings…')
        with PageReader() as reader:
            for page in range(1, 6):
                if event.is_set() or matched >= filters.limit or scanned >= 120:
                    break
                html = reader.get(current)
                links = [u for u in listing_links(html, current) if u not in seen]
                if not links:
                    if page == 1:
                        if has_no_results(html):
                            source_ok = True
                            break
                        raise SourceError('OLX returned no readable listing links. Its page structure may have changed; this is not a verified empty search.')
                    warnings.append('Pagination ended or repeated previously collected listings.')
                    break
                source_ok = True
                for url in links:
                    if event.is_set() or matched >= filters.limit or scanned >= 120:
                        break
                    seen.add(url)
                    if event.wait(request_delay()):
                        break
                    scanned += 1
                    store.update_search(sid, scanned=scanned, message=f'Reading listing {scanned} · {matched} matches collected')
                    try:
                        car = parse_listing(reader.get(url), url)
                        matches, unknown = match_listing(car, filters)
                        if matches:
                            car.unverified_filters = unknown
                            car.cached_images = reader.cache_images(car.images, event)
                            store.append_listing(sid, car.model_dump())
                            matched += 1
                        else:
                            excluded += 1
                    except SourceError as e:
                        failures += 1
                        if len(warnings) < 5:
                            warnings.append(str(e))
                        if failures >= 5 and not matched:
                            raise SourceError('Five listing detail requests failed. Stopped rather than treating unreadable listings as no matches.') from e
                    store.update_search(sid, excluded=excluded, detail_failures=failures, warnings=warnings)
                current = next_page(html, current, page)
        warnings.append('Bounded search: up to 5 result pages and 120 listing details. Results are a collected sample, not all OLX inventory.')
        if failures:
            warnings.append(f'{failures} listing detail pages could not be read; those cars were excluded.')
        status = 'cancelled' if event.is_set() else 'completed'
        store.update_search(sid, status=status, source_status='partial' if failures or event.is_set() else 'available', warnings=warnings,
                            completed_at=store.now(), message=f'{"Search cancelled" if event.is_set() else "Search finished"} · {matched} matches from {scanned} listings checked')
    except Exception as e:
        message = str(e) if isinstance(e, SourceError) else 'Search failed unexpectedly. Collected results have been preserved.'
        store.update_search(sid, status='cancelled' if event.is_set() else 'failed', source_status='partial' if matched else 'unavailable',
                            warnings=warnings, detail_failures=failures, excluded=excluded, completed_at=store.now(), message=message)
    finally:
        with lock:
            active.pop(sid, None)
