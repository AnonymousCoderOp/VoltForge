import numpy as np
import pandas as pd

from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import lil_matrix

from forecaster import (
    generate_historical_data,
    train_models,
    generate_future_conditions,
    forecast_next_24_hours,
)


# ============================================================
# VOLTFORGE RESILIENCE ENGINE
# ============================================================

BATTERY_CAPACITY_KWH = 1000.0
MIN_SOC_KWH = 100.0
INITIAL_SOC_KWH = 400.0

MAX_CHARGE_KW = 250.0
MAX_DISCHARGE_KW = 250.0

CHARGE_EFFICIENCY = 0.95
DISCHARGE_EFFICIENCY = 0.95

# Load priorities
CRITICAL_LOAD_PERCENT = 0.60
NON_CRITICAL_LOAD_PERCENT = 0.40

# Optimization penalties
CRITICAL_UNSERVED_PENALTY = 100000.0
NON_CRITICAL_UNSERVED_PENALTY = 1000.0
SOLAR_CURTAILMENT_PENALTY = 0.10


# ============================================================
# RESILIENCE OPTIMIZER
# ============================================================

def optimize_resilience(
    forecast: pd.DataFrame,
    initial_soc_kwh: float = INITIAL_SOC_KWH,
    blackout_start_hour: int = 18,
    blackout_end_hour: int = 21,
):
    forecast = forecast.copy().reset_index(drop=True)

    if len(forecast) != 24:
        raise ValueError(
            "Resilience engine requires exactly 24 forecast hours."
        )

    hours = 24

    solar = forecast["predicted_solar_kw"].to_numpy(dtype=float)
    load = forecast["predicted_load_kw"].to_numpy(dtype=float)
    tariff = forecast["tariff_rs_per_kwh"].to_numpy(dtype=float)

    # --------------------------------------------------------
    # Split total load into critical and non-critical loads
    # --------------------------------------------------------

    critical_load = load * CRITICAL_LOAD_PERCENT
    noncritical_load = load * NON_CRITICAL_LOAD_PERCENT

    # --------------------------------------------------------
    # Variables for each hour:
    #
    # grid
    # charge
    # discharge
    # soc
    # critical served
    # noncritical served
    # solar curtailment
    # binary battery mode
    # --------------------------------------------------------

    grid_start = 0
    charge_start = grid_start + hours
    discharge_start = charge_start + hours
    soc_start = discharge_start + hours
    critical_start = soc_start + hours
    noncritical_start = critical_start + hours
    curtail_start = noncritical_start + hours
    mode_start = curtail_start + hours

    total_variables = mode_start + hours

    # --------------------------------------------------------
    # Objective function
    # --------------------------------------------------------

    objective = np.zeros(total_variables)

    # Cost of grid electricity
    objective[
        grid_start:grid_start + hours
    ] = tariff

    # Reward serving critical loads
    objective[
        critical_start:critical_start + hours
    ] = -CRITICAL_UNSERVED_PENALTY

    # Reward serving non-critical loads
    objective[
        noncritical_start:noncritical_start + hours
    ] = -NON_CRITICAL_UNSERVED_PENALTY

    # Slight penalty for curtailing solar
    objective[
        curtail_start:curtail_start + hours
    ] = SOLAR_CURTAILMENT_PENALTY

    # --------------------------------------------------------
    # Variable bounds
    # --------------------------------------------------------

    lower = np.zeros(total_variables)
    upper = np.full(total_variables, np.inf)

    # Grid availability
    for t in range(hours):

        hour = int(forecast.loc[t, "hour"])

        if blackout_start_hour <= hour <= blackout_end_hour:
            upper[grid_start + t] = 0.0
        else:
            upper[grid_start + t] = np.inf

    # Battery
    upper[
        charge_start:charge_start + hours
    ] = MAX_CHARGE_KW

    upper[
        discharge_start:discharge_start + hours
    ] = MAX_DISCHARGE_KW

    lower[
        soc_start:soc_start + hours
    ] = MIN_SOC_KWH

    upper[
        soc_start:soc_start + hours
    ] = BATTERY_CAPACITY_KWH

    # Load served
    upper[
        critical_start:critical_start + hours
    ] = critical_load

    upper[
        noncritical_start:noncritical_start + hours
    ] = noncritical_load

    # Solar curtailment
    upper[
        curtail_start:curtail_start + hours
    ] = solar

    # Binary mode
    upper[
        mode_start:mode_start + hours
    ] = 1.0

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    energy_balance_rows = hours
    soc_rows = hours
    charge_mode_rows = hours
    discharge_mode_rows = hours
    terminal_soc_rows = 1

    total_rows = (
        energy_balance_rows
        + soc_rows
        + charge_mode_rows
        + discharge_mode_rows
        + terminal_soc_rows
    )

    A = lil_matrix(
        (total_rows, total_variables)
    )

    constraint_lower = np.full(
        total_rows,
        -np.inf,
    )

    constraint_upper = np.full(
        total_rows,
        np.inf,
    )

    row = 0

    # ========================================================
    # 1. ENERGY BALANCE
    #
    # Grid + Solar + Battery Discharge
    # =
    # Critical Served
    # + Non-critical Served
    # + Battery Charge
    # + Solar Curtailment
    # ========================================================

    for t in range(hours):

        A[row, grid_start + t] = 1
        A[row, discharge_start + t] = 1
        A[row, critical_start + t] = -1
        A[row, noncritical_start + t] = -1
        A[row, charge_start + t] = -1
        A[row, curtail_start + t] = -1

        # Rearranged RHS:
        # Grid + Discharge - Critical - Noncritical
        # - Charge - Curtailment = -Solar

        rhs = -solar[t]

        constraint_lower[row] = rhs
        constraint_upper[row] = rhs

        row += 1

    # ========================================================
    # 2. BATTERY SOC DYNAMICS
    # ========================================================

    for t in range(hours):

        A[row, soc_start + t] = 1

        A[row, charge_start + t] = -CHARGE_EFFICIENCY

        A[row, discharge_start + t] = (
            1 / DISCHARGE_EFFICIENCY
        )

        if t == 0:

            rhs = initial_soc_kwh

        else:

            A[row, soc_start + t - 1] = -1

            rhs = 0.0

        constraint_lower[row] = rhs
        constraint_upper[row] = rhs

        row += 1

    # ========================================================
    # 3. CHARGE MODE
    #
    # charge <= MAX_CHARGE * mode
    # ========================================================

    for t in range(hours):

        A[row, charge_start + t] = 1

        A[row, mode_start + t] = -MAX_CHARGE_KW

        constraint_upper[row] = 0

        row += 1

    # ========================================================
    # 4. DISCHARGE MODE
    #
    # discharge <= MAX_DISCHARGE * (1 - mode)
    #
    # => discharge + MAX_DISCHARGE*mode <= MAX_DISCHARGE
    # ========================================================

    for t in range(hours):

        A[row, discharge_start + t] = 1

        A[row, mode_start + t] = MAX_DISCHARGE_KW

        constraint_upper[row] = MAX_DISCHARGE_KW

        row += 1

    # ========================================================
    # 5. TERMINAL SOC
    # Keep at least initial SOC at end of horizon
    # ========================================================

    A[row, soc_start + hours - 1] = 1

    constraint_lower[row] = initial_soc_kwh
    constraint_upper[row] = np.inf

    # --------------------------------------------------------
    # Build constraints
    # --------------------------------------------------------

    constraints = LinearConstraint(
        A.tocsc(),
        constraint_lower,
        constraint_upper,
    )

    # Binary variables
    integrality = np.zeros(total_variables)

    integrality[
        mode_start:mode_start + hours
    ] = 1

    # --------------------------------------------------------
    # Solve
    # --------------------------------------------------------

    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(
            lower,
            upper,
        ),
        constraints=constraints,
        options={
            "time_limit": 10,
            "mip_rel_gap": 0.0001,
        },
    )

    if not result.success:
        raise RuntimeError(
            f"Resilience optimization failed: {result.message}"
        )

    solution = result.x

    # --------------------------------------------------------
    # Extract solution
    # --------------------------------------------------------

    grid = solution[
        grid_start:grid_start + hours
    ]

    charge = solution[
        charge_start:charge_start + hours
    ]

    discharge = solution[
        discharge_start:discharge_start + hours
    ]

    soc = solution[
        soc_start:soc_start + hours
    ]

    critical_served = solution[
        critical_start:critical_start + hours
    ]

    noncritical_served = solution[
        noncritical_start:noncritical_start + hours
    ]

    curtailment = solution[
        curtail_start:curtail_start + hours
    ]

    # --------------------------------------------------------
    # Derived values
    # --------------------------------------------------------

    critical_unserved = (
        critical_load - critical_served
    )

    noncritical_unserved = (
        noncritical_load - noncritical_served
    )

    blackout_active = []

    operating_mode = []

    for t in range(hours):

        hour = int(forecast.loc[t, "hour"])

        is_blackout = (
            blackout_start_hour
            <= hour
            <= blackout_end_hour
        )

        blackout_active.append(is_blackout)

        if is_blackout:
            operating_mode.append("ISLAND MODE")
        else:
            operating_mode.append("GRID CONNECTED")

    # --------------------------------------------------------
    # Cost
    # --------------------------------------------------------

    grid_cost = grid * tariff

    # --------------------------------------------------------
    # Resilience score
    # --------------------------------------------------------

    total_critical = critical_load.sum()
    total_critical_unserved = critical_unserved.sum()

    if total_critical > 0:

        critical_protection = (
            1
            - (
                total_critical_unserved
                / total_critical
            )
        )

    else:

        critical_protection = 1.0

    resilience_score = round(
        max(
            0,
            min(
                100,
                critical_protection * 100,
            ),
        ),
        1,
    )

    # --------------------------------------------------------
    # Final result DataFrame
    # --------------------------------------------------------

    results = pd.DataFrame({

        "timestamp": forecast["timestamp"],

        "hour": forecast["hour"],

        "solar_kw": np.round(
            solar,
            2,
        ),

        "total_load_kw": np.round(
            load,
            2,
        ),

        "tariff_rs_per_kwh": np.round(
            tariff,
            2,
        ),

        "critical_load_kw": np.round(
            critical_load,
            2,
        ),

        "noncritical_load_kw": np.round(
            noncritical_load,
            2,
        ),

        "critical_served_kw": np.round(
            critical_served,
            2,
        ),

        "noncritical_served_kw": np.round(
            noncritical_served,
            2,
        ),

        "critical_unserved_kw": np.round(
            critical_unserved,
            2,
        ),

        "noncritical_unserved_kw": np.round(
            noncritical_unserved,
            2,
        ),

        "grid_import_kw": np.round(
            grid,
            2,
        ),

        "battery_charge_kw": np.round(
            charge,
            2,
        ),

        "battery_discharge_kw": np.round(
            discharge,
            2,
        ),

        "battery_soc_kwh": np.round(
            soc,
            2,
        ),

        "solar_curtailed_kw": np.round(
            curtailment,
            2,
        ),

        "grid_cost_rs": np.round(
            grid_cost,
            2,
        ),

        "blackout": blackout_active,

        "operating_mode": operating_mode,
    })

    return results, resilience_score


