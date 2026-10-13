import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env')
DATA = Path(os.environ.get('MOTORWISE_DATA_DIR', ROOT / 'data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
IMAGES = DATA / 'images'
IMAGES.mkdir(exist_ok=True)


def request_delay() -> float:
    try:
        return max(0.5, min(10, float(os.getenv('OLX_REQUEST_DELAY', '1.5'))))
    except ValueError:
        return 1.5
