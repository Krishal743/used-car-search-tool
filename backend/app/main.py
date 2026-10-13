import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from . import ai, jobs, store
from .analysis import completeness, price_comparisons
from .config import ROOT, IMAGES
from .models import Filters, Listing, ManualListing, SavedSearch, ChatRequest, SettingsInput, safe_olx_url
from .sources.olx import PageReader, SourceError, parse_listing, safe_image, BENGALURU
from pydantic import BaseModel, Field, field_validator


@asynccontextmanager
async def lifespan(_):
    store.initialize()
    yield
    jobs.shutdown()


app = FastAPI(title='Motorwise', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:5173', 'http://localhost:5173'],
                   allow_methods=['GET', 'POST', 'DELETE', 'PUT'], allow_headers=['Content-Type'])


def require_search(sid):
    result = store.get_search(sid)
    if not result:
        raise HTTPException(404, 'Search not found.')
    return result


@app.get('/api/health')
async def health():
    return {'status': 'ok', 'ai': ai.status(), 'version': '0.1.0'}


@app.get('/api/sources')
async def sources():
    return [{'name': 'OLX', 'status': 'ready', 'description': 'Public listings · on-demand retrieval', 'url': BENGALURU},
            *[dict(name=n, status='planned', description='Not connected in this version', url=u) for n, u in [
                ('CarWale', 'https://www.carwale.com/used/'), ('Cars24', 'https://www.cars24.com/'),
                ('Spinny', 'https://www.spinny.com/'), ('Facebook Marketplace', 'https://www.facebook.com/marketplace/')]]]


@app.post('/api/searches', status_code=202)
async def search(filters: Filters):
    try:
        return jobs.start(filters)
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    except SourceError as e:
        raise HTTPException(422, str(e)) from e


@app.get('/api/searches')
async def history():
    return store.history()


@app.get('/api/searches/{sid}')
async def search_detail(sid: str):
    result = require_search(sid)
    return dict(**result, price_comparisons=price_comparisons(result['listings']))


@app.post('/api/searches/{sid}/cancel')
async def cancel_search(sid: str):
    require_search(sid)
    jobs.cancel(sid)
    return require_search(sid)


@app.get('/api/saved-searches')
async def saved():
    return store.saved_searches()


@app.post('/api/saved-searches', status_code=201)
async def save_search(body: SavedSearch):
    return {'id': store.save_search(body.name.strip(), body.filters.model_dump())}


@app.delete('/api/saved-searches/{sid}')
async def delete_saved(sid: str):
    store.delete_saved(sid)
    return {'ok': True}


@app.get('/api/shortlist')
async def shortlist():
    cars = store.shortlists()
    return {'listings': cars, 'price_comparisons': price_comparisons(cars)}


class ShortlistInput(BaseModel):
    search_id: str
    listing_id: str


@app.post('/api/shortlist', status_code=201)
async def add_shortlist(body: ShortlistInput):
    snapshot = require_search(body.search_id)
    car = next((c for c in snapshot['listings'] if c['id'] == body.listing_id), None)
    if not car:
        raise HTTPException(404, 'Listing not found in that search.')
    store.add_shortlist(car)
    return {'ok': True}


@app.delete('/api/shortlist/{lid}')
async def remove_shortlist(lid: str):
    store.delete_shortlist(lid)
    return {'ok': True}


@app.post('/api/listings/manual', status_code=201)
async def manual(body: ManualListing):
    if body.search_id:
        search = require_search(body.search_id)
        if search['status'] in ('queued', 'running'):
            raise HTTPException(409, 'Wait for this search to finish before adding a manual listing.')
    images = body.images
    car = Listing(**body.model_dump(exclude={'search_id', 'images'}), id='manual-'+uuid.uuid4().hex,
                  images=images, origin='manual', retrieved_at=store.now())
    car.missing = completeness(car)
    sid = body.search_id
    if not sid:
        snapshot = store.create_search(Filters(location=body.location or 'Bengaluru').model_dump())
        sid = snapshot['id']
        store.update_search(sid, status='completed', source_status='manual', completed_at=store.now(), message='Manually added listing · no source search performed')
    store.append_listing(sid, car.model_dump())
    return {'search_id': sid, 'listing': car.model_dump()}


