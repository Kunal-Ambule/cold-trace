import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_tmp = tempfile.mkdtemp(prefix="coldtrace_test_")
os.environ["DB_PATH"] = str(Path(_tmp) / "test.db")
os.environ["DATA_DIR"] = _tmp
os.environ["MODELS_DIR"] = str(Path(_tmp) / "models")
os.environ["LLM_PROVIDER"] = "none"
os.environ["OSRM_URL"] = "http://127.0.0.1:9"      # unreachable -> waypoint routes, fast

import pytest  # noqa: E402

from app import bootstrap, db  # noqa: E402
from tests.weather_fixture import seed_fake_weather  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup():
    bootstrap.init_all()
    seed_fake_weather()
    yield
