import asyncio
import json
import threading
from pathlib import Path
import pytest
import httpx
from backend.app import ai, jobs, store
from backend.app.analysis import match_listing, price_comparisons
from backend.app.main import app
from backend.app.models import Filters, Listing
from backend.app.sources.olx import parse_listing, listing_links, SourceError


class LocalClient:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def request(self, method, path, **kwargs):
        async def perform():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(perform())

    def get(self, path, **kwargs):
        return self.request('GET', path, **kwargs)

    def post(self, path, **kwargs):
        return self.request('POST', path, **kwargs)

URL = 'https://www.olx.in/item/cars-c84-used-honda-city-in-bengaluru-iid-1854376255'
URL2 = 'https://www.olx.in/item/cars-c84-used-honda-city-2019-in-bengaluru-iid-1854376256'
SEARCH_PAGE = f'''<html><h1>Cars in Bengaluru</h1><a href="{URL}">Honda City</a><a href="{URL2}">Honda City</a></html>'''
DETAIL_PAGE = '''<html><head><script id="__NEXT_DATA__" type="application/json">{
"props":{"item":{"id":"1854376255","title":"Honda City 2018 Automatic","price":{"value":{"raw":650000}},
"description":"Single owner. Service records available; please verify.","parameters":[
{"key":"make","value_name":"Honda"},{"key":"model","value_name":"City"},
{"key":"year","value_name":"2018"},{"key":"km_driven","value_name":"48,000 km"},
{"key":"fuel","value_name":"Petrol"},{"key":"transmission","value_name":"Automatic"},
{"key":"owners","value_name":"1"}],"images":[{"url":"https://apollo.olx.in/v1/files/sample/image;s=400x300"}]}}}
</script></head><body><h1>Honda City 2018 Automatic</h1><div data-aut-id="itemLocation">Indiranagar, Bengaluru</div><div data-aut-id="itemPrice">₹ 6,50,000</div></body></html>'''


@pytest.fixture()
def local_store(monkeypatch, tmp_path):
    monkeypatch.setattr(store, 'DATA', tmp_path)
    store.initialize()
    yield tmp_path


def test_parses_realistic_public_page_and_strict_filters():
    car = parse_listing(DETAIL_PAGE, URL)
    assert car.id == 'olx-1854376255'
    assert (car.price, car.km, car.owners, car.year) == (650000, 48000, 1, 2018)
    assert car.images == ['https://apollo.olx.in/v1/files/sample/image;s=400x300']
    assert 'Service records' in car.description
    assert len(listing_links(SEARCH_PAGE, 'https://www.olx.in/bengaluru_g4058803/cars_c84')) == 2
    assert match_listing(car, Filters(max_price=700000, max_owners=1, fuel='Petrol')) == (True, [])
    assert match_listing(car, Filters(max_price=600000))[0] is False
    car.owners = None
    assert match_listing(car, Filters(max_owners=1))[0] is False
    assert match_listing(car, Filters(max_owners=1, include_unknown=True)) == (True, ['owners'])
    assert match_listing(car, Filters(location='Mumbai'))[0] is False


def test_price_median_requires_three_real_peers():
    cars = [dict(id=str(i), price=p, make='Honda', model='City', fuel='Petrol', transmission='Automatic',
                 year=2018, km=48000, variant='VX') for i,p in enumerate([650000,680000,690000,700000])]
    result = price_comparisons(cars)
    assert result['0']['median'] == 690000
    assert result['0']['count'] == 3
    assert result['0']['difference_percent'] == -5.8
    assert price_comparisons(cars[:3])['0']['median'] is None


def test_search_job_and_api_persistence(monkeypatch, local_store):
    class Reader:
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def get(self, url):
            if '/item/' not in url:
                return SEARCH_PAGE
            if url == URL2:
                raise SourceError('Listing removed')
            return DETAIL_PAGE
        def cache_images(self, *_): return []
    monkeypatch.setattr(jobs, 'PageReader', Reader)
    monkeypatch.setattr(jobs, 'request_delay', lambda: 0)
    with LocalClient() as client:
        response = client.post('/api/searches', json={'max_price': 700000, 'limit': 2})
        assert response.status_code == 202
        sid = response.json()['id']
        # The controlled second listing fails; collected first listing must survive.
        for _ in range(100):
            result = client.get('/api/searches/'+sid).json()
            if result['status'] in ('completed','failed','cancelled'): break
            threading.Event().wait(.02)
        assert result['status'] == 'completed'
        assert result['source_status'] == 'partial'
        assert result['detail_failures'] == 1
        assert [c['id'] for c in result['listings']] == ['olx-1854376255']
        assert client.post('/api/shortlist',json={'search_id':sid,'listing_id':'olx-1854376255'}).status_code == 201
        assert client.get('/api/shortlist').json()['listings'][0]['id'] == 'olx-1854376255'
        assert client.get('/api/searches').json()[0]['count'] == 1
        assert client.post('/api/chat',json={'search_id':sid,'message':'Rank these'}).status_code == 503
        assert client.get('/').status_code == 200


