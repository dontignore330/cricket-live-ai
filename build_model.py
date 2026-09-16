import sqlite3
import requests
import os

DB_FILE = "cricket_history.db"
URL = "https://db-mcp.tigzig.com/v1/query/duckdb"

def query(sql):
    r = requests.post(
        URL,
        json={"sql": sql, "format": "json"},
        timeout=120
    )
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict):
        return data.get("rows", data.get("data", []))

    return data


if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

db = sqlite3.connect(DB_FILE)
cur = db.cursor()

cur.execute("""
CREATE TABLE matches (
    match_id TEXT,
    league TEXT,
    format TEXT,
    date TEXT,
    venue TEXT,
    team1 TEXT,
    team2 TEXT,
    winner TEXT
)
""")

cur.execute("""
CREATE TABLE deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    league TEXT,
    innings_no INTEGER,
    over_no INTEGER,
    ball_no REAL,
    batting_team TEXT,
    bowling_team TEXT,
    runs INTEGER,
    wickets INTEGER
)
""")

cur.execute("""
CREATE TABLE win_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    league TEXT,
    innings_no INTEGER,
    ball_no REAL,
    batting_team TEXT,
    bowling_team TEXT,
    wickets INTEGER,
    won INTEGER
)
""")

cur.execute("""
CREATE TABLE samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT,
    league TEXT,
    innings_no INTEGER,
    ball_no REAL,
    target_ball REAL,
    future_runs INTEGER
)
""")

db.commit()

print("DREAM PROJECT DATABASE BUILD STARTED")

print("Getting IPL data...")

sql = """
SELECT
    match_id,
    innings,
    ball,
    batting_team,
    bowling_team,
    runs_off_bat,
    extras
FROM ball_by_ball
WHERE match_type = 'IPL'
ORDER BY match_id, innings, ball
"""

rows = query(sql)

print("IPL rows received:", len(rows))

match_ids = set()

for row in rows:

    if not isinstance(row, dict):
        continue

    match_id = str(row.get("match_id", ""))

    if not match_id:
        continue

    match_ids.add(match_id)

    innings = int(row.get("innings") or 0)
    ball = float(row.get("ball") or 0)

    batting = str(row.get("batting_team") or "")
    bowling = str(row.get("bowling_team") or "")

    runs = int(row.get("runs_off_bat") or 0)
    extras = int(row.get("extras") or 0)

    total_runs = runs + extras

    cur.execute(
        """
        INSERT INTO deliveries
        (
            match_id,
            league,
            innings_no,
            over_no,
            ball_no,
            batting_team,
            bowling_team,
            runs,
            wickets
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            "IPL",
            innings,
            int(ball),
            ball,
            batting,
            bowling,
            total_runs,
            0
        )
    )

db.commit()

print("Deliveries saved:", len(rows))
print("Matches found:", len(match_ids))

print("Creating indexes...")

cur.execute(
    "CREATE INDEX idx_deliveries_match ON deliveries(match_id)"
)

cur.execute(
    "CREATE INDEX idx_deliveries_teams ON deliveries(batting_team, bowling_team)"
)

cur.execute(
    """
    CREATE INDEX idx_win_states
    ON win_states(league, batting_team, bowling_team, ball_no)
    """
)

cur.execute(
    """
    CREATE INDEX idx_samples
    ON samples(league, innings_no, ball_no, target_ball)
    """
)

db.commit()
db.close()

print("================================")
print("DATABASE BUILD COMPLETE")
print("Created:", DB_FILE)
print("================================")
