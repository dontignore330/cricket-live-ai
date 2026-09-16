import sqlite3
import requests
import os
import time

DB_FILE = "cricket_history.db"
API_URL = "https://db-mcp.tigzig.com/v1/query/duckdb"

def run_sql(sql):
    response = requests.post(
        API_URL,
        json={"sql": sql, "format": "json"},
        timeout=120
    )

    print("API status:", response.status_code)

    if response.status_code != 200:
        print(response.text[:1000])
        return []

    data = response.json()

    if isinstance(data, dict):
        if "rows" in data:
            return data["rows"]
        if "data" in data:
            return data["data"]

    if isinstance(data, list):
        return data

    return []


def value(row, key, default=""):
    if isinstance(row, dict):
        return row.get(key, default)
    return default


if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

db = sqlite3.connect(DB_FILE)
cur = db.cursor()

cur.execute("PRAGMA journal_mode=OFF")
cur.execute("PRAGMA synchronous=OFF")

cur.execute("""
CREATE TABLE matches (
    match_id TEXT PRIMARY KEY,
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

print("======================================")
print(" DREAM PROJECT IPL DATABASE BUILDER")
print("======================================")
print("")


# -------------------------------------------------
# 1. GET IPL MATCH LIST
# -------------------------------------------------

print("STEP 1: Getting IPL matches...")

match_sql = """
SELECT
    match_id,
    start_date,
    venue,
    team1,
    team2,
    winner
FROM match_info
WHERE match_type = 'IPL'
ORDER BY start_date, match_id
"""

match_rows = run_sql(match_sql)

print("Match rows received:", len(match_rows))

match_map = {}

for row in match_rows:

    match_id = str(value(row, "match_id", ""))

    if not match_id:
        continue

    match_map[match_id] = {
        "date": str(value(row, "start_date", "")),
        "venue": str(value(row, "venue", "")),
        "team1": str(value(row, "team1", "")),
        "team2": str(value(row, "team2", "")),
        "winner": str(value(row, "winner", ""))
    }

print("Matches found:", len(match_map))

if len(match_map) == 0:
    print("ERROR: No IPL matches returned.")
    db.close()
    raise SystemExit(1)


# -------------------------------------------------
# 2. SAVE MATCHES
# -------------------------------------------------

print("STEP 2: Saving match information...")

for match_id, info in match_map.items():

    cur.execute("""
        INSERT OR REPLACE INTO matches
        (
            match_id,
            league,
            format,
            date,
            venue,
            team1,
            team2,
            winner
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id,
        "IPL",
        "T20",
        info["date"],
        info["venue"],
        info["team1"],
        info["team2"],
        info["winner"]
    ))

db.commit()

print("Match information saved.")


# -------------------------------------------------
# 3. GET IPL DELIVERIES IN BATCHES
# -------------------------------------------------

print("")
print("STEP 3: Getting IPL ball-by-ball data...")
print("Using 1000-row batches.")


delivery_rows = []

offset = 0
batch_size = 1000

while True:

    sql = f"""
    SELECT
        match_id,
        innings,
        over_no,
        delivery_in_over,
        batting_team,
        bowling_team,
        runs_off_bat,
        extras,
        wicket_type
    FROM ball_by_ball_ipl
    ORDER BY
        match_id,
        innings,
        over_no,
        delivery_in_over
    LIMIT {batch_size}
    OFFSET {offset}
    """

    rows = run_sql(sql)

    if not rows:
        break

    print(
        "Batch:",
        offset,
        "-",
        offset + len(rows),
        "| Total received:",
        offset + len(rows)
    )

    for row in rows:

        match_id = str(value(row, "match_id", ""))

        if not match_id:
            continue

        try:
            innings = int(value(row, "innings", 0))
        except:
            innings = 0

        try:
            over_no = int(value(row, "over_no", 0))
        except:
            over_no = 0

        try:
            delivery_no = int(value(row, "delivery_in_over", 0))
        except:
            delivery_no = 0

        batting = str(value(row, "batting_team", ""))
        bowling = str(value(row, "bowling_team", ""))

        try:
            runs = int(value(row, "runs_off_bat", 0) or 0)
        except:
            runs = 0

        try:
            extras = int(value(row, "extras", 0) or 0)
        except:
            extras = 0

        wicket_type = str(value(row, "wicket_type", "") or "")

        wicket = 1 if wicket_type else 0

        ball_no = float(
            str(over_no) + "." + str(delivery_no)
        )

        delivery_rows.append((
            match_id,
            "IPL",
            innings,
            over_no,
            ball_no,
            batting,
            bowling,
            runs + extras,
            wicket
        ))

    offset += len(rows)

    if len(rows) < batch_size:
        break

    time.sleep(0.2)


print("")
print("Total deliveries collected:", len(delivery_rows))


# -------------------------------------------------
# 4. SAVE DELIVERIES
# -------------------------------------------------

print("STEP 4: Saving deliveries...")

cur.executemany("""
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
""", delivery_rows)

db.commit()

print("Deliveries saved.")


# -------------------------------------------------
# 5. CREATE WIN STATES
# -------------------------------------------------

print("STEP 5: Creating historical win states...")

cur.execute("""
SELECT
    d.match_id,
    d.innings_no,
    d.ball_no,
    d.batting_team,
    d.bowling_team,
    d.wickets,
    m.winner
FROM deliveries d
LEFT JOIN matches m
ON d.match_id = m.match_id
WHERE m.winner IS NOT NULL
AND m.winner != ''
ORDER BY d.match_id, d.innings_no, d.ball_no
""")

state_rows = []

for row in cur.fetchall():

    (
        match_id,
        innings_no,
        ball_no,
        batting_team,
        bowling_team,
        wickets,
        winner
    ) = row

    won = 1 if batting_team == winner else 0

    state_rows.append((
        match_id,
        "IPL",
        innings_no,
        ball_no,
        batting_team,
        bowling_team,
        wickets,
        won
    ))

cur.executemany("""
    INSERT INTO win_states
    (
        match_id,
        league,
        innings_no,
        ball_no,
        batting_team,
        bowling_team,
        wickets,
        won
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
""", state_rows)

db.commit()

print("Win states:", len(state_rows))


# -------------------------------------------------
# 6. INDEXES
# -------------------------------------------------

print("STEP 6: Creating indexes...")

cur.execute("""
CREATE INDEX idx_deliveries_match
ON deliveries(match_id)
""")

cur.execute("""
CREATE INDEX idx_deliveries_teams
ON deliveries(batting_team, bowling_team)
""")

cur.execute("""
CREATE INDEX idx_win_states
ON win_states(
    league,
    batting_team,
    bowling_team,
    innings_no,
    ball_no
)
""")

cur.execute("""
CREATE INDEX idx_matches_league
ON matches(league)
""")

db.commit()


# -------------------------------------------------
# 7. FINAL COUNTS
# -------------------------------------------------

print("")
print("======================================")
print(" DATABASE BUILD COMPLETE")
print("======================================")

for table in [
    "matches",
    "deliveries",
    "win_states"
]:

    cur.execute(
        "SELECT COUNT(*) FROM " + table
    )

    count = cur.fetchone()[0]

    print(table, ":", count)

db.close()

print("")
print("Created:", DB_FILE)
print("DREAM PROJECT IPL DATABASE READY")
