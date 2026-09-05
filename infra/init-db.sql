-- Runs once, on first creation of the database volume.
-- TimescaleDB gives us hypertables for OHLCV bars in phase 01.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
