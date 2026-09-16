import os
import sqlite3
import zipfile
import tempfile
import shutil
import requests
import pandas as pd


# =========================================================
# DREAM PROJECT
# HISTORICAL DATABASE BUILDER
# =========================================================

FINAL_DB = "cricket_history.db"

SOURCE_URLS = [
    "https://db-mcp.tigzig.com/downloads/cricket_all_tables.sqlite.zip",
    "https://api.tigzig.com/cricket/v1/download/cricket_all_tables.sqlite.zip",
]

SOURCE_ZIP = "cricket_source.zip"


# =========================================================
# DOWNLOAD
# =========================================================

def download_source():

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
    }

    last_error = None

    for url in SOURCE_URLS:

        print("")
        print("Downloading cricket database...")
        print(url)

        try:

            response = requests.get(
                url,
                headers=headers,
                timeout=180,
                stream=True,
                allow_redirects=True
            )

            response.raise_for_status()

            content_type = (
                response.headers
                .get("content-type", "")
                .lower()
            )

            print(
                "HTTP:",
                response.status_code
            )

            print(
                "Content-Type:",
                content_type
            )

            with open(
                SOURCE_ZIP,
                "wb"
            ) as f:

                for chunk in response.iter_content(
                    chunk_size=1024 * 1024
                ):

                    if chunk:
                        f.write(chunk)

            size = os.path.getsize(
                SOURCE_ZIP
            )

            print(
                "Downloaded:",
                round(size / 1024 / 1024, 2),
                "MB"
            )

            if size < 10000:

                raise RuntimeError(
                    "Downloaded file is too small."
                )

            return SOURCE_ZIP

        except Exception as e:

            print(
                "Download failed:",
                e
            )

            last_error = e

            if os.path.exists(SOURCE_ZIP):

                os.remove(
                    SOURCE_ZIP
                )

    raise RuntimeError(
        f"Could not download cricket database: {last_error}"
    )


# =========================================================
# EXTRACT SQLITE DATABASE
# =========================================================

def extract_sqlite(zip_path):

    temp_dir = tempfile.mkdtemp(
        prefix="dream_cricket_"
    )

    print("")
    print("Extracting source database...")

    try:

        with zipfile.ZipFile(
            zip_path,
            "r"
        ) as z:

            names = z.namelist()

            sqlite_files = [
                name
                for name in names
                if name.lower().endswith(
                    (".sqlite", ".db", ".sqlite3")
                )
            ]

            if not sqlite_files:

                raise RuntimeError(
                    "No SQLite database found inside downloaded ZIP."
                )

            print(
                "SQLite files found:",
                sqlite_files
            )

            selected = sqlite_files[0]

            z.extract(
                selected,
                temp_dir
            )

            source_db = os.path.join(
                temp_dir,
                selected
            )

            return temp_dir, source_db

    except Exception:

        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        raise


# =========================================================
# FIND TABLES
# =========================================================

def get_tables(connection):

    query = """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
        ORDER BY name
    """

    data = pd.read_sql_query(
        query,
        connection
    )

    return data["name"].tolist()


# =========================================================
# FIND COLUMNS
# =========================================================

def get_columns(
    connection,
    table
):

    query = f"""
        PRAGMA table_info("{table}")
    """

    data = pd.read_sql_query(
        query,
        connection
    )

    return data["name"].tolist()


# =========================================================
# CREATE OUR DATABASE
# =========================================================

