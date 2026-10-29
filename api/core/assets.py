from __future__ import annotations

import uuid
from pathlib import Path
from typing import BinaryIO

from PIL import Image

from .config import DATA_DIR

ASSETS_DIR = DATA_DIR / "assets"
MAX_ASSET_BYTES = 25 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
CHUNK = 512 * 1024


class AssetError(Exception):
    pass


def ensure_assets_dir() -> None:
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def save_asset(filename: str, stream: BinaryIO) -> dict:
    ensure_assets_dir()
    suffix = Path(filename or "").suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise AssetError("Unsupported image type.")

    asset_id = uuid.uuid4().hex[:16]
    path = ASSETS_DIR / f"{asset_id}{suffix}"
    size = 0

    try:
        with path.open("wb") as out:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ASSET_BYTES:
                    raise AssetError("Image is larger than 25 MB.")
                out.write(chunk)

        if size == 0:
            raise AssetError("The image is empty.")

        with Image.open(path) as image:
            width, height = image.size
            image.verify()

        return {
            "id": asset_id,
            "ext": suffix,
            "width": width,
            "height": height,
            "size": size,
        }
    except (AssetError, OSError):
        path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise AssetError("The file is not a readable image.") from exc


def asset_path(asset_id: str) -> Path:
    if not asset_id or not all(c in "0123456789abcdef" for c in asset_id):
        raise AssetError("Invalid asset id.")
    for candidate in ASSETS_DIR.glob(f"{asset_id}.*"):
        if candidate.is_file():
            return candidate
    raise AssetError("Image asset not found.")


def asset_bytes(asset_id: str) -> bytes:
    path = asset_path(asset_id)
    return path.read_bytes()
