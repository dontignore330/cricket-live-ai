import os
import sqlite3
import zipfile
import requests
import duckdb


# ============================================================
# DREAM PROJECT
# FINAL IPL DATABASE BUILDER
# ============================================================

SQLITE_DB = "cricket_history.db"

ZIP_FILE = "cricket_data.zip"

DOWNLOAD_URL = (
    "https://db-mcp.tigzig.com/"
    "downloads/cricket_all_tables.duckdb.zip"
)

DUCKDB_FILE = "cricket_all_tables.duckdb"


print("")
print("==========================================")
print(" DREAM PROJECT")
print(" FINAL IPL DATABASE BUILDER")
print("==========================================")
print("")


# ============================================================
# REMOVE OLD OUTPUT
# ============================================================

if os.path.exists(SQLITE_DB):
    os.remove(SQLITE_DB)

if os.path.exists(ZIP_FILE):
    os.remove(ZIP_FILE)

if os.path.exists(DUCKDB_FILE):
    os.remove(DUCKDB_FILE)


# ============================================================
# DOWNLOAD DATABASE
# ============================================================

print("STEP 1: Downloading cricket database...")
print("")

response = requests.get(
    DOWNLOAD_URL,
    stream=True,
    timeout=300
)

response.raise_for_status()

total = 0

with open(ZIP_FILE, "wb") as f:

    for chunk in response.iter_content(
        chunk_size=1024 * 1024
    ):

        if chunk:
            f.write(chunk)
            total += len(chunk)

            if total % (10 * 1024 * 1024) < len(chunk):
                print(
                    "Downloaded:",
                    round(total / 1024 / 1024, 1),
                    "MB"
                )


print("")
print("Download complete.")


# ============================================================
# EXTRACT
# ============================================================

print("")
print("STEP 2: Extracting database...")

with zipfile.ZipFile(ZIP_FILE, "r") as z:

    members = z.namelist()

    print("Files inside ZIP:", members)

    z.extractall(".")


# Sometimes ZIP contains a folder/path.
# Find the actual DuckDB file.

if not os.path.exists(DUCKDB_FILE):

    for root, dirs, files in os.walk("."):

        for name in files:

            if name.endswith(".duckdb"):

                DUCKDB_FILE = os.path.join(
                    root,
                    name
                )

                break


if not os.path.exists(DUCKDB_FILE):

    raise RuntimeError(
        "DuckDB file was not found after extraction."
    )


print("DuckDB found:", DUCKDB_FILE)


# ============================================================
# OPEN DUCKDB
# ============================================================

print("")
print("STEP 3: Opening DuckDB...")

source = duckdb.connect(
    DUCKDB_FILE,
    read_only=True
)


# ============================================================
# CHECK TABLES
# ============================================================

print("")
print("STEP 4: Checking source database...")

tables = source.execute(
    "SHOW TABLES"
).fetchall()

print("Tables:")

for table in tables:
    print(" -", table[0])


# ============================================================
# CREATE SQLITE DATABASE
# ============================================================

print("")
print("STEP 5: Creating application database...")

db = sqlite3.connect(
    SQLITE_DB
)

cur = db.cursor()

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


# ============================================================
# IPL MATCHES
# ============================================================

print("")
print("STEP 6: Reading IPL matches...")


match_query = """
SELECT
    match_id,
    start_date,
    venue,
    team1,
    team2,
    winner
FROM match_info
WHERE match_id IN (
    SELECT DISTINCT match_id
    FROM ball_by_ball
    WHERE match_type = 'IPL'
)
ORDER BY start_date, match_id
"""


match_cursor = source.execute(match_query)

match_count = 0


while True:

    rows = match_cursor.fetchmany(500)

    if not rows:
        break

    cur.executemany(
        """
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
        """,
        [
            (
                str(r[0]),
                "IPL",
                "T20",
                str(r[1] or ""),
                str(r[2] or ""),
                str(r[3] or ""),
                str(r[4] or ""),
                str(r[5] or "")
            )
            for r in rows
        ]
    )

    db.commit()

    match_count += len(rows)

    print(
        "Matches saved:",
        match_count
    )


print("")
print("TOTAL IPL MATCHES:", match_count)


if match_count == 0:

    source.close()
    db.close()

    raise RuntimeError(
        "IPL matches returned ZERO."
    )


# ============================================================
# IPL DELIVERIES
# ============================================================

print("")
print("STEP 7: Reading IPL deliveries...")
print("")


delivery_query = """
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
FROM ball_by_ball
WHERE match_type = 'IPL'
ORDER BY
    match_id,
    innings,
    over_no,
    delivery_in_over
"""


delivery_cursor = source.execute(
    delivery_query
)


delivery_count = 0


# Keep only current innings in memory.
current_match = None
current_innings = None
innings_rows = []


