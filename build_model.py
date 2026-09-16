import os
import json
import zipfile
import urllib.request
import urllib.error
import sqlite3
import time


URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "BBL": "https://cricsheet.org/downloads/bbl_json.zip",
    "WBBL": "https://cricsheet.org/downloads/wbb_json.zip",
}


DB = "cricket_history.db"


def download(league):

    os.makedirs("data", exist_ok=True)

    path = f"data/{league.lower()}_json.zip"

    url = os.getenv(
        f"CRICSHEET_{league}_URL",
        URLS[league]
    )

    print("")
    print("==============================")
    print("Downloading:", league)
    print("URL:", url)
    print("==============================")

    # Remove old/broken file
    if os.path.exists(path):
        os.remove(path)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/131.0 Safari/537.36"
        ),
        "Accept": (
            "application/zip,"
            "application/octet-stream,"
            "application/x-zip-compressed,"
            "*/*"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "close",
    }

    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=300
        ) as response:

            final_url = response.geturl()
            status = response.status
            content_type = response.headers.get(
                "Content-Type",
                ""
            )

            print("HTTP status:", status)
            print("Final URL:", final_url)
            print("Content-Type:", content_type)

            data = response.read()

        print(
            "Downloaded bytes:",
            len(data)
        )

        # A normal ZIP file starts with PK.
        if not data.startswith(b"PK"):

            print("")
            print(
                "ERROR: Server returned something other than ZIP."
            )

            print(
                "First 200 bytes:"
            )

            print(
                repr(data[:200])
            )

            raise RuntimeError(
                f"{league} server returned HTML/non-ZIP data."
            )

        # Save ZIP
        with open(
            path,
            "wb"
        ) as file:

            file.write(data)

        # Extra ZIP validation
        if not zipfile.is_zipfile(path):

            os.remove(path)

            raise RuntimeError(
                f"{league} downloaded file failed ZIP validation."
            )

        print(
            league,
            "ZIP downloaded successfully."
        )

        return path

    except urllib.error.HTTPError as error:

        print(
            "HTTP ERROR:",
            error.code,
            error.reason
        )

        raise RuntimeError(
            f"Could not download {league}: HTTP {error.code}"
        )

    except urllib.error.URLError as error:

        print(
            "URL ERROR:",
            error.reason
        )

        raise RuntimeError(
            f"Could not download {league}: {error.reason}"
        )

    except Exception as error:

        if os.path.exists(path):
            os.remove(path)

        raise RuntimeError(
            f"Could not download {league}: {error}"
        )


