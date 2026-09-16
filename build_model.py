import sqlite3
import requests
import json
import time
import os

# ============================================================
# DREAM PROJECT - MEMORY SAFE IPL BUILDER
# ============================================================

DB_FILE = "cricket_history.db"

API_URL = "https://db-mcp.tigzig.com/v1/query/duckdb"

# We build a compact historical database.
# We DO NOT download the complete 1M+ row database.
# We ask TigZig to calculate only the IPL historical states we need.

def api_query(sql):
    payload = {
        "sql": sql,
        "format": "json"
    }

    for attempt in range(5):
        try:
            r = requests.post(
                API_URL,
                json=payload,
                timeout=120
            )

            if r.status_code == 