def process_innings(
    match_id,
    innings_no,
    rows
):

    if not rows:
        return 0

    # --------------------------------------------
    # Convert rows
    # --------------------------------------------

    balls = []

    cumulative_wickets = 0

    for r in rows:

        over_no = int(r[2] or 0)
        delivery_no = int(r[3] or 0)

        batting = str(r[4] or "")
        bowling = str(r[5] or "")

        runs = int(r[6] or 0)
        extras = int(r[7] or 0)

        wicket_type = str(r[8] or "")

        if wicket_type:
            cumulative_wickets += 1

        # Decimal is ONLY for compatibility
        # with the existing app.
        ball_no = float(
            str(over_no) +
            "." +
            str(delivery_no)
        )

        balls.append(
            (
                over_no,
                ball_no,
                batting,
                bowling,
                runs + extras,
                cumulative_wickets
            )
        )


    # --------------------------------------------
    # Deliveries
    # --------------------------------------------

    delivery_insert = []

    for b in balls:

        delivery_insert.append(
            (
                match_id,
                "IPL",
                innings_no,
                b[0],
                b[1],
                b[2],
                b[3],
                b[4],
                b[5]
            )
        )


    cur.executemany(
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
        delivery_insert
    )


    # --------------------------------------------
    # Winner
    # --------------------------------------------

    winner_row = cur.execute(
        """
        SELECT winner
        FROM matches
        WHERE match_id = ?
        """,
        (match_id,)
    ).fetchone()


    winner = ""

    if winner_row:
        winner = str(
            winner_row[0] or ""
        )


    # --------------------------------------------
    # Win states
    # --------------------------------------------

    if winner:

        win_insert = []

        for b in balls:

            won = (
                1
                if b[2] == winner
                else 0
            )

            win_insert.append(
                (
                    match_id,
                    "IPL",
                    innings_no,
                    b[1],
                    b[2],
                    b[3],
                    b[5],
                    won
                )
            )


        cur.executemany(
            """
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
            """,
            win_insert
        )


    # --------------------------------------------
    # Future-run samples
    # --------------------------------------------

    distances = [
        6,
        12,
        18,
        30
    ]

    prefix = [0]

    for b in balls:

        prefix.append(
            prefix[-1] + b[4]
        )


    sample_insert = []

    for i in range(len(balls)):

        current_ball = balls[i][1]

        for distance in distances:

            target_index = (
                i + distance
            )

            if target_index >= len(balls):
                continue

            future_runs = (
                prefix[target_index + 1]
                -
                prefix[i + 1]
            )

            target_ball = (
                balls[target_index][1]
            )

            sample_insert.append(
                (
                    match_id,
                    "IPL",
                    innings_no,
                    current_ball,
                    target_ball,
                    future_runs
                )
            )


    cur.executemany(
        """
        INSERT INTO samples
        (
            match_id,
            league,
            innings_no,
            ball_no,
            target_ball,
            future_runs
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        sample_insert
    )

    return len(balls)


# ============================================================
# STREAM DELIVERIES
# ============================================================

while True:

    rows = delivery_cursor.fetchmany(1000)

    if not rows:
        break

    for r in rows:

        match_id = str(r[0])

        innings_no = int(
            r[1] or 0
        )

        if (
            current_match is None
            or
            (
                match_id == current_match
                and
                innings_no == current_innings
            )
        ):

            if current_match is None:

                current_match = match_id
                current_innings = innings_no

            innings_rows.append(r)

        else:

            processed = process_innings(
                current_match,
                current_innings,
                innings_rows
            )

            delivery_count += processed

            if delivery_count % 10000 < processed:

                db.commit()

                print(
                    "Deliveries saved:",
                    delivery_count
                )

            current_match = match_id
            current_innings = innings_no
            innings_rows = [r]


# Last innings

if current_match is not None:

    processed = process_innings(
        current_match,
        current_innings,
        innings_rows
    )

    delivery_count += processed


db.commit()


print("")
print(
    "TOTAL DELIVERIES:",
    delivery_count
)


# ============================================================
# INDEXES
# ============================================================

print("")
print("STEP 8: Creating indexes...")


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
CREATE INDEX idx_win_states_lookup
ON win_states(
    league,
    batting_team,
    bowling_team,
    innings_no,
    ball_no
)
""")

cur.execute("""
CREATE INDEX idx_samples_lookup
ON samples(
    league,
    innings_no,
    ball_no,
    target_ball
)
""")

cur.execute("""
CREATE INDEX idx_matches_league
ON matches(league)
""")


db.commit()


# ============================================================
# FINAL COUNTS
# ============================================================

print("")
print("==========================================")
print(" FINAL DATABASE CHECK")
print("==========================================")


for table in [
    "matches",
    "deliveries",
    "win_states",
    "samples"
]:

    result = cur.execute(
        "SELECT COUNT(*) FROM " + table
    ).fetchone()

    print(
        table,
        ":",
        result[0]
    )


db.close()
source.close()


# ============================================================
# CLEANUP
# ============================================================

try:
    os.remove(ZIP_FILE)
except:
    pass

try:
    os.remove(DUCKDB_FILE)
except:
    pass


print("")
print("==========================================")
print(" DREAM PROJECT DATABASE READY")
print("==========================================")
print(
    "Created:",
    SQLITE_DB
)
