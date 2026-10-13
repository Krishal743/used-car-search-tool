import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DATA


def now():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    db = sqlite3.connect(DATA / 'motorwise.sqlite3', timeout=20)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS searches (id TEXT PRIMARY KEY, created_at TEXT, filters TEXT, state TEXT);
        CREATE TABLE IF NOT EXISTS saved_searches (id TEXT PRIMARY KEY, name TEXT, filters TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS shortlist (id TEXT PRIMARY KEY, listing TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT, role TEXT, content TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS ai_cache (key TEXT PRIMARY KEY, response TEXT);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        ''')
        for row in db.execute('SELECT id, state FROM searches').fetchall():
            state = json.loads(row['state'])
            if state['status'] in ('queued', 'running'):
                state.update(status='interrupted', message='The app stopped before this search finished. Collected results are preserved.')
                db.execute('UPDATE searches SET state=? WHERE id=?', (json.dumps(state), row['id']))


def create_search(filters):
    sid = uuid.uuid4().hex
    state = dict(status='queued', message='Waiting to search OLX', listings=[], scanned=0, excluded=0,
                 detail_failures=0, warnings=[], source_status='pending', completed_at=None, search_url='')
    with connect() as db:
        db.execute('INSERT INTO searches VALUES (?, ?, ?, ?)', (sid, now(), json.dumps(filters), json.dumps(state)))
    return get_search(sid)


def get_search(sid):
    with connect() as db:
        row = db.execute('SELECT * FROM searches WHERE id=?', (sid,)).fetchone()
    return dict(id=row['id'], created_at=row['created_at'], filters=json.loads(row['filters']), **json.loads(row['state'])) if row else None


def update_search(sid, **fields):
    with connect() as db:
        row = db.execute('SELECT state FROM searches WHERE id=?', (sid,)).fetchone()
        if row:
            state = json.loads(row['state'])
            state.update(fields)
            db.execute('UPDATE searches SET state=? WHERE id=?', (json.dumps(state), sid))


def append_listing(sid, listing):
    with connect() as db:
        row = db.execute('SELECT state FROM searches WHERE id=?', (sid,)).fetchone()
        if not row:
            return False
        state = json.loads(row['state'])
        state['listings'] = [x for x in state['listings'] if x['id'] != listing['id']] + [listing]
        db.execute('UPDATE searches SET state=? WHERE id=?', (json.dumps(state), sid))
    return True


def history():
    with connect() as db:
        rows = db.execute('SELECT * FROM searches ORDER BY created_at DESC LIMIT 100').fetchall()
    result = []
    for row in rows:
        state = json.loads(row['state'])
        result.append(dict(id=row['id'], created_at=row['created_at'], filters=json.loads(row['filters']),
                           status=state['status'], count=len(state['listings']), message=state['message']))
    return result


def shortlists():
    with connect() as db:
        rows = db.execute('SELECT listing FROM shortlist ORDER BY created_at DESC').fetchall()
    return [json.loads(row['listing']) for row in rows]


def add_shortlist(listing):
    with connect() as db:
        db.execute('INSERT INTO shortlist VALUES (?, ?, ?) ON CONFLICT(id) DO UPDATE SET listing=excluded.listing',
                   (listing['id'], json.dumps(listing), now()))


def delete_shortlist(lid):
    with connect() as db:
        db.execute('DELETE FROM shortlist WHERE id=?', (lid,))


def saved_searches():
    with connect() as db:
        rows = db.execute('SELECT * FROM saved_searches ORDER BY created_at DESC').fetchall()
    return [dict(id=r['id'], name=r['name'], filters=json.loads(r['filters'])) for r in rows]


def save_search(name, filters):
    sid = uuid.uuid4().hex
    with connect() as db:
        db.execute('INSERT INTO saved_searches VALUES (?, ?, ?, ?)', (sid, name, json.dumps(filters), now()))
    return sid


def delete_saved(sid):
    with connect() as db:
        db.execute('DELETE FROM saved_searches WHERE id=?', (sid,))


def messages(scope):
    with connect() as db:
        rows = db.execute('SELECT * FROM messages WHERE scope=? ORDER BY id', (scope,)).fetchall()
    return [dict(id=r['id'], role=r['role'], content=json.loads(r['content']), created_at=r['created_at']) for r in rows]


def add_message(scope, role, content):
    with connect() as db:
        db.execute('INSERT INTO messages(scope, role, content, created_at) VALUES (?, ?, ?, ?)',
                   (scope, role, json.dumps(content), now()))


def cache_get(key):
    with connect() as db:
        row = db.execute('SELECT response FROM ai_cache WHERE key=?', (key,)).fetchone()
    return json.loads(row['response']) if row else None


def cache_put(key, response):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO ai_cache VALUES (?, ?)', (key, json.dumps(response)))


def get_setting(key, default=''):
    with connect() as db:
        row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return row['value'] if row else default


def set_setting(key, value):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, value))
