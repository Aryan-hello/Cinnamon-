#!/usr/bin/env python3
"""One-time importer for existing Runway artwork. No new image generation.

Run after cloning/pushing this repository (or via the bundled GitHub Action).
It downloads the already-generated images into normal local files so expiring
Runway CDN links never appear in Cinnamon's actual Discord UI.

The 46 background-removed cutouts have been numbered, NOT mislabelled as fish,
rods, or bait: the image task list does not identify the individual subjects.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = ROOT / 'tools' / 'runway_art_urls.txt'
ASSETS_ROOT = ROOT / 'static' / 'wildlands'
MANIFEST_PATH = ASSETS_ROOT / 'manifest.json'
ALLOWED_HOST = 'dnznrvs05pmza.cloudfront.net'
MAX_BYTES = 14 * 1024 * 1024
MAX_DIMENSION = 1500
PLACE_NAMES = ('ruins_fishing_pool', 'frostfall_fishing_spot',
               'moonlit_fishing_pool', 'woodland_fishing_pier')


def entries(urls: list[str]) -> list[dict]:
    if len(urls) != 50:
        raise ValueError(f'Expected 46 cutouts and 4 fishing places; found {len(urls)} source URLs.')
    items = []
    for i, url in enumerate(urls):
        p = urlsplit(url)
        if p.scheme != 'https' or p.hostname != ALLOWED_HOST or p.port not in (None, 443):
            raise ValueError(f'Artwork source #{i+1} does not use the expected Runway CDN host.')
        if not p.path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            raise ValueError(f'Unsupported image source format at index {i+1}.')
        task_id = (p.path.split('/')[4] if '/gemini/' in p.path else p.path.split('/')[2])
        if i < 46:
            key = f'cutout_{i+1:02d}'
            relative = f'cutouts/{key}.webp'
            kind = 'unmapped_cutout'
            name = f'Background-free cutout {i+1:02d}'
        else:
            key = PLACE_NAMES[i - 46]
            relative = f'places/{key}.webp'
            kind = 'fishing_place'
            name = key.replace('_', ' ').title()
        items.append({'key': key, 'label': name, 'kind': kind,
                      'file': relative, 'runway_task_id': task_id})
    return items


def valid_existing(path: Path) -> bool:
    try:
        if path.stat().st_size < 100:
            return False
        with Image.open(path) as picture:
            picture.verify()
        return True
    except (FileNotFoundError, OSError, UnidentifiedImageError, ValueError):
        return False


def download_one(url: str, dest: Path) -> None:
    request = Request(url, headers={'User-Agent': 'Cinnamon-Asset-Importer/1.0', 'Accept': 'image/*'})
    with urlopen(request, timeout=40) as response:
        kind = response.headers.get('Content-Type', '')
        if not (kind.lower().startswith('image/') or kind.lower().startswith('application/octet-stream')):
            raise ValueError(f'Source returned non-image content type {kind!r}')
        content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError('Source image too large')
    with Image.open(io.BytesIO(content)) as src:
        src.load()
        src = ImageOps.exif_transpose(src)
        src.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)
        # Preserve alpha on background-removed fish/rod/bait art.
        rendered = src.convert('RGBA') if 'A' in src.getbands() or 'transparency' in src.info else src.convert('RGB')
        if rendered.size[0] < 64 or rendered.size[1] < 64:
            raise ValueError('Unexpectedly tiny image')
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix('.tmp')
        try:
            rendered.save(temporary, format='WEBP', quality=84, method=5)
            with Image.open(temporary) as final:
                final.verify()
            os.replace(temporary, dest)
        finally:
            temporary.unlink(missing_ok=True)


def run() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-download', action='store_true', help='Validate manifest and existing files only')
    options = parser.parse_args()
    if not SOURCE_FILE.exists():
        print('ERROR: artwork source list is not included.', file=sys.stderr)
        return 2
    urls = [u.strip() for u in SOURCE_FILE.read_text(encoding='utf-8').splitlines() if u.strip() and not u.startswith('#')]
    items = entries(urls)
    ASSETS_ROOT.mkdir(parents=True, exist_ok=True)
    # The stable manifest deliberately contains NO expiring, signed links.
    MANIFEST_PATH.write_text(json.dumps({'version': 1, 'images': items}, indent=2) + '\n', encoding='utf-8')
    newly_downloaded, already_present, failures = 0, 0, []
    for i, (url, item) in enumerate(zip(urls, items), 1):
        path = ASSETS_ROOT / item['file']
        if valid_existing(path):
            already_present += 1
            continue
        if options.skip_download:
            continue
        try:
            download_one(url, path)
            newly_downloaded += 1
            print(f'[{i:02d}/50] saved {item["file"]}')
        except Exception as error:
            # Never print signed URLs to CI logs.
            reason = f'{type(error).__name__}: {error}'
            if len(reason) > 170:
                reason = reason[:170] + '...'
            print(f'[{i:02d}/50] ERROR downloading {item["key"]}: {reason}', file=sys.stderr)
            failures.append(item['key'])

    total = sum(valid_existing(ASSETS_ROOT / item['file']) for item in items)
    print(f'Artwork cached: {total}/50. New: {newly_downloaded}; previously saved: {already_present}; failed: {len(failures)}.')
    if failures:
        print('Missing assets:', ', '.join(failures), file=sys.stderr)
    # Save partial downloads via CI, even if some URLs already expired.
    return 0 if not failures and total == 50 else 1


if __name__ == '__main__':
    sys.exit(run())