def test_manual_cross_source_and_ai_validation(monkeypatch, local_store):
    with LocalClient() as client:
        add = client.post('/api/listings/manual', json={
            'title':'2019 Hyundai i20', 'source':'CarWale', 'url':'https://www.carwale.com/used/cars/example',
            'price':500000, 'location':'Bengaluru', 'description':'Seller says excellent condition.'})
        assert add.status_code == 201
        sid=add.json()['search_id']
        assert client.get('/api/searches/'+sid).json()['listings'][0]['source']=='CarWale'
        assert client.post('/api/listings/manual', json={'title':'Bad URL','url':'http://localhost/admin'}).status_code == 422
        assert client.post('/api/listings/manual', json={'title':'Bad photo','images':['https://127.0.0.1/private.png']}).status_code == 422
        with pytest.raises(ai.AIError):
            ai.validate_answer({'answer':'Buy another car', 'rankings':[{'listing_id':'invented','rank':1,'reason':'Great'}]},
                               {add.json()['listing']['id']})
        ai.configure('test-only-key','gemini-2.5-flash')
        class FakeResponse:
            status_code=200
            def raise_for_status(self): pass
            def json(self):
                return {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps({
                    'answer':'The seller claims excellent condition; verify it in person.',
                    'criteria':['Listed facts','Missing facts'],
                    'rankings':[{'listing_id':add.json()['listing']['id'],'rank':1,'reason':'One available car',
                                 'pros':[],'concerns':['Condition unverified'], 'missing_information':['Mileage'],
                                 'seller_questions':['Can you share service records?']}]})}]}}]}
        class FakeClient:
            def __init__(self,**_): pass
            async def __aenter__(self):return self
            async def __aexit__(self,*_):pass
            async def post(self,*_,**kwargs):
                assert 'images' not in kwargs['json']['contents'][0]['parts'][0]['text']
                return FakeResponse()
        monkeypatch.setattr(ai,'client',lambda: FakeClient())
        answer=client.post('/api/chat', json={'search_id':sid,'message':'Rank these'}).json()
        assert answer['rankings'][0]['listing_id']==add.json()['listing']['id']
        assert client.get('/api/messages',params={'search_id':sid}).json()[-1]['role']=='assistant'
        ai.configure('', 'gemini-2.5-flash')


def test_single_olx_import_reads_only_given_link(monkeypatch, local_store):
    from backend.app import main
    seen = []
    class Reader:
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def get(self, url):
            seen.append(url)
            return DETAIL_PAGE
        def cache_images(self, *_): return []
    monkeypatch.setattr(main, 'PageReader', Reader)
    with LocalClient() as client:
        result = client.post('/api/listings/import', json={'url':URL})
        assert result.status_code == 201
        assert seen == [URL]
        sid = result.json()['search_id']
        assert client.get('/api/searches/'+sid).json()['listings'][0]['id'] == 'olx-1854376255'


def test_unavailable_source_and_interrupted_restart(monkeypatch, local_store):
    class BlockedReader:
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def get(self, _): raise SourceError('OLX is showing an access challenge.')
    monkeypatch.setattr(jobs, 'PageReader', BlockedReader)
    snapshot = store.create_search(Filters().model_dump())
    jobs.run(snapshot['id'], Filters(), threading.Event())
    failed = store.get_search(snapshot['id'])
    assert failed['status'] == 'failed'
    assert failed['source_status'] == 'unavailable'
    assert failed['listings'] == []
    pending = store.create_search(Filters().model_dump())
    store.initialize()
    assert store.get_search(pending['id'])['status'] == 'interrupted'
