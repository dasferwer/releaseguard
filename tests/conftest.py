import os
from pathlib import Path


def pytest_ignore_collect(collection_path: Path) -> bool:
    # Чистый suite остаётся доступен без БД; явный файл требует ранний preflight.
    return collection_path.name == "test_integration.py" and "TESTING" not in os.environ
