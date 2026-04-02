#!/usr/bin/env python3
"""
SkyNav data import script
Stáhne CSV z OurAirports a naimportuje do PostgreSQL.
Spouštět jednou denně (cron job).

Použití:
    python import_data.py
    python import_data.py --full    # reimport všeho, ne jen změn
"""

import asyncio
import asyncpg
import httpx
import csv
import io
import os
import logging
import argparse
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("skynav-import")

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://skynav:skynav@localhost/skynav")

SOURCES = {
    "airports":    "https://cdn.jsdelivr.net/gh/davidmegginson/ourairports-data@main/airports.csv",
    "runways":     "https://cdn.jsdelivr.net/gh/davidmegginson/ourairports-data@main/runways.csv",
    "frequencies": "https://cdn.jsdelivr.net/gh/davidmegginson/ourairports-data@main/airport-frequencies.csv",
    "navaids":     "https://cdn.jsdelivr.net/gh/davidmegginson/ourairports-data@main/navaids.csv",
}

def parse_float(val):
    try:
        return float(val) if val and val.strip() else None
    except ValueError:
        return None

def parse_int(val):
    try:
        return int(float(val)) if val and val.strip() else None
    except ValueError:
        return None

async def fetch_csv(client: httpx.AsyncClient, name: str, url: str) -> list[dict]:
    log.info(f"Stahuji {name}...")
    r = await client.get(url, timeout=60.0)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    rows = list(reader)
    log.info(f"  → {len(rows):,} řádků")
    return rows

async def import_airports(conn, rows: list[dict]):
    log.info("Importuji letiště...")
    VALID_TYPES = {
        "large_airport", "medium_airport", "small_airport",
        "heliport", "closed", "seaplane_base", "balloonport"
    }
    data = []
    for r in rows:
        lat = parse_float(r.get("latitude_deg"))
        lon = parse_float(r.get("longitude_deg"))
        if lat is None or lon is None:
            continue
        if r.get("type") not in VALID_TYPES:
            continue
        ident = (r.get("ident") or "").strip()
        if not ident:
            continue
        data.append((
            ident,
            r.get("iata_code") or None,
            (r.get("name") or "").strip(),
            lat, lon,
            r.get("elevation_ft") or None,
            r.get("type"),
            r.get("scheduled_service") or None,
            r.get("iso_country") or None,
            r.get("municipality") or None,
            r.get("gps_code") or None,
        ))

    await conn.execute("TRUNCATE airports CASCADE")
    await conn.executemany("""
        INSERT INTO airports (
            ident, iata_code, name, latitude_deg, longitude_deg,
            elevation_ft, type, scheduled_service, iso_country,
            municipality, gps_code, geom
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
            ST_SetSRID(ST_MakePoint($5, $4), 4326)
        )
        ON CONFLICT (ident) DO UPDATE SET
            iata_code = EXCLUDED.iata_code,
            name = EXCLUDED.name,
            latitude_deg = EXCLUDED.latitude_deg,
            longitude_deg = EXCLUDED.longitude_deg,
            elevation_ft = EXCLUDED.elevation_ft,
            type = EXCLUDED.type,
            scheduled_service = EXCLUDED.scheduled_service,
            iso_country = EXCLUDED.iso_country,
            municipality = EXCLUDED.municipality,
            gps_code = EXCLUDED.gps_code,
            geom = EXCLUDED.geom
    """, data)
    log.info(f"  → importováno {len(data):,} letišť")

async def import_runways(conn, rows: list[dict]):
    log.info("Importuji dráhy...")
    # Načti existující ident pro FK check
    existing = set(r["ident"] for r in await conn.fetch("SELECT ident FROM airports"))

    data = []
    for r in rows:
        ident = (r.get("airport_ident") or "").strip()
        if ident not in existing:
            continue
        data.append((
            ident,
            r.get("le_ident") or None,
            r.get("he_ident") or None,
            parse_float(r.get("le_latitude_deg")),
            parse_float(r.get("le_longitude_deg")),
            parse_float(r.get("he_latitude_deg")),
            parse_float(r.get("he_longitude_deg")),
            parse_float(r.get("le_heading_degT")),
            parse_int(r.get("length_ft")),
            parse_int(r.get("width_ft")),
            r.get("surface") or None,
            r.get("closed") == "1",
            parse_float(r.get("le_ils_freq_mhz")),
            parse_float(r.get("he_ils_freq_mhz")),
        ))

    await conn.execute("DELETE FROM runways")
    await conn.executemany("""
        INSERT INTO runways (
            airport_ident, le_ident, he_ident,
            le_latitude_deg, le_longitude_deg,
            he_latitude_deg, he_longitude_deg,
            le_heading_degt, length_ft, width_ft,
            surface, closed, le_ils_freq_mhz, he_ils_freq_mhz
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
    """, data)
    log.info(f"  → importováno {len(data):,} drah")

async def import_frequencies(conn, rows: list[dict]):
    log.info("Importuji frekvence...")
    existing = set(r["ident"] for r in await conn.fetch("SELECT ident FROM airports"))

    data = []
    for r in rows:
        ident = (r.get("airport_ident") or "").strip()
        if ident not in existing:
            continue
        mhz = parse_float(r.get("frequency_mhz"))
        if not mhz:
            continue
        data.append((
            ident,
            (r.get("type") or "").strip() or None,
            mhz,
            (r.get("description") or "").replace('"', '').strip() or None,
        ))

    await conn.execute("DELETE FROM frequencies")
    await conn.executemany("""
        INSERT INTO frequencies (airport_ident, type, frequency_mhz, description)
        VALUES ($1, $2, $3, $4)
    """, data)
    log.info(f"  → importováno {len(data):,} frekvencí")

async def import_navaids(conn, rows: list[dict]):
    log.info("Importuji navaidy...")
    data = []
    for r in rows:
        lat = parse_float(r.get("latitude_deg"))
        lon = parse_float(r.get("longitude_deg"))
        if lat is None or lon is None:
            continue
        ident = (r.get("ident") or "").strip()
        if not ident:
            continue
        data.append((
            ident,
            r.get("name") or None,
            r.get("type") or None,
            lat, lon,
            parse_float(r.get("frequency_khz")),
            r.get("iso_country") or None,
        ))

    await conn.execute("DELETE FROM navaids")
    await conn.executemany("""
        INSERT INTO navaids (
            ident, name, type, latitude_deg, longitude_deg,
            frequency_khz, iso_country, geom
        ) VALUES (
            $1, $2, $3, $4, $5, $6, $7,
            ST_SetSRID(ST_MakePoint($5, $4), 4326)
        )
        ON CONFLICT DO NOTHING
    """, data)
    log.info(f"  → importováno {len(data):,} navaidů")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="Reimport všeho")
    args = parser.parse_args()

    start = datetime.now()
    log.info("=== SkyNav import spuštěn ===")

    async with httpx.AsyncClient() as client:
        tasks = {name: fetch_csv(client, name, url) for name, url in SOURCES.items()}
        results = {}
        for name, coro in tasks.items():
            results[name] = await coro

    conn = await asyncpg.connect(DATABASE_URL)
    try:
        async with conn.transaction():
            await import_airports(conn, results["airports"])
            await import_runways(conn, results["runways"])
            await import_frequencies(conn, results["frequencies"])
            await import_navaids(conn, results["navaids"])
    finally:
        await conn.close()

    elapsed = (datetime.now() - start).total_seconds()
    log.info(f"=== Import dokončen za {elapsed:.1f}s ===")

if __name__ == "__main__":
    asyncio.run(main())
