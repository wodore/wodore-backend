import os


def pytest_configure(config):
    os.environ.setdefault("DJANGO_ENV", "test")
