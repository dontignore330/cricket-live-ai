"""
Build multi-league feature files from Cricsheet JSON zip archives.
"""

import os
import zipfile
import json
import urllib.request
import pandas as pd


URLS = {
    "ipl": "https://cricsheet.org/downloads/ipl_json.zip",
    "bbl": "https://cricsheet.org/downloads/bbl_json.zip",
    "wbbl": "https://cricsheet.org/downloads/wbbl_json.zip",
}


def get_zip(key):
    os.makedirs("data", exist_ok=True)

    path = f"data/{key}.zip"

    if not os.path.exists(path):
        url = os.getenv(
            f"CRICSHEET_{key.upper()}_URL",
            URLS[key]
        )

        print(f"Downloading {key.upper()}...")
        urllib.request.urlretrieve(url, path)

    return zipfile.ZipFile(path)


def window_balls(over):
    # Five-over historical session = 30 legal-ball slots.
    # This is the training target used by this foundation model.
    return 30


def parse(key):

    z = get_zip(key)

    rows = []

    for name in z.namelist():

        if not name.endswith(".json"):
            continue

        try:
            match = json.loads(z.read(name))
        except Exception:
            continue

        info = match.get("info", {})

        venue = info.get("venue", "")

        teams = info.get("teams", [])

        dates = info.get("dates", [""])

        date = str(dates[0]) if dates else ""

        for innings in match.get("innings", []):

            batting_team = innings.get("team", "")

            bowling_team = next(
                (
                    team
                    for team in teams
                    if team != batting_team
                ),
                ""
            )

            deliveries = []

            for over_data in innings.get("overs", []):

                over_number = over_data.get("over", 0)

                for delivery in over_data.get(
                    "deliveries", []
                ):

                    deliveries.append(
                        (over_number, delivery)
                    )

            for i, (over_number, delivery) in enumerate(
                deliveries
            ):

                future_deliveries = deliveries[
                    i + 1:
                    i + 1 + window_balls(over_number)
                ]

                future_runs = sum(
                    d.get("runs", {}).get("total", 0)
                    for _, d in future_deliveries
                )

                if over_number < 6:
                    phase = "Powerplay"

                elif over_number < 15:
                    phase = "Middle"

                else:
                    phase = "Death"

                rows.append(
                    {
                        "league": key.upper(),
                        "date": date,
                        "venue": venue,
                        "batting_team": batting_team,
                        "bowling_team": bowling_team,
                        "over": over_number,
                        "phase": phase,
                        "future_runs": future_runs,
                    }
                )

    output = f"{key}_features.csv"

    pd.DataFrame(rows).to_csv(
        output,
        index=False
    )

    print(
        f"{key.upper()}: {len(rows):,} rows saved to {output}"
    )


def main():

    for league in URLS:
        try:
            parse(league)

        except Exception as error:

            print(
                f"ERROR while processing {league.upper()}: "
                f"{error}"
            )

    print("Historical data build completed.")


if __name__ == "__main__":
    main()
