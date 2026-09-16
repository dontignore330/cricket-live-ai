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

                columns = data.get("columns", [])
                rows = data.get("rows", [])

                # TigZig returns rows as arrays.
                # Convert each row into a dictionary.
                result = []

                for row in rows:
                    result.append(
                        dict(zip(columns, row))
                    )

                return result

            print("API ERROR:")
            print(r.text[:1000])

        except Exception as e:
            print("REQUEST ERROR:", e)

        time.sleep(5)

    return []