def create_output_database():

    if os.path.exists(FINAL_DB):

        os.remove(
            FINAL_DB
        )

    connection = sqlite3.connect(
        FINAL_DB
    )

    cursor = connection.cursor()


    # -----------------------------------------------------
    # MATCHES
    # -----------------------------------------------------

    cursor.execute(
        """
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
        """
    )


    # -----------------------------------------------------
    # DELIVERIES
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            league TEXT,
            innings_no INTEGER,
            over_no INTEGER,
            ball_no INTEGER,
            batting_team TEXT,
            bowling_team TEXT,
            runs INTEGER,
            wickets INTEGER
        )
        """
    )


    # -----------------------------------------------------
    # WIN STATES
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE win_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            league TEXT,
            innings_no INTEGER,
            ball_no INTEGER,
            batting_team TEXT,
            bowling_team TEXT,
            wickets INTEGER,
            won INTEGER
        )
        """
    )


    # -----------------------------------------------------
    # FUTURE SAMPLES
    # -----------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            league TEXT,
            innings_no INTEGER,
            ball_no INTEGER,
            target_ball INTEGER,
            future_runs INTEGER
        )
        """
    )


    connection.commit()

    return connection


# =========================================================
# SOURCE DATA HELPERS
# =========================================================

def find_table(
    tables,
    possible_names
):

    lower_map = {
        t.lower(): t
        for t in tables
    }

    for name in possible_names:

        if name.lower() in lower_map:

            return lower_map[
                name.lower()
            ]

    return None


def find_column(
    columns,
    possible_names
):

    lower_map = {
        c.lower(): c
        for c in columns
    }

    for name in possible_names:

        if name.lower() in lower_map:

            return lower_map[
                name.lower()
            ]

    return None


# =========================================================
# BUILD FROM SOURCE
# =========================================================

def build_database(
    source_db
):

    print("")
    print("Reading source database...")

    source = sqlite3.connect(
        source_db
    )

    tables = get_tables(
        source
    )

    print(
        "Source tables:",
        tables
    )


    match_table = find_table(
        tables,
        [
            "match_info",
            "matches"
        ]
    )


    ball_table = find_table(
        tables,
        [
            "ball_by_ball",
            "ball_by_ball_ipl",
            "deliveries"
        ]
    )


    if match_table is None:

        raise RuntimeError(
            "Could not find match_info table."
        )


    if ball_table is None:

        raise RuntimeError(
            "Could not find ball-by-ball table."
        )


    print(
        "Match table:",
        match_table
    )

    print(
        "Ball table:",
        ball_table
    )


    match_columns = get_columns(
        source,
        match_table
    )

    ball_columns = get_columns(
        source,
        ball_table
    )


    print(
        "Match columns:",
        match_columns
    )

    print(
        "Ball columns:",
        ball_columns
    )


    # -----------------------------------------------------
    # OUTPUT DATABASE
    # -----------------------------------------------------

    output = create_output_database()

    out_cursor = output.cursor()


    # =====================================================
    # READ MATCH INFORMATION
    # =====================================================

    match_data = pd.read_sql_query(
        f'SELECT * FROM "{match_table}"',
        source
    )


    print(
        "Matches loaded:",
        len(match_data)
    )


    # -----------------------------------------------------
    # COLUMN DETECTION
    # -----------------------------------------------------

    match_id_col = find_column(
        match_data.columns,
        [
            "match_id",
            "id"
        ]
    )


    venue_col = find_column(
        match_data.columns,
        [
            "venue",
            "ground"
        ]
    )


    date_col = find_column(
        match_data.columns,
        [
            "date",
            "start_date",
            "match_date"
        ]
    )


    winner_col = find_column(
        match_data.columns,
        [
            "winner",
            "winning_team",
            "outcome_winner"
        ]
    )


    team1_col = find_column(
        match_data.columns,
        [
            "team1",
            "team_1"
        ]
    )


    team2_col = find_column(
        match_data.columns,
        [
            "team2",
            "team_2"
        ]
    )


    format_col = find_column(
        match_data.columns,
        [
            "format",
            "match_type",
            "type"
        ]
    )


    league_col = find_column(
        match_data.columns,
        [
            "league",
            "competition",
            "tournament"
        ]
    )


    # -----------------------------------------------------
    # INSERT MATCHES
    # -----------------------------------------------------

    for _, row in match_data.iterrows():

        match_id = (
            str(row[match_id_col])
            if match_id_col
            else str(_)
        )


        league = (
            str(row[league_col])
            if league_col
            else "Unknown"
        )


        match_format = (
            str(row[format_col])
            if format_col
            else "Unknown"
        )


        date = (
            str(row[date_col])
            if date_col
            else ""
        )


        venue = (
            str(row[venue_col])
            if venue_col
            else ""
        )


        team1 = (
            str(row[team1_col])
            if team1_col
            else ""
        )


        team2 = (
            str(row[team2_col])
            if team2_col
            else ""
        )


        winner = (
            str(row[winner_col])
            if winner_col
            else ""
        )


        out_cursor.execute(
            """
            INSERT OR IGNORE INTO matches
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
            (
                match_id,
                league,
                match_format,
                date,
                venue,
                team1,
                team2,
                winner
            )
        )


    output.commit()


    # =====================================================
    # BALL DATA
    # =====================================================

    ball_data = pd.read_sql_query(
        f'SELECT * FROM "{ball_table}"',
        source
    )


    print(
        "Deliveries loaded:",
        len(ball_data)
    )


    # -----------------------------------------------------
    # BALL COLUMNS
    # -----------------------------------------------------

    b_match_id = find_column(
        ball_data.columns,
        [
            "match_id",
            "id"
        ]
    )


    b_innings = find_column(
        ball_data.columns,
        [
            "innings",
            "innings_no"
        ]
    )


    b_over = find_column(
        ball_data.columns,
        [
            "over_no",
            "over"
        ]
    )


    b_delivery = find_column(
        ball_data.columns,
        [
            "delivery_in_over",
            "ball_no",
            "ball"
        ]
    )


    b_batting = find_column(
        ball_data.columns,
        [
            "batting_team",
            "team"
        ]
    )


    b_bowling = find_column(
        ball_data.columns,
        [
            "bowling_team"
        ]
    )


    b_runs = find_column(
        ball_data.columns,
        [
            "runs_off_bat",
            "runs_batter",
            "runs"
        ]
    )


    b_wicket = find_column(
        ball_data.columns,
        [
            "wicket_kind",
            "wicket"
        ]
    )


    # -----------------------------------------------------
    # REQUIRED CHECK
    # -----------------------------------------------------

    if b_match_id is None:

        raise RuntimeError(
            "Ball data has no match_id column."
        )


    if b_innings is None:

        raise RuntimeError(
            "Ball data has no innings column."
        )


    if b_over is None:

        raise RuntimeError(
            "Ball data has no over column."
        )


    if b_batting is None:

        raise RuntimeError(
            "Ball data has no batting_team column."
        )


    # =====================================================
    # PROCESS BALLS
    # =====================================================

    match_winners = {}

    for _, row in match_data.iterrows():

        if match_id_col:

            mid = str(
                row[match_id_col]
            )

        else:

            mid = str(_)


        winner = ""

        if winner_col:

            value = row[winner_col]

            if pd.notna(value):

                winner = str(value)


        match_winners[mid] = winner


    # -----------------------------------------------------
    # RUNNING MATCH STATE
    # -----------------------------------------------------

    current_match = None
    current_innings = None

    total_wickets = 0
    total_runs = 0

    rows_processed = 0


    # Sort where possible

    sort_columns = []

    for col in [
        b_match_id,
        b_innings,
        b_over,
        b_delivery
    ]:

        if col and col in ball_data.columns:

            sort_columns.append(
                col
            )


    if sort_columns:

        ball_data = ball_data.sort_values(
            sort_columns
        )


    # =====================================================
    # PROCESS EACH DELIVERY
    # =====================================================

    for _, row in ball_data.iterrows():

        match_id = str(
            row[b_match_id]
        )


        innings_value = row[
            b_innings
        ]


        try:

            innings_no = int(
                innings_value
            )

        except Exception:

            innings_no = 1


        if (
            current_match != match_id
            or current_innings != innings_no
        ):

            current_match = match_id

            current_innings = innings_no

            total_wickets = 0

            total_runs = 0


        # -------------------------------------------------
        # OVER
        # -------------------------------------------------

        try:

            over_no = int(
                float(row[b_over])
            )

        except Exception:

            over_no = 0


        # -------------------------------------------------
        # BALL
        # -------------------------------------------------

        if b_delivery:

            try:

                delivery_no = int(
                    float(row[b_delivery])
                )

            except Exception:

                delivery_no = 1

        else:

            delivery_no = 1


        ball_no = (
            over_no * 6
            + delivery_no
        )


        # -------------------------------------------------
        # TEAMS
        # -------------------------------------------------

        batting_team = str(
            row[b_batting]
        )


        if b_bowling:

            bowling_team = str(
                row[b_bowling]
            )

        else:

            bowling_team = ""


        # -------------------------------------------------
        # RUNS
        # -------------------------------------------------

        runs = 0

        if b_runs:

            try:

                runs = int(
                    float(row[b_runs])
                )

            except Exception:

                runs = 0


        total_runs += runs


        # -------------------------------------------------
        # WICKET
        # -------------------------------------------------

        wicket = 0

        if b_wicket:

            value = row[b_wicket]

            if pd.notna(value):

                text = str(
                    value
                ).strip()

                if text and text.lower() not in [
                    "none",
                    "nan",
                    ""
                ]:

                    wicket = 1


        total_wickets += wicket


        # -------------------------------------------------
        # LEAGUE
        # -------------------------------------------------

        league = "Unknown"

        if match_id in match_winners:

            # Try to get league from match data
            pass


        # Find league using match lookup

        try:

            match_row = match_data[
                match_data[
                    match_id_col
                ].astype(str)
                == match_id
            ]

            if not match_row.empty:

                if league_col:

                    league = str(
                        match_row.iloc[0][
                            league_col
                        ]
                    )

        except Exception:

            league = "Unknown"


        # -------------------------------------------------
        # STORE DELIVERY
        # -------------------------------------------------

        out_cursor.execute(
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
                league,
                innings_no,
                over_no,
                ball_no,
                batting_team,
                bowling_team,
                runs,
                total_wickets
            )
        )


        # -------------------------------------------------
        # WIN STATE
        # -------------------------------------------------

        winner = match_winners.get(
            match_id,
            ""
        )


        won = 0

        if winner:

            if winner.strip().lower() == batting_team.strip().lower():

                won = 1


        out_cursor.execute(
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
            (
                match_id,
                league,
                innings_no,
                ball_no,
                batting_team,
                bowling_team,
                total_wickets,
                won
            )
        )


        rows_processed += 1


        # -------------------------------------------------
        # PROGRESS
        # -------------------------------------------------

        if rows_processed % 50000 == 0:

            output.commit()

            print(
                "Processed deliveries:",
                rows_processed
            )


    output.commit()


    # =====================================================
    # FUTURE RUN SAMPLES
    # =====================================================

    print("")
    print("Creating future-run samples...")


    future_query = """
        SELECT
            match_id,
            league,
            innings_no,
            ball_no,
            runs
        FROM deliveries
        ORDER BY
            match_id,
            innings_no,
            ball_no
    """


    delivery_data = pd.read_sql_query(
        future_query,
        output
    )


    # Keep this controlled so the Render build
    # does not become unnecessarily huge.

    grouped = delivery_data.groupby(
        [
            "match_id",
            "innings_no"
        ],
        sort=False
    )


    sample_count = 0


    for (
        (
            match_id,
            innings_no
        ),
        group
    ) in grouped:

        group = group.sort_values(
            "ball_no"
        ).reset_index(
            drop=True
        )


        for index in range(
            len(group)
        ):

            current_ball = int(
                group.iloc[index][
                    "ball_no"
                ]
            )


            # Build samples for several
            # future horizons.

            for future_distance in [
                6,
                12,
                18,
                30,
                60
            ]:

                target_index = (
                    index
                    + future_distance
                )


                if target_index >= len(group):

                    continue


                future_slice = group.iloc[
                    index + 1:
                    target_index + 1
                ]


                future_runs = int(
                    future_slice[
                        "runs"
                    ].sum()
                )


                league = str(
                    group.iloc[index][
                        "league"
                    ]
                )


                target_ball = int(
                    group.iloc[target_index][
                        "ball_no"
                    ]
                )


                out_cursor.execute(
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
                    (
                        match_id,
                        league,
                        int(innings_no),
                        current_ball,
                        target_ball,
                        future_runs
                    )
                )


                sample_count += 1


                if sample_count % 50000 == 0:

                    output.commit()


    output.commit()


    # =====================================================
    # INDEXES
    # =====================================================

    print("")
    print("Creating indexes...")


    indexes = [

        """
        CREATE INDEX IF NOT EXISTS
        idx_win_league
        ON win_states(league)
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_win_teams
        ON win_states(
            batting_team,
            bowling_team
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_win_position
        ON win_states(
            innings_no,
            ball_no,
            wickets
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_samples_search
        ON samples(
            league,
            innings_no,
            ball_no,
            target_ball
        )
        """,

        """
        CREATE INDEX IF NOT EXISTS
        idx_deliveries_match
        ON deliveries(
            match_id,
            innings_no,
            ball_no
        )
        """
    ]


    for index_sql in indexes:

        out_cursor.execute(
            index_sql
        )


    output.commit()


    # =====================================================
    # FINAL COUNTS
    # =====================================================

    print("")
    print("===================================")
    print("DATABASE BUILD COMPLETE")
    print("===================================")


    cursor = output.cursor()


    cursor.execute(
        "SELECT COUNT(*) FROM matches"
    )

    matches = cursor.fetchone()[0]


    cursor.execute(
        "SELECT COUNT(*) FROM deliveries"
    )

    deliveries = cursor.fetchone()[0]


    cursor.execute(
        "SELECT COUNT(*) FROM win_states"
    )

    win_states = cursor.fetchone()[0]


    cursor.execute(
        "SELECT COUNT(*) FROM samples"
    )

    samples = cursor.fetchone()[0]


    print(
        "Matches:",
        matches
    )

    print(
        "Deliveries:",
        deliveries
    )

    print(
        "Win states:",
        win_states
    )

    print(
        "Future samples:",
        samples
    )


    output.close()
    source.close()


# =========================================================
# MAIN
# =========================================================

def main():

    print("")
    print("===================================")
    print("DREAM PROJECT DATABASE BUILDER")
    print("===================================")


    if os.path.exists(
        SOURCE_ZIP
    ):

        os.remove(
            SOURCE_ZIP
        )


    temp_dir = None


    try:

        zip_path = download_source()

        temp_dir, source_db = extract_sqlite(
            zip_path
        )

        build_database(
            source_db
        )


        print("")
        print(
            "SUCCESS: cricket_history.db created."
        )


    except Exception as e:

        print("")
        print(
            "DATABASE BUILD FAILED"
        )

        print(
            str(e)
        )

        raise


    finally:

        if temp_dir:

            shutil.rmtree(
                temp_dir,
                ignore_errors=True
            )


        if os.path.exists(
            SOURCE_ZIP
        ):

            os.remove(
                SOURCE_ZIP
            )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
