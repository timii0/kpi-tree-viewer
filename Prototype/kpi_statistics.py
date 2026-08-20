"""
kpi_statistics.py - Data Extraction from Teradata

Connects to Teradata, runs a SQL query for flight-level KPI data, and
saves the result as a local parquet cache (teradata_cache.parquet).

This is the first step in the pipeline. All downstream tools (converter.py,
cascade.py, editor.py, app.py) read from the parquet cache — they never
query Teradata directly.

Usage:
    python kpi_statistics.py

Environment variables:
    TD_HOST     Teradata hostname (default: dwprod)
    TD_USER     Username (prompts if not set)
    TD_PASS     Password (prompts if not set)
    TD_LOGMECH  Auth mechanism (default: LDAP)

Output:
    teradata_cache.parquet — Flat table, one row per flight-operation.
        Columns: Yr_Nb, Mo_Nb, sys, ml_dc_1, ml_dc_2, dom_int, station,
                 fleet, frst_flt_ind, vendor, num, den

    The dimension columns (everything except num, den, Yr_Nb) are
    automatically discovered by editor.py for hierarchy building.
    To add a new dimension, add it to the SELECT below.
"""

import teradatasql
import pandas as pd
import getpass as gp
import os
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Connection configuration (from environment or interactive prompt)
# ---------------------------------------------------------------------------

TD_HOST = os.getenv('TD_HOST', 'dwprod')
TD_USER = os.getenv('TD_USER') or input('Teradata username (TD_USER): ').strip()
TD_PASS = os.getenv('TD_PASS') or gp.getpass('Teradata password (TD_PASS): ')
TD_LOGMECH = os.getenv('TD_LOGMECH', 'LDAP')


def td_connect():
    """Open a connection to Teradata using configured credentials."""
    return teradatasql.connect(host=TD_HOST, user=TD_USER, password=TD_PASS, logmech=TD_LOGMECH)


# ---------------------------------------------------------------------------
# SQL Query
# ---------------------------------------------------------------------------
# Each column here becomes an available dimension in the hierarchy editor.
# Reserved columns (not used as dimensions): num, den, Yr_Nb
#
# To add a new dimension:
#   1. Add it to the SELECT (aliased to a clean name)
#   2. Re-run this script to refresh the parquet cache
#   3. Restart editor.py — new column appears automatically
# ---------------------------------------------------------------------------

query = """
        select
            Yr_Nb,
            Mo_Nb,
            'sys' as sys,
            ML_DC_Cd as ml_dc_1,
            Ownr_Crr_Cd as ml_dc_2,
            Dom_Intl_Cd as dom_int,
            Schd_Orig_Stn_Cd as station,
            schd_fleet as fleet,
            Frst_Flt_Ct as frst_flt_ind,
            pax_vendor as vendor,
            D0_Ct as num,
            DOT_OA_Sub_Op_Ct as den
        from 
            zods_kpi.flp_dtl_m
        where 
            data_cut = 'STANDARD'
            and DOT_OA_Sub_Op_Ct = 1
            and flt_orig_dt between '2025-06-01' and '2026-05-30'

        """

# ---------------------------------------------------------------------------
# Execute and save
# ---------------------------------------------------------------------------
# State after: teradata_cache.parquet written to disk.
#   DataFrame shape: ~1.8M rows x 12 columns
#   Each row = one flight operation with its KPI outcome (num) and
#   opportunity count (den), tagged with all dimensional attributes.
#   This is the single source of truth for all tree building.
# ---------------------------------------------------------------------------

with td_connect() as conn:
    df = pd.read_sql(query, conn)
    df.to_parquet("teradata_cache.parquet")

print(f"Saved {len(df):,} rows to teradata_cache.parquet")
print(f"Columns: {list(df.columns)}")
print(df.head())
