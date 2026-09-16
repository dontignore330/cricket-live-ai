import sqlite3
import requests
import os
import time

DB_FILE = "cricket_history.db"
API_URL = "https://db-mcp.tigzig.com/v1/query/duckdb"


def query(sql):
    for attempt in range(5):
        try:
            r = requests.post(
                API_URL,
                json={"sql": sql, "format": "json"},
                timeout=120
            )

            print("API:", r.status_code)

            if r.status_code == 200:
                data = r.json()

                if isinstance(data, dict):
                    return data.get("rows", data.get("data", []))

                if isinstance(data, list):
                    return data

                return []

            print(r.text[:500])

        except Exception as e:
            print("ERROR:", e)

        time.sleep(5)

    return []


def val(row, key, default=""):
    if isinstance(row, dict):
        return row.get(key, default)
    return default


# ============================================================
# NEW DATABASE
# ============================================================

if os.path.exists(DB_FILE):
    os.remove(DB_FILE)

db = sqlite3.connect(DB_FILE)
cur = db.cursor()

cur.execute("PRAGMA journal_mode=OFF")
cur.execute("PRAGMA synchronous=OFF")
cur.execute("PRAGMA temp_store=FILE")


# ============================================================
# TABLES
# ============================================================

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


print("==========================================")
print(" DREAM PROJECT - IPL DATABASE")
print("==========================================")


# ============================================================
# STEP 1
# GET IPL MATCH IDS DIRECTLY FROM IPL VIEW
# ============================================================

print("")
print("STEP 1: Finding IPL matches...")

match_ids = []
offset = 0
batch = 1000

while True:

    sql = f"""
    SELECT DISTINCT match_id
    FROM ball_by_ball_ipl
    ORDER BY match_id
    LIMIT {batch}
    OFFSET {offset}
    """

    rows = query(sql)

    if not rows:
        break

    for row in rows:
        match_id = str(val(row, "match_id", ""))

        if match_id:
            match_ids.append(match_id)

    print(
        "Match IDs:",
        len(match_ids)
    )

    offset += len(rows)

    if len(rows) < batch:
        break


print("")
print("TOTAL IPL MATCHES FOUND:", len(match_ids))


if not match_ids:
    print("")
    print("ERROR: IPL view returned zero matches.")
    db.close()
    raise SystemExit(1)


# ============================================================
# STEP 2
# GET MATCH INFORMATION
# ============================================================

print("")
print("STEP 2: Getting match information...")


# Process match IDs in groups.
for start in range(0, len(match_ids), 300):

    group = match_ids[start:start + 300]

    ids = []

    for x in group:
        safe = x.replace("'", "''")
        ids.append("'" + safe + "'")

    id_text = ",".join(ids)

    sql = f"""
    SELECT
        match_id,
        start_date,
        venue,
        team1,
        team2,
        winner
    FROM match_info
    WHERE match_id IN ({id_text})
    """

    rows = query(sql)

    for row in rows:

        match_id = str(val(row, "match_id", ""))

        if not match_id:
            continue

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
            str(val(row, "start_date", "")),
            str(val(row, "venue", "")),
            str(val(row, "team1", "")),
            str(val(row, "team2", "")),
            str(val(row, "winner", ""))
        ))

    db.commit()

    print(
        "Match information:",
        min(start + 300, len(match_ids)),
        "/",
        len(match_ids)
    )


# ============================================================
# STEP 3
# GET IPL BALL-BY-BALL
# ============================================================

print("")
print("STEP 3: Getting IPL deliveries...")
print("This may take some time.")


offset = 0
total_deliveries = 0

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
    LIMIT {batch}
    OFFSET {offset}
    """

    rows = query(sql)

    if not rows:
        break

    insert_rows = []

    for row in rows:

        match_id = str(val(row, "match_id", ""))

        try:
            innings = int(val(row, "innings", 0))
        except:
            innings = 0

        try:
            over_no = int(val(row, "over_no", 0))
        except:
            over_no = 0

        try:
            delivery_no = int(
                val(row, "delivery_in_over", 0)
            )
        except:
            delivery_no = 0

        batting = str(
            val(row, "batting_team", "")
        )

        bowling = str(
            val(row, "bowling_team", "")
        )

        try:
            bat_runs = int(
                val(row, "runs_off_bat", 0) or 0
            )
        except:
            bat_runs = 0

        try:
            extras = int(
                val(row, "extras", 0) or 0
            )
        except:
            extras = 0

        wicket_type = str(
            val(row, "wicket_type", "") or ""
        )

        wicket = 1 if wicket_type else 0

        # Human-readable ball number.
        ball_no = float(
            str(over_no) + "." + str(delivery_no)
        )

        insert_rows.append((
            match_id,
            "IPL",
            innings,
            over_no,
            ball_no,
            batting,
            bowling,
            bat_runs + extras,
            wicket
        ))

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
    """, insert_rows)

    db.commit()

    total_deliveries += len(insert_rows)

    print(
        "Deliveries:",
        total_deliveries
    )

    offset += len(rows)

    if len(rows) < batch:
        break

    time.sleep(0.2)


# ============================================================
# STEP 4
# WIN STATES
# ============================================================

print("")
print("STEP 4: Creating historical win states...")


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
ORDER BY
    d.match_id,
    d.innings_no,
    d.ball_no
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

print(
    "Win states:",
    len(state_rows)
)


# ============================================================
# STEP 5
# INDEXES
# ============================================================

print("")
print("STEP 5: Creating indexes...")


cur.execute("""
CREATE INDEX idx_deliveries_match
ON deliveries(match_id)
""")

cur.execute("""
CREATE INDEX idx_deliveries_teams
ON deliveries(
    batting_team,
    bowling_team
)
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


# ============================================================
# FINAL
# ============================================================

print("")
print("==========================================")
print(" DATABASE BUILD COMPLETE")
print("==========================================")


for table in [
    "matches",
    "deliveries",
    "win_states"
]:

    cur.execute(
        "SELECT COUNT(*) FROM " + table
    )

    count = cur.fetchone()[0]

    print(
        table,
        ":",
        count
    )


db.close()

print("")
print("cricket_history.db CREATED SUCCESSFULLY")
print("DREAM PROJECT IPL DATABASE READY")
