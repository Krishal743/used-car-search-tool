from datetime import datetime
import ipaddress
from typing import Literal
from urllib.parse import urlparse
from pydantic import BaseModel, Field, field_validator, model_validator


def safe_olx_url(value: str) -> str:
    p = urlparse(value)
    if p.scheme != 'https' or p.hostname not in {'olx.in', 'www.olx.in'} or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Use a public https://www.olx.in URL.')
    return value


def safe_listing_url(value: str) -> str:
    p = urlparse(value)
    hosts = {'olx.in', 'www.olx.in', 'carwale.com', 'www.carwale.com', 'cars24.com', 'www.cars24.com',
             'spinny.com', 'www.spinny.com', 'facebook.com', 'www.facebook.com'}
    if p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Use a public HTTPS listing URL from one of the supported marketplaces.')
    return value


def safe_manual_image(value: str) -> str:
    p = urlparse(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Use a public HTTPS photo URL.')
    host = p.hostname.lower()
    if host == 'localhost' or host.endswith('.localhost') or '.' not in host:
        raise ValueError('Use a public HTTPS photo URL.')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Use a public HTTPS photo URL.')
    return value


class Filters(BaseModel):
    location: str = Field(default='Bengaluru', min_length=1, max_length=100)
    search_url: str = Field(default='', max_length=1000)
    min_price: int | None = Field(default=None, ge=0, le=100_000_000)
    max_price: int | None = Field(default=None, ge=0, le=100_000_000)
    make: str = Field(default='', max_length=80)
    model: str = Field(default='', max_length=80)
    min_year: int | None = Field(default=None, ge=1950, le=datetime.now().year + 1)
    max_year: int | None = Field(default=None, ge=1950, le=datetime.now().year + 1)
    max_km: int | None = Field(default=None, ge=0, le=2_000_000)
    fuel: Literal['', 'Petrol', 'Diesel', 'CNG', 'LPG', 'Hybrid', 'Electric'] = ''
    transmission: Literal['', 'Manual', 'Automatic'] = ''
    max_owners: int | None = Field(default=None, ge=1, le=5)
    limit: int = Field(default=20, ge=1, le=60)
    include_unknown: bool = False

    @field_validator('search_url')
    @classmethod
    def validate_url(cls, v):
        if v:
            safe_olx_url(v)
            if '/item/' in urlparse(v).path or 'cars_c84' not in urlparse(v).path:
                raise ValueError('Paste an OLX Cars search URL containing cars_c84.')
        return v

    @model_validator(mode='after')
    def ranges(self):
        for lo, hi in [('min_price', 'max_price'), ('min_year', 'max_year')]:
            if getattr(self, lo) is not None and getattr(self, hi) is not None and getattr(self, lo) > getattr(self, hi):
                raise ValueError(f'{lo} must not exceed {hi}.')
        return self


class Listing(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    source: str = 'OLX'
    url: str = Field(default='', max_length=1000)
    title: str = Field(min_length=1, max_length=300)
    price: int | None = Field(default=None, ge=0, le=100_000_000)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=100)
    variant: str | None = Field(default=None, max_length=150)
    year: int | None = Field(default=None, ge=1950, le=datetime.now().year + 1)
    km: int | None = Field(default=None, ge=0, le=2_000_000)
    fuel: str | None = Field(default=None, max_length=40)
    transmission: str | None = Field(default=None, max_length=40)
    owners: int | None = Field(default=None, ge=1, le=10)
    location: str = Field(default='', max_length=150)
    description: str = Field(default='', max_length=30000)
    images: list[str] = Field(default_factory=list, max_length=30)
    cached_images: list[str] = Field(default_factory=list)
    retrieved_at: str = ''
    posted_at: str | None = None
    origin: Literal['scraped', 'manual'] = 'scraped'
    missing: list[str] = Field(default_factory=list)
    unverified_filters: list[str] = Field(default_factory=list)


class ManualListing(BaseModel):
    title: str = Field(min_length=2, max_length=300)
    url: str = Field(default='', max_length=1000)
    source: Literal['OLX', 'CarWale', 'Cars24', 'Spinny', 'Facebook Marketplace', 'Other'] = 'Other'
    price: int | None = Field(default=None, ge=0, le=100_000_000)
    make: str | None = Field(default=None, max_length=80)
    model: str | None = Field(default=None, max_length=100)
    year: int | None = Field(default=None, ge=1950, le=datetime.now().year + 1)
    km: int | None = Field(default=None, ge=0, le=2_000_000)
    fuel: str | None = Field(default=None, max_length=40)
    transmission: str | None = Field(default=None, max_length=40)
    owners: int | None = Field(default=None, ge=1, le=10)
    location: str = Field(default='', max_length=150)
    description: str = Field(default='', max_length=30000)
    images: list[str] = Field(default_factory=list, max_length=20)
    search_id: str | None = None

    @field_validator('url')
    @classmethod
    def validate_url(cls, v):
        return safe_listing_url(v) if v else v

    @field_validator('images')
    @classmethod
    def validate_images(cls, images):
        return [safe_manual_image(url) for url in images]


class SavedSearch(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    filters: Filters


class ChatRequest(BaseModel):
    search_id: str | None = None
    listing_ids: list[str] = Field(default_factory=list, max_length=60)
    scope: Literal['search', 'shortlist'] = 'search'
    message: str = Field(min_length=1, max_length=4000)


class Assessment(BaseModel):
    listing_id: str
    rank: int = Field(ge=1, le=60)
    reason: str = Field(max_length=2000)
    pros: list[str] = Field(default_factory=list, max_length=10)
    concerns: list[str] = Field(default_factory=list, max_length=10)
    missing_information: list[str] = Field(default_factory=list, max_length=10)
    seller_questions: list[str] = Field(default_factory=list, max_length=10)


class AIAnswer(BaseModel):
    answer: str = Field(max_length=16000)
    criteria: list[str] = Field(default_factory=list, max_length=12)
    rankings: list[Assessment] = Field(default_factory=list, max_length=60)


class SettingsInput(BaseModel):
    api_key: str | None = Field(default=None, max_length=300)
    model: str = Field(default='gemini-2.5-flash', pattern=r'^[a-zA-Z0-9._-]{1,100}$')
