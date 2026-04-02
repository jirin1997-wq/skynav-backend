from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncpg
import os
import httpx
import asyncio
from typing import Optional

app = FastAPI(title="SkyNav API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://skynav:skynav@localhost/skynav")
pool = None

@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)

@app.on_event("shutdown")
async def shutdown():
    await pool.close()

# ─── AIRPORTS ────────────────────────────────────────────────
@app.get("/airports")
async def get_airports(
    minlat: float = Query(...),
    minlon: float = Query(...),
    maxlat: float = Query(...),
    maxlon: float = Query(...),
    zoom: int = Query(5),
):
    """
    Vrátí letiště pro daný viewport.
    Na nízkém zoomu jen large/medium, na vysokém zoomu vše.
    """
    if zoom < 5:
        types = ("large_airport",)
    elif zoom < 7:
        types = ("large_airport", "medium_airport")
    elif zoom < 9:
        types = ("large_airport", "medium_airport", "small_airport")
    else:
        types = ("large_airport", "medium_airport", "small_airport",
                 "heliport", "closed", "seaplane_base", "balloonport")

    rows = await pool.fetch("""
        SELECT ident, iata_code, name, latitude_deg, longitude_deg,
               elevation_ft, type, scheduled_service, iso_country,
               municipality, gps_code
        FROM airports
        WHERE latitude_deg BETWEEN $1 AND $2
          AND longitude_deg BETWEEN $3 AND $4
          AND type = ANY($5::text[])
        LIMIT 3000
    """, minlat, maxlat, minlon, maxlon, list(types))

    return JSONResponse([dict(r) for r in rows])


# ─── RUNWAYS ─────────────────────────────────────────────────
@app.get("/runways/{ident}")
async def get_runways(ident: str):
    rows = await pool.fetch("""
        SELECT le_ident, he_ident,
               le_latitude_deg, le_longitude_deg,
               he_latitude_deg, he_longitude_deg,
               le_heading_degt, length_ft, width_ft,
               surface, closed,
               le_ils_freq_mhz, he_ils_freq_mhz
        FROM runways
        WHERE airport_ident = $1
    """, ident.upper())
    return JSONResponse([dict(r) for r in rows])


# ─── FREQUENCIES ─────────────────────────────────────────────
@app.get("/frequencies/{ident}")
async def get_frequencies(ident: str):
    rows = await pool.fetch("""
        SELECT type, frequency_mhz, description
        FROM frequencies
        WHERE airport_ident = $1
        ORDER BY frequency_mhz
    """, ident.upper())
    return JSONResponse([dict(r) for r in rows])


# ─── NAVAIDS ─────────────────────────────────────────────────
@app.get("/navaids")
async def get_navaids(
    minlat: float = Query(...),
    minlon: float = Query(...),
    maxlat: float = Query(...),
    maxlon: float = Query(...),
):
    rows = await pool.fetch("""
        SELECT ident, name, type, latitude_deg, longitude_deg,
               frequency_khz, iso_country
        FROM navaids
        WHERE latitude_deg BETWEEN $1 AND $2
          AND longitude_deg BETWEEN $3 AND $4
        LIMIT 500
    """, minlat, maxlat, minlon, maxlon)
    return JSONResponse([dict(r) for r in rows])


# ─── SEARCH ──────────────────────────────────────────────────
@app.get("/search")
async def search(q: str = Query(..., min_length=2)):
    rows = await pool.fetch("""
        SELECT ident, iata_code, name, latitude_deg, longitude_deg,
               type, iso_country, municipality
        FROM airports
        WHERE ident ILIKE $1
           OR iata_code ILIKE $1
           OR name ILIKE $2
           OR municipality ILIKE $2
        ORDER BY
            CASE type
                WHEN 'large_airport' THEN 1
                WHEN 'medium_airport' THEN 2
                WHEN 'small_airport' THEN 3
                ELSE 4
            END
        LIMIT 20
    """, q.upper() + '%', '%' + q + '%')
    return JSONResponse([dict(r) for r in rows])


# ─── METAR (proxy aby se obešel CORS) ────────────────────────
@app.get("/metar/{ident}")
async def get_metar(ident: str):
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            r = await client.get(
                f"https://aviationweather.gov/api/data/metar"
                f"?ids={ident.upper()}&format=json"
            )
            return JSONResponse(r.json())
        except Exception:
            return JSONResponse([])


@app.get("/metar")
async def get_metar_batch(ids: str = Query(...)):
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            r = await client.get(
                f"https://aviationweather.gov/api/data/metar"
                f"?ids={ids}&format=json"
            )
            return JSONResponse(r.json())
        except Exception:
            return JSONResponse([])


# ─── TAF ─────────────────────────────────────────────────────
@app.get("/taf/{ident}")
async def get_taf(ident: str):
    async with httpx.AsyncClient(timeout=8.0) as client:
        try:
            r = await client.get(
                f"https://aviationweather.gov/api/data/taf"
                f"?ids={ident.upper()}&format=json"
            )
            return JSONResponse(r.json())
        except Exception:
            return JSONResponse([])


# ─── HEALTH ──────────────────────────────────────────────────
@app.get("/health")
async def health():
    try:
        await pool.fetchval("SELECT 1")
        return {"status": "ok"}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)
