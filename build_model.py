import os
import json
import zipfile
import urllib.request
import sqlite3

URLS = {
    "IPL": "https://cricsheet.org/downloads/ipl_json.zip",
    "BBL": "https://cricsheet.org/downloads/bbl_json.zip",
    "WBBL": "https://cricsheet.org/downloads/wbb_json.zip",
}

DB = "cricket_history.db"


def download(league):
    os.makedirs("data", exist_ok=True)

    path = f"data/{league.lower()}_json.zip"

    if not os.path.exists(path):
        print("Downloading", league)

        url = os.getenv(
            f"CRICSHEET_{league}_URL",
            URLS[league]
        )

        print("Download URL:", url)

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=120
        ) as response:

            with open(path, "wb") as file:
                file.write(response.read())

    return path


def build():

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

        print("\nProcessing", league)

        zip_path = download(league)

        with zipfile.ZipFile(zip_path) as archive:

            for filename in archive.namelist():

                if not filename.endswith(".json"):
                    continue

                try:
                    match = json.loads(
                        archive.read(filename)
                    )
                except Exception:
                    continue

                info = match.get("info", {})

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
                                .get("runs", {})
                                .get("total", 0)
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
                            # do not consume a legal ball.
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

                    # Store every possible future legal-ball target.
                    #
                    # Example:
                    #
                    # 2.3 -> 5.2
                    # 7.1 -> 11.4
                    # 15.5 -> 19.2

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

                        # Historical match result
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

                    if delivery_count % 100000 == 0:

                        connection.commit()

                        print(
                            "Deliveries:",
                            delivery_count,
                            "Samples:",
                            sample_count
                        )

    # Indexes make the live app much faster.

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

    print("\n==============================")
    print("BUILD COMPLETE")
    print("==============================")
    print("Deliveries:", delivery_count)
    print("Samples:", sample_count)
    print("Win states:", win_count)


if __name__ == "__main__":
    build()
