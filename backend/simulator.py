import numpy as np
import pandas as pd


# -----------------------------
# VoltForge Microgrid Simulator
# -----------------------------

def generate_microgrid_data():
    hours = np.arange(24)

    solar = []
    load = []
    tariff = []

    for hour in hours:

        # -------------------------
        # Solar generation
        # -------------------------
        if 6 <= hour <= 19:
            solar_power = 500 * np.exp(-((hour - 13) ** 2) / 12)
        else:
            solar_power = 0

        # -------------------------
        # Campus electricity load
        # -------------------------
        morning_peak = 180 * np.exp(-((hour - 9) ** 2) / 8)
        evening_peak = 220 * np.exp(-((hour - 19) ** 2) / 10)

        base_load = 180

        campus_load = (
            base_load
            + morning_peak
            + evening_peak
        )

        # -------------------------
        # Electricity tariff
        # -------------------------
        if 0 <= hour < 6:
            electricity_tariff = 4

        elif 6 <= hour < 18:
            electricity_tariff = 8

        elif 18 <= hour < 22:
            electricity_tariff = 15

        else:
            electricity_tariff = 6

        solar.append(round(solar_power, 2))
        load.append(round(campus_load, 2))
        tariff.append(electricity_tariff)

    data = pd.DataFrame({
        "hour": hours,
        "solar_kw": solar,
        "load_kw": load,
        "tariff_rs_per_kwh": tariff
    })

    return data


if __name__ == "__main__":
    data = generate_microgrid_data()

    print("\nVOLTFORGE MICROGRID SIMULATION")
    print("=" * 50)
    print(data.to_string(index=False))