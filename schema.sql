-- SkyNav databázové schéma
-- Spustit jednou před importem dat

CREATE EXTENSION IF NOT EXISTS postgis;

-- Letiště
CREATE TABLE IF NOT EXISTS airports (
    ident           TEXT PRIMARY KEY,
    iata_code       TEXT,
    name            TEXT NOT NULL,
    latitude_deg    DOUBLE PRECISION NOT NULL,
    longitude_deg   DOUBLE PRECISION NOT NULL,
    elevation_ft    TEXT,
    type            TEXT NOT NULL,
    scheduled_service TEXT,
    iso_country     TEXT,
    municipality    TEXT,
    gps_code        TEXT,
    geom            GEOMETRY(Point, 4326)
);

CREATE INDEX IF NOT EXISTS airports_geom_idx ON airports USING GIST(geom);
CREATE INDEX IF NOT EXISTS airports_type_idx ON airports(type);
CREATE INDEX IF NOT EXISTS airports_country_idx ON airports(iso_country);
CREATE INDEX IF NOT EXISTS airports_iata_idx ON airports(iata_code) WHERE iata_code IS NOT NULL;
CREATE INDEX IF NOT EXISTS airports_search_idx ON airports USING gin(
    to_tsvector('simple', coalesce(name,'') || ' ' || coalesce(municipality,'') || ' ' || ident)
);

-- Dráhy
CREATE TABLE IF NOT EXISTS runways (
    id              SERIAL PRIMARY KEY,
    airport_ident   TEXT NOT NULL REFERENCES airports(ident) ON DELETE CASCADE,
    le_ident        TEXT,
    he_ident        TEXT,
    le_latitude_deg DOUBLE PRECISION,
    le_longitude_deg DOUBLE PRECISION,
    he_latitude_deg DOUBLE PRECISION,
    he_longitude_deg DOUBLE PRECISION,
    le_heading_degt DOUBLE PRECISION,
    length_ft       INTEGER,
    width_ft        INTEGER,
    surface         TEXT,
    closed          BOOLEAN DEFAULT FALSE,
    le_ils_freq_mhz DOUBLE PRECISION,
    he_ils_freq_mhz DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS runways_airport_idx ON runways(airport_ident);

-- Frekvence
CREATE TABLE IF NOT EXISTS frequencies (
    id              SERIAL PRIMARY KEY,
    airport_ident   TEXT NOT NULL REFERENCES airports(ident) ON DELETE CASCADE,
    type            TEXT,
    frequency_mhz   DOUBLE PRECISION,
    description     TEXT
);

CREATE INDEX IF NOT EXISTS frequencies_airport_idx ON frequencies(airport_ident);

-- Navaidy
CREATE TABLE IF NOT EXISTS navaids (
    ident           TEXT NOT NULL,
    name            TEXT,
    type            TEXT,
    latitude_deg    DOUBLE PRECISION NOT NULL,
    longitude_deg   DOUBLE PRECISION NOT NULL,
    frequency_khz   DOUBLE PRECISION,
    iso_country     TEXT,
    geom            GEOMETRY(Point, 4326),
    PRIMARY KEY (ident, type, latitude_deg, longitude_deg)
);

CREATE INDEX IF NOT EXISTS navaids_geom_idx ON navaids USING GIST(geom);