class ImportInput(BaseModel):
    url: str = Field(max_length=1000)
    search_id: str | None = None

    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        safe_olx_url(v)
        if '/item/' not in v:
            raise ValueError('Use an individual OLX listing URL.')
        return v


@app.post('/api/listings/import', status_code=201)
async def import_listing(body: ImportInput):
    if body.search_id:
        snapshot = require_search(body.search_id)
        if snapshot['status'] in ('queued', 'running'):
            raise HTTPException(409, 'Wait for the active search to finish before importing a listing.')
    with jobs.lock:
        if jobs.active:
            raise HTTPException(409, 'An OLX search is active. Wait for it to finish before importing.')
    try:
        with PageReader() as reader:
            car = parse_listing(reader.get(body.url), body.url)
            car.cached_images = reader.cache_images(car.images)
    except SourceError as e:
        raise HTTPException(502, str(e)) from e
    sid = body.search_id
    if not sid:
        sid = store.create_search(Filters().model_dump())['id']
        store.update_search(sid, status='completed', source_status='available', message='Imported one public OLX listing', completed_at=store.now())
    store.append_listing(sid, car.model_dump())
    return {'search_id': sid, 'listing': car.model_dump()}


def chat_scope(body):
    if body.scope == 'shortlist':
        pool = store.shortlists()
        scope = 'shortlist'
    else:
        if not body.search_id:
            raise HTTPException(422, 'Choose a search before chatting.')
        snapshot = require_search(body.search_id)
        if snapshot['status'] in ('queued', 'running'):
            raise HTTPException(409, 'Wait for the search to finish before asking the AI.')
        pool = snapshot['listings']
        scope = body.search_id
    selected = [c for c in pool if c['id'] in body.listing_ids] if body.listing_ids else pool
    if not selected or (body.listing_ids and not set(body.listing_ids).issubset({c['id'] for c in pool})):
        raise HTTPException(422, 'Select cars that exist in this search or shortlist.')
    return scope, selected, pool


@app.post('/api/chat')
async def chat(body: ChatRequest):
    scope, selected, pool = chat_scope(body)
    try:
        return await ai.ask(scope, selected, pool, body.message.strip())
    except ai.AIError as e:
        raise HTTPException(e.status, str(e)) from e


@app.get('/api/messages')
async def messages(search_id: str | None = None, scope: str = 'search'):
    if scope == 'shortlist':
        return store.messages('shortlist')
    if search_id:
        require_search(search_id)
        return store.messages(search_id)
    return []


@app.get('/api/settings')
async def settings():
    return ai.status()


@app.put('/api/settings')
async def update_settings(body: SettingsInput):
    return ai.configure(body.api_key, body.model)


@app.get('/api/images/{filename}')
async def image(filename: str):
    if not re.fullmatch(r'[0-9a-f]{64}\.img', filename) or not (IMAGES / filename).is_file():
        raise HTTPException(404, 'Photo not found.')
    with (IMAGES / filename).open('rb') as stream:
        head = stream.read(16)
    media_type = ('image/jpeg' if head.startswith(b'\xff\xd8') else 'image/png' if head.startswith(b'\x89PNG')
                  else 'image/webp' if head[8:12] == b'WEBP' else 'image/avif' if head[4:12] in (b'ftypavif', b'ftypavis')
                  else 'application/octet-stream')
    return Response((IMAGES / filename).read_bytes(), media_type=media_type,
                    headers={'Cache-Control': 'public, max-age=31536000, immutable'})


frontend = ROOT / 'frontend' / 'dist'


@app.get('/')
async def index():
    path = frontend / 'index.html'
    if not path.is_file():
        raise HTTPException(503, 'Dashboard build missing. Run the setup script.')
    return HTMLResponse(path.read_text(encoding='utf-8'))


@app.get('/assets/{filename}')
async def assets(filename: str):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', filename):
        raise HTTPException(404, 'Asset not found.')
    path = frontend / 'assets' / filename
    if not path.is_file():
        raise HTTPException(404, 'Asset not found.')
    media_type = ('text/javascript' if filename.endswith('.js') else 'text/css' if filename.endswith('.css')
                  else 'image/svg+xml' if filename.endswith('.svg') else 'application/octet-stream')
    return Response(path.read_bytes(), media_type=media_type,
                    headers={'Cache-Control': 'public, max-age=31536000, immutable'})
