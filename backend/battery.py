import pandas as pd

from simulator import generate_microgrid_data


# -----------------------------
# Battery Configuration
# -----------------------------

BATTERY_CAPACITY_KWH = 1000
MAX_CHARGE_KW = 250
MAX_DISCHARGE_KW = 250

INITIAL_SOC_KWH = 400

CHARGE_EFFICIENCY = 0.95
DISCHARGE_EFFICIENCY = 0.95

MIN_SOC_KWH = 100


def simulate_battery(data: pd.DataFrame) -> pd.DataFrame:

    soc = INITIAL_SOC_KWH

    results = []

    for _, row in data.iterrows():

        hour = int(row["hour"])
        solar = float(row["solar_kw"])
        load = float(row["load_kw"])
        tariff = float(row["tariff_rs_per_kwh"])

        battery_charge = 0.0
        battery_discharge = 0.0

        # --------------------------------
        # 1. Use solar to satisfy load
        # --------------------------------

        solar_to_load = min(solar, load)

        remaining_load = load - solar_to_load
        excess_solar = max(solar - solar_to_load, 0)

        # --------------------------------
        # 2. Charge battery from excess solar
        # --------------------------------

        if excess_solar > 0 and soc < BATTERY_CAPACITY_KWH:

            available_capacity = BATTERY_CAPACITY_KWH - soc

            battery_charge = min(
                excess_solar,
                MAX_CHARGE_KW,
                available_capacity / CHARGE_EFFICIENCY
            )

            soc += battery_charge * CHARGE_EFFICIENCY

            excess_solar -= battery_charge

        # --------------------------------
        # 3. Charge from cheap grid
        # --------------------------------

        elif tariff <= 4 and soc < BATTERY_CAPACITY_KWH:

            available_capacity = BATTERY_CAPACITY_KWH - soc

            battery_charge = min(
                MAX_CHARGE_KW,
                available_capacity / CHARGE_EFFICIENCY
            )

            soc += battery_charge * CHARGE_EFFICIENCY

        # --------------------------------
        # 4. Discharge during peak tariff
        # --------------------------------

        if tariff >= 15 and remaining_load > 0:

            available_energy = max(soc - MIN_SOC_KWH, 0)

            battery_discharge = min(
                MAX_DISCHARGE_KW,
                remaining_load,
                available_energy * DISCHARGE_EFFICIENCY
            )

            soc -= battery_discharge / DISCHARGE_EFFICIENCY

        # --------------------------------
        # 5. Remaining energy from grid
        # --------------------------------

        grid_import = (
            remaining_load
            + battery_charge
            - battery_discharge
            - excess_solar
        )

        grid_import = max(grid_import, 0)

        # --------------------------------
        # 6. Calculate cost
        # --------------------------------

        grid_cost = grid_import * tariff

        results.append({
            "hour": hour,
            "solar_kw": solar,
            "load_kw": load,
            "tariff_rs_per_kwh": tariff,
            "solar_to_load_kw": round(solar_to_load, 2),
            "battery_charge_kw": round(battery_charge, 2),
            "battery_discharge_kw": round(battery_discharge, 2),
            "battery_soc_kwh": round(soc, 2),
            "grid_import_kw": round(grid_import, 2),
            "grid_cost_rs": round(grid_cost, 2),
        })

    return pd.DataFrame(results)


# -----------------------------
# Run Simulation
# -----------------------------

if __name__ == "__main__":

    data = generate_microgrid_data()

    results = simulate_battery(data)

    print("\nVOLTFORGE BATTERY SIMULATION")
    print("=" * 90)

    print(
        results[
            [
                "hour",
                "solar_kw",
                "load_kw",
                "tariff_rs_per_kwh",
                "battery_charge_kw",
                "battery_discharge_kw",
                "battery_soc_kwh",
                "grid_import_kw",
                "grid_cost_rs",
            ]
        ].to_string(index=False)
    )

    total_cost = results["grid_cost_rs"].sum()

    print("\n" + "=" * 90)
    print(f"Total Grid Cost: ₹{total_cost:,.2f}")
    print(f"Final Battery SOC: {results.iloc[-1]['battery_soc_kwh']:.2f} kWh")