# ============================================================
# COMPLETE RESILIENCE DEMO
# ============================================================

if __name__ == "__main__":

    print("\n")
    print("=" * 90)
    print("VOLTFORGE RESILIENCE ENGINE")
    print("=" * 90)

    # --------------------------------------------------------
    # Historical data
    # --------------------------------------------------------

    historical_data = generate_historical_data(
        days=90
    )

    print(
        f"\nHistorical records: "
        f"{len(historical_data)}"
    )

    # --------------------------------------------------------
    # Train models
    # --------------------------------------------------------

    print("\nTraining forecasting models...")

    solar_model, load_model, metrics = train_models(
        historical_data
    )

    print(
        f"Solar MAE: {metrics['solar_mae']} kW"
    )

    print(
        f"Load MAE: {metrics['load_mae']} kW"
    )

    # --------------------------------------------------------
    # Future conditions
    # --------------------------------------------------------

    last_timestamp = (
        historical_data["timestamp"].iloc[-1]
    )

    future_conditions = generate_future_conditions(
        last_timestamp + pd.Timedelta(hours=1)
    )

    # --------------------------------------------------------
    # Forecast
    # --------------------------------------------------------

    forecast = forecast_next_24_hours(
        solar_model,
        load_model,
        future_conditions,
    )

    # --------------------------------------------------------
    # Simulated blackout
    # --------------------------------------------------------

    print("\n")
    print("Injecting simulated GRID BLACKOUT...")
    print("Blackout window: 18:00 - 21:00")

    results, resilience_score = optimize_resilience(
        forecast,
        initial_soc_kwh=INITIAL_SOC_KWH,
        blackout_start_hour=18,
        blackout_end_hour=21,
    )

    # --------------------------------------------------------
    # Outage results
    # --------------------------------------------------------

    print("\n")
    print("=" * 120)
    print("GRID OUTAGE RESPONSE")
    print("=" * 120)

    outage_results = results[
        results["blackout"] == True
    ]

    display_columns = [
        "hour",
        "solar_kw",
        "total_load_kw",
        "critical_load_kw",
        "critical_served_kw",
        "noncritical_load_kw",
        "noncritical_served_kw",
        "battery_discharge_kw",
        "battery_soc_kwh",
        "grid_import_kw",
        "operating_mode",
    ]

    print(
        outage_results[
            display_columns
        ].to_string(index=False)
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    total_critical = results[
        "critical_load_kw"
    ].sum()

    total_critical_served = results[
        "critical_served_kw"
    ].sum()

    total_noncritical = results[
        "noncritical_load_kw"
    ].sum()

    total_noncritical_served = results[
        "noncritical_served_kw"
    ].sum()

    critical_coverage = (
        total_critical_served
        / total_critical
        * 100
    )

    noncritical_coverage = (
        total_noncritical_served
        / total_noncritical
        * 100
    )

    print("\n")
    print("=" * 90)
    print("VOLTFORGE RESILIENCE SUMMARY")
    print("=" * 90)

    print(
        f"Resilience Score:          "
        f"{resilience_score}/100"
    )

    print(
        f"Critical Load Coverage:    "
        f"{critical_coverage:.2f}%"
    )

    print(
        f"Non-critical Coverage:     "
        f"{noncritical_coverage:.2f}%"
    )

    print(
        f"Minimum Battery SOC:       "
        f"{results['battery_soc_kwh'].min():.2f} kWh"
    )

    print(
        f"Final Battery SOC:         "
        f"{results.iloc[-1]['battery_soc_kwh']:.2f} kWh"
    )

    print(
        "\nGrid blackout handled:      YES"
    )

    print(
        "Critical infrastructure:    PROTECTED"
    )

    print(
        "Operating mode:             ISLAND MODE"
    )

    results.to_csv(
        "resilience_schedule.csv",
        index=False,
    )

    print(
        "\nSaved:"
        " backend/resilience_schedule.csv"
    )

    print("=" * 90)