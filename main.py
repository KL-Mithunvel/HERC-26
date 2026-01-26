import time
from sensors import GPS


def main():
    print("HERC-26 main started")

    gps = GPS()
    gps.open()

    try:
        while True:
            data = gps.read()

            if data.get("ok"):
                print(
                    f"[GPS] {data['utc_date']} {data['utc_time']} | "
                    f"Lat={data['lat']} Lon={data['lon']}"
                )
            else:
                print("[GPS ERROR]", data.get("error"))

            time.sleep(0.5)

    finally:
        gps.close()


if __name__ == "__main__":
    main()
