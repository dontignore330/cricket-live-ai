import os
import json
import zipfile
import sqlite3
import subprocess
import shutil
import time
import requests


# =========================================================
# DREAM PROJECT - DATA BUILDER
# =========================================================

DB = "cricket_history.db"

URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "BBL": "https://cricsheet.org/downloads/bbl_json.zip",
    "WBBL": "https://cricsheet.org/downloads/wbb_json.zip",
}


# =========================================================
# DOWNLOAD
# =========================================================

def download(league):

    os.makedirs("data", exist_ok=True)

    path = f"data/{league.lower()}_json.zip"

    url = os.getenv(
        f"CRICSHEET_{league}_URL",
        URLS[league]
    )

    print("")
    print("========================================")
    print("DOWNLOADING:", league)
    print("URL:", url)
    print("========================================")

    if os.path.exists(path):
        os.remove(path)

    # -----------------------------------------------------
    # METHOD 1: CURL
    # -----------------------------------------------------

    curl_path = shutil.which("curl")

    if curl_path:

        print("Download method: CURL")

        command = [
            curl_path,
            "-L",
            "--fail",
            "--silent",
            "--show-error",
            "--retry",
            "5",
            "--retry-delay",
            "3",
            "--connect-timeout",
            "30",
            "--max-time",
            "600",
            "-A",
            "Mozilla/5.0",
            "-H",
            "Accept: application/zip,application/octet-stream,*/*",
            "-o",
            path,
            url
        ]

        try:

            result = subprocess.run(
                command,
                capture_output=True,
                text=True
            )

            if result.returncode != 0:

                print(
                    "CURL failed:",
                    result.stderr
                )

            else:

                if os.path.exists(path):

                    size = os.path.getsize(path)

                    print(
                        "Downloaded bytes:",
                        size
                    )

                    if size > 1000 and zipfile.is_zipfile(path):

                        print(
                            league,
                            "ZIP downloaded successfully."
                        )

                        return path

                    print(
                        "CURL returned invalid/non-ZIP file."
                    )

                    if os.path.exists(path):
                        os.remove(path)

        except Exception as error:

            print(
                "CURL exception:",
                error
            )

            if os.path.exists(path):
                os.remove(path)

    # -----------------------------------------------------
    # METHOD 2: REQUESTS FALLBACK
    # -----------------------------------------------------

    print("Download method: REQUESTS fallback")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Accept": (
            "application/zip,"
            "application/octet-stream,"
            "*/*"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://cricsheet.org/downloads/"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=600,
            allow_redirects=True,
            stream=True
        )

        print(
            "HTTP status:",
            response.status_code
        )

        print(
            "Final URL:",
            response.url
        )

        print(
            "Content-Type:",
            response.headers.get(
                "Content-Type",
                ""
            )
        )

        response.raise_for_status()

        with open(path, "wb") as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if chunk:

                    file.write(chunk)

        size = os.path.getsize(path)

        print(
            "Downloaded bytes:",
            size
        )

        if size <= 1000:

            raise RuntimeError(
                "Downloaded file is too small."
            )

        if not zipfile.is_zipfile(path):

            with open(
                path,
                "rb"
            ) as file:

                first_bytes = file.read(200)

            print(
                "First bytes:",
                repr(first_bytes)
            )

            raise RuntimeError(
                f"{league} downloaded file is NOT a valid ZIP."
            )

        print(
            league,
            "ZIP downloaded successfully."
        )

        return path

    except Exception as error:

        if os.path.exists(path):
            os.remove(path)

        raise RuntimeError(
            f"Could not download {league}: {error}"
        )


# =========================================================
# DATABASE
# =========================================================

