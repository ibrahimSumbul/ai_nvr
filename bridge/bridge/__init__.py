"""AI NVR bridge servisi.

Version pyproject.toml'dan tek kaynak olarak okunur (importlib.metadata).
Manuel sync gerekmez — `pyproject.toml`'da bump edilince burası otomatik
güncellenir.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bridge")
except PackageNotFoundError:
    # Package install edilmemiş (örn. ham repo). Geliştirme fallback'i.
    __version__ = "0.0.0+unknown"