def build():

    print("")
    print("==============================")
    print("STARTING CRICKET DATA BUILD")
    print("==============================")

    # Delete old database
    if os.path.exists(DB):
        os.remove(DB)

    connection = sqlite3.connect(DB)
    cursor = connection.cursor()

    cursor.execute("""
        CREATE TABLE deliveries(
            id INTEGER PRIMARY KEY,
            league TEXT,
            venue TEXT,
            date TEXT,
            innings_no INTEGER,
            batting_team TEXT,
            bowling_team TEXT,
            ball_no INTEGER,
            over_no INTEGER,
            wickets INTEGER,
            runs INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE samples(
            id INTEGER PRIMARY KEY,
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
            runs_to_target INTEGER
        )
    """)

    cursor.execute("""
        CREATE TABLE win_states(
            id INTEGER PRIMARY KEY,
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

    delivery_count = 0
    sample_count = 0
    win_count = 0

    for league in URLS:

        print("")
        print("==============================")
        print("PROCESSING", league)
        print("==============================")

        zip_path = download(league)

        print(
            "Opening ZIP:",
            zip_path
        )

        with zipfile.ZipFile(
            zip_path,
            "r"
        ) as archive:

            filenames = archive.namelist()

            print(
                "Files in ZIP:",
                len(filenames)
            )

            for filename in filenames:

                if not filename.endswith(".json"):
                    continue

                try:

                    match = json.loads(
                        archive.read(filename)
                    )

                except Exception:

                    continue

                info = match.get(
                    "info",
                    {}
                )

                venue = info.get(
                    "venue",
                    ""
                ) or ""

                teams = info.get(
                    "teams",
                    []
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

                winner = info.get(
                    "outcome",
                    {}
                ).get(
                    "winner",
                    ""
                )

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

                    bowling_team = next(
                        (
                            team
                            for team in teams
                            if team != batting_team
                        ),
                        ""
                    )

                    rows = []

                    legal_ball = 0
                    total_runs = 0
                    wickets = 0

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

                            runs = int(
                                delivery
                                .get(
                                    "runs",
                                    {}
                                )
                                .get(
                                    "total",
                                    0
                                )
                            )

                            total_runs += runs

                            wickets += len(
                                delivery.get(
                                    "wickets",
                                    []
                                )
                            )

                            extras = delivery.get(
                                "extras",
                                {}
                            )

                            # Wides and no-balls
                            # are not legal balls.
                            legal = not (
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

                            if legal:

                                legal_ball += 1

                                rows.append({
                                    "ball_no": legal_ball,
                                    "over_no": over_no,
                                    "wickets": wickets,
                                    "total_runs": total_runs
                                })

                    if not rows:
                        continue

                    # Save delivery states
                    for row in rows:

                        cursor.execute(
                            """
                            INSERT INTO deliveries(
                                league,
                                venue,
                                date,
                                innings_no,
                                batting_team,
                                bowling_team,
                                ball_no,
                                over_no,
                                wickets,
                                runs
                            )
                            VALUES(
                                ?,?,?,?,?,?,?,?,?,?
                            )
                            """,
                            (
                                league,
                                venue,
                                date,
                                innings_no,
                                batting_team,
                                bowling_team,
                                row["ball_no"],
                                row["over_no"],
                                row["wickets"],
                                0
                            )
                        )

                        delivery_count += 1

                    # Maximum 120 legal balls
                    max_ball = min(
                        120,
                        rows[-1]["ball_no"]
                    )

                    # Create historical future-target samples
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
                                    runs_to_target
                                )
                                VALUES(
                                    ?,?,?,?,?,?,?,?,?,?,?
                                )
                                """,
                                (
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

                        # Match winner information
                        if winner:

                            cursor.execute(
                                """
                                INSERT INTO win_states(
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
                                    ?,?,?,?,?,?,?,?
                                )
                                """,
                                (
                                    league,
                                    venue,
                                    innings_no,
                                    batting_team,
                                    bowling_team,
                                    current_ball,
                                    current_wickets,
                                    1
                                    if winner == batting_team
                                    else 0
                                )
                            )

                            win_count += 1

                    # Commit periodically
                    if delivery_count % 100000 == 0:

                        connection.commit()

                        print(
                            "Deliveries:",
                            delivery_count,
                            "Samples:",
                            sample_count,
                            "Win states:",
                            win_count
                        )

    print("")
    print("==============================")
    print("CREATING INDEXES")
    print("==============================")

    cursor.execute(
        """
        CREATE INDEX idx_samples_target
        ON samples(
            league,
            target_ball,
            ball_no
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX idx_samples_context
        ON samples(
            venue,
            batting_team,
            bowling_team,
            innings_no,
            wickets
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX idx_samples_team
        ON samples(
            batting_team,
            bowling_team,
            innings_no,
            wickets
        )
        """
    )

    cursor.execute(
        """
        CREATE INDEX idx_win
        ON win_states(
            league,
            innings_no,
            ball_no,
            wickets
        )
        """
    )

    connection.commit()

    connection.close()

    print("")
    print("==============================")
    print("BUILD COMPLETE")
    print("==============================")
    print("Deliveries:", delivery_count)
    print("Samples:", sample_count)
    print("Win states:", win_count)
    print("==============================")


if __name__ == "__main__":
    build()
