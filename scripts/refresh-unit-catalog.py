#!/usr/bin/env python3
"""Generate single-unit spawn choices from the installed DCS country database."""

import argparse
import hashlib
import json
from pathlib import Path
import re


DEFAULT_DCS_ROOT = Path('/data/dcs-fow/config/.wine/drive_c/Program Files/Eagle Dynamics/DCS World Server')
OUTPUT = Path(__file__).resolve().parent.parent / 'missions' / 'unit_catalog.json'


def country_vehicles(source: str, country: str) -> list[str]:
    marker = re.compile(r'(?m)^\s*local units\s*=\s*country:get\("' + re.escape(country) + r'"\)\.Units\s*$')
    match = marker.search(source)
    if not match:
        raise ValueError(f'Cannot find {country} unit list in DCS database')
    tail = source[match.end():]
    next_country = re.search(r'(?m)^\s*local units\s*=\s*country:get\(', tail)
    block = tail[:next_country.start()] if next_country else tail
    names = re.findall(r'(?m)^\s*cnt_unit\s*\(\s*units\.Cars\.Car\s*,\s*"([^"]+)"', block)
    if not names:
        raise ValueError(f'No ground units found for {country}')
    return sorted(set(names), key=str.casefold)


def generate(source: str) -> dict:
    result = {}
    for side, country in [('blue', 'USA'), ('red', 'RUSSIA')]:
        result[side] = {}
        for name in country_vehicles(source, country):
            unit_id = 'unit_' + hashlib.sha256(name.encode('utf-8')).hexdigest()[:16]
            result[side][unit_id] = {'label': name, 'kind': 'unit',
                                     'units': [{'type': name, 'dx': 0, 'dy': 0}]}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dcs-root', type=Path, default=DEFAULT_DCS_ROOT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    source_path = args.dcs_root / 'Scripts' / 'Database' / 'db_countries.lua'
    catalog = generate(source_path.read_text(encoding='utf-8-sig'))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n')
    print(f'Generated {args.output}: ' + ', '.join(f'{side} {len(entries)}' for side, entries in catalog.items()))


if __name__ == '__main__':
    main()