def create_database():

    if os.path.exists(DB):

        os.remove(DB)

    connection = sqlite3.connect(DB)

    cursor = connection.cursor()

    # -----------------------------------------------------
    # MATCHES
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE matches(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league TEXT,
            match_file TEXT,
            venue TEXT,
            city TEXT,
            date TEXT,
            season TEXT,
            gender TEXT,
            match_type TEXT,
            team1 TEXT,
            team2 TEXT,
            winner TEXT
        )
    """)

    # -----------------------------------------------------
    # DELIVERIES
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE deliveries(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            league TEXT,
            venue TEXT,
            date TEXT,
            innings_no INTEGER,
            batting_team TEXT,
            bowling_team TEXT,
            ball_no INTEGER,
            over_no INTEGER,
            wickets INTEGER,
            runs INTEGER,
            total_runs INTEGER
        )
    """)

    # -----------------------------------------------------
    # FUTURE SAMPLES
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE samples(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            league TEXT,
            venue TEXT,
            date TEXT,
            innings_no INTEGER,
            batting_team TEXT,
            bowling_team TEXT,
            ball_no INTEGER,
            target_ball INTEGER,
            wickets INTEGER,
            current_runs INTEGER,
            future_runs INTEGER
        )
    """)

    # -----------------------------------------------------
    # WIN STATES
    # -----------------------------------------------------

    cursor.execute("""
        CREATE TABLE win_states(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id INTEGER,
            league TEXT,
            venue TEXT,
            innings_no INTEGER,
            batting_team TEXT,
            bowling_team TEXT,
            ball_no INTEGER,
            wickets INTEGER,
            won INTEGER
        )
    """)

    connection.commit()

    return connection, cursor


# =========================================================
# BUILD
# =========================================================

def build():

    print("")
    print("========================================")
    print("DREAM PROJECT DATA BUILD")
    print("========================================")

    connection, cursor = create_database()

    delivery_count = 0
    sample_count = 0
    win_count = 0
    match_count = 0

    # =====================================================
    # EACH LEAGUE
    # =====================================================

    for league in URLS:

        print("")
        print("========================================")
        print("PROCESSING:", league)
        print("========================================")

        zip_path = download(league)

        print(
            "Opening:",
            zip_path
        )

        with zipfile.ZipFile(
            zip_path,
            "r"
        ) as archive:

            filenames = archive.namelist()

            json_files = [
                filename
                for filename in filenames
                if filename.lower().endswith(".json")
            ]

            print(
                "JSON matches found:",
                len(json_files)
            )

            for file_number, filename in enumerate(
                json_files,
                start=1
            ):

                try:

                    raw = archive.read(
                        filename
                    )

                    match = json.loads(
                        raw.decode(
                            "utf-8"
                        )
                    )

                except Exception as error:

                    print(
                        "Skipping bad JSON:",
                        filename,
                        error
                    )

                    continue

                info = match.get(
                    "info",
                    {}
                )

                # -------------------------------------------------
                # BASIC MATCH INFO
                # -------------------------------------------------

                venue = (
                    info.get(
                        "venue",
                        ""
                    )
                    or ""
                )

                city = (
                    info.get(
                        "city",
                        ""
                    )
                    or ""
                )

                dates = info.get(
                    "dates",
                    []
                )

                date = (
                    str(dates[0])
                    if dates
                    else ""
                )

                season = str(
                    info.get(
                        "season",
                        ""
                    )
                )

                gender = (
                    info.get(
                        "gender",
                        ""
                    )
                    or ""
                )

                match_type = (
                    info.get(
                        "match_type",
                        ""
                    )
                    or ""
                )

                teams = info.get(
                    "teams",
                    []
                )

                team1 = (
                    teams[0]
                    if len(teams) >= 1
                    else ""
                )

                team2 = (
                    teams[1]
                    if len(teams) >= 2
                    else ""
                )

                outcome = info.get(
                    "outcome",
                    {}
                )

                winner = outcome.get(
                    "winner",
                    ""
                )

                # -------------------------------------------------
                # SAVE MATCH
                # -------------------------------------------------

                cursor.execute(
                    """
                    INSERT INTO matches(
                        league,
                        match_file,
                        venue,
                        city,
                        date,
                        season,
                        gender,
                        match_type,
                        team1,
                        team2,
                        winner
                    )
                    VALUES(
                        ?,?,?,?,?,?,?,?,?,?,?
                    )
                    """,
                    (
                        league,
                        filename,
                        venue,
                        city,
                        date,
                        season,
                        gender,
                        match_type,
                        team1,
                        team2,
                        winner
                    )
                )

                match_id = cursor.lastrowid

                match_count += 1

                # -------------------------------------------------
                # INNINGS
                # -------------------------------------------------

                innings_list = match.get(
                    "innings",
                    []
                )

                for innings_no, innings in enumerate(
                    innings_list,
                    start=1
                ):

                    batting_team = innings.get(
                        "team",
                        ""
                    )

                    # Find other team.
                    bowling_team = next(
                        (
                            team
                            for team in teams
                            if team != batting_team
                        ),
                        ""
                    )

                    legal_ball = 0
                    total_runs = 0
                    wickets = 0

                    rows = []

                    # -------------------------------------------------
                    # OVERS
                    # -------------------------------------------------

                    for over_data in innings.get(
                        "overs",
                        []
                    ):

                        over_no = int(
                            over_data.get(
                                "over",
                                0
                            )
                        )

                        for delivery in over_data.get(
                            "deliveries",
                            []
                        ):

                            run_data = delivery.get(
                                "runs",
                                {}
                            )

                            ball_runs = int(
                                run_data.get(
                                    "total",
                                    0
                                )
                            )

                            total_runs += ball_runs

                            wicket_list = delivery.get(
                                "wickets",
                                []
                            )

                            wickets += len(
                                wicket_list
                            )

                            extras = delivery.get(
                                "extras",
                                {}
                            )

                            # Wide and no-ball are not legal balls.
                            is_legal = not (
                                extras.get(
                                    "wides",
                                    0
                                )
                                or
                                extras.get(
                                    "noballs",
                                    0
                                )
                            )

                            if not is_legal:
                                continue

                            legal_ball += 1

                            rows.append(
                                {
                                    "ball_no": legal_ball,
                                    "over_no": over_no,
                                    "runs": ball_runs,
                                    "total_runs": total_runs,
                                    "wickets": wickets
                                }
                            )

                    if not rows:
                        continue

                    # -------------------------------------------------
                    # SAVE DELIVERY STATES
                    # -------------------------------------------------

                    for row in rows:

                        cursor.execute(
                            """
                            INSERT INTO deliveries(
                                match_id,
                                league,
                                venue,
                                date,
                                innings_no,
                                batting_team,
                                bowling_team,
                                ball_no,
                                over_no,
                                wickets,
                                runs,
                                total_runs
                            )
                            VALUES(
                                ?,?,?,?,?,?,?,?,?,?,?,?
                            )
                            """,
                            (
                                match_id,
                                league,
                                venue,
                                date,
                                innings_no,
                                batting_team,
                                bowling_team,
                                row["ball_no"],
                                row["over_no"],
                                row["wickets"],
                                row["runs"],
                                row["total_runs"]
                            )
                        )

                        delivery_count += 1

                    # -------------------------------------------------
                    # FUTURE RUN SAMPLES
                    # -------------------------------------------------

                    max_ball = min(
                        120,
                        rows[-1]["ball_no"]
                    )

                    for row in rows:

                        current_ball = row[
                            "ball_no"
                        ]

                        current_score = row[
                            "total_runs"
                        ]

                        current_wickets = row[
                            "wickets"
                        ]

                        # Only create samples for future balls.
                        for target_ball in range(
                            current_ball + 1,
                            max_ball + 1
                        ):

                            target_score = rows[
                                target_ball - 1
                            ]["total_runs"]

                            future_runs = (
                                target_score
                                - current_score
                            )

                            cursor.execute(
                                """
                                INSERT INTO samples(
                                    match_id,
                                    league,
                                    venue,
                                    date,
                                    innings_no,
                                    batting_team,
                                    bowling_team,
                                    ball_no,
                                    target_ball,
                                    wickets,
                                    current_runs,
                                    future_runs
                                )
                                VALUES(
                                    ?,?,?,?,?,?,?,?,?,?,?,?
                                )
                                """,
                                (
                                    match_id,
                                    league,
                                    venue,
                                    date,
                                    innings_no,
                                    batting_team,
                                    bowling_team,
                                    current_ball,
                                    target_ball,
                                    current_wickets,
                                    current_score,
                                    future_runs
                                )
                            )

                            sample_count += 1

                    # -------------------------------------------------
                    # WIN STATES
                    # -------------------------------------------------

                    if winner:

                        for row in rows:

                            won = (
                                1
                                if winner == batting_team
                                else 0
                            )

                            cursor.execute(
                                """
                                INSERT INTO win_states(
                                    match_id,
                                    league,
                                    venue,
                                    innings_no,
                                    batting_team,
                                    bowling_team,
                                    ball_no,
                                    wickets,
                                    won
                                )
                                VALUES(
                                    ?,?,?,?,?,?,?,?,?
                                )
                                """,
                                (
                                    match_id,
                                    league,
                                    venue,
                                    innings_no,
                                    batting_team,
                                    bowling_team,
                                    row["ball_no"],
                                    row["wickets"],
                                    won
                                )
                            )

                            win_count += 1

                # -------------------------------------------------
                # PERIODIC COMMIT
                # -------------------------------------------------

                if match_count % 100 == 0:

                    connection.commit()

                    print(
                        "Progress:",
                        match_count,
                        "matches |",
                        delivery_count,
                        "deliveries |",
                        sample_count,
                        "samples"
                    )

        # Remove ZIP after processing.
        try:

            if os.path.exists(zip_path):
                os.remove(zip_path)

        except Exception:
            pass

        connection.commit()

    # =====================================================
    # INDEXES
    # =====================================================

    print("")
    print("========================================")
    print("CREATING INDEXES")
    print("========================================")

    cursor.execute("""
        CREATE INDEX idx_deliveries_context
        ON deliveries(
            league,
            ball_no,
            wickets,
            batting_team,
            bowling_team
        )
    """)

    cursor.execute("""
        CREATE INDEX idx_samples_context
        ON samples(
            league,
            target_ball,
            ball_no,
            wickets,
            batting_team,
            bowling_team
        )
    """)

    cursor.execute("""
        CREATE INDEX idx_samples_venue
        ON samples(
            venue,
            innings_no,
            wickets,
            ball_no
        )
    """)

    cursor.execute("""
        CREATE INDEX idx_win_context
        ON win_states(
            league,
            innings_no,
            ball_no,
            wickets,
            batting_team,
            bowling_team
        )
    """)

    cursor.execute("""
        CREATE INDEX idx_matches_league
        ON matches(
            league,
            date
        )
    """)

    connection.commit()

    connection.close()

    print("")
    print("========================================")
    print("BUILD COMPLETE")
    print("========================================")
    print("Matches:", match_count)
    print("Deliveries:", delivery_count)
    print("Samples:", sample_count)
    print("Win states:", win_count)
    print("Database:", DB)
    print("========================================")


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    build()
