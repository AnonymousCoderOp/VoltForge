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
# VOLTFORGE DISPATCH OPTIMIZER
# ============================================================

BATTERY_CAPACITY_KWH = 1000.0
MIN_SOC_KWH = 100.0
INITIAL_SOC_KWH = 400.0

MAX_CHARGE_KW = 250.0
MAX_DISCHARGE_KW = 250.0

CHARGE_EFFICIENCY = 0.95
DISCHARGE_EFFICIENCY = 0.95

# Small penalty to discourage unnecessary battery cycling.
BATTERY_DEGRADATION_COST_RS = 0.05


# ============================================================
# VARIABLE INDEXING
# ============================================================

def variable_indices(hours: int):
    """
    Create slices for all decision variables.

    Variables for every hour:
    - Grid import
    - Battery charge
    - Battery discharge
    - Battery SOC
    - Solar curtailment
    - Binary battery mode
    """

    grid_start = 0
    charge_start = grid_start + hours
    discharge_start = charge_start + hours
    soc_start = discharge_start + hours
    curtail_start = soc_start + hours
    mode_start = curtail_start + hours

    total_variables = mode_start + hours

    return {
        "grid": slice(grid_start, charge_start),
        "charge": slice(charge_start, discharge_start),
        "discharge": slice(discharge_start, soc_start),
        "soc": slice(soc_start, curtail_start),
        "curtail": slice(curtail_start, mode_start),
        "mode": slice(mode_start, total_variables),
        "total": total_variables,
    }


# ============================================================
# OPTIMIZATION FUNCTION
# ============================================================

def optimize_dispatch(
    forecast: pd.DataFrame,
    initial_soc_kwh: float = INITIAL_SOC_KWH,
) -> pd.DataFrame:

    if len(forecast) != 24:
        raise ValueError(
            "VoltForge optimizer requires exactly 24 forecast hours."
        )

    forecast = forecast.copy().reset_index(drop=True)

    # --------------------------------------------------------
    # Forecast inputs
    # --------------------------------------------------------

    solar = forecast["predicted_solar_kw"].to_numpy(dtype=float)

    load = forecast["predicted_load_kw"].to_numpy(dtype=float)

    tariff = forecast["tariff_rs_per_kwh"].to_numpy(dtype=float)

    hours = len(forecast)

    # Physical solar limits
    for i in range(hours):
        if not 6 <= int(forecast.loc[i, "hour"]) <= 19:
            solar[i] = 0.0

    solar = np.clip(solar, 0, 500)
    load = np.clip(load, 50, None)

    # --------------------------------------------------------
    # Variable structure
    # --------------------------------------------------------

    idx = variable_indices(hours)

    n = idx["total"]

    # Objective function
    objective = np.zeros(n)

    # Grid electricity cost
    objective[idx["grid"]] = tariff

    # Small degradation penalty
    objective[idx["charge"]] = BATTERY_DEGRADATION_COST_RS
    objective[idx["discharge"]] = BATTERY_DEGRADATION_COST_RS

    # --------------------------------------------------------
    # Variable bounds
    # --------------------------------------------------------

    lower_bounds = np.zeros(n)
    upper_bounds = np.full(n, np.inf)

    # Grid
    upper_bounds[idx["grid"]] = np.inf

    # Battery charge
    upper_bounds[idx["charge"]] = MAX_CHARGE_KW

    # Battery discharge
    upper_bounds[idx["discharge"]] = MAX_DISCHARGE_KW

    # Battery SOC
    lower_bounds[idx["soc"]] = MIN_SOC_KWH
    upper_bounds[idx["soc"]] = BATTERY_CAPACITY_KWH

    # Solar curtailment
    upper_bounds[idx["curtail"]] = solar

    # Binary operating mode
    # 0 = discharge/idle
    # 1 = charge/idle
    lower_bounds[idx["mode"]] = 0
    upper_bounds[idx["mode"]] = 1

    # --------------------------------------------------------
    # Constraints
    # --------------------------------------------------------

    # Energy balance
    energy_rows = hours

    # SOC equations
    soc_rows = hours

    # Charge/discharge mode constraints
    charge_mode_rows = hours
    discharge_mode_rows = hours

    # Final SOC requirement
    terminal_row = 1

    total_constraints = (
        energy_rows
        + soc_rows
        + charge_mode_rows
        + discharge_mode_rows
        + terminal_row
    )

    A = lil_matrix((total_constraints, n))

    constraint_lower = np.full(
        total_constraints,
        -np.inf,
        dtype=float,
    )

    constraint_upper = np.full(
        total_constraints,
        np.inf,
        dtype=float,
    )

    row = 0

    # ========================================================
    # 1. ENERGY BALANCE
    # ========================================================
    #
    # Grid + Solar + Discharge
    # =
    # Load + Charge + Curtailment
    #
    # Rearranged:
    #
    # Grid + Discharge - Charge - Curtailment
    # =
    # Load - Solar
    #

    for t in range(hours):

        A[row, idx["grid"].start + t] = 1

        A[row, idx["discharge"].start + t] = 1

        A[row, idx["charge"].start + t] = -1

        A[row, idx["curtail"].start + t] = -1

        rhs = load[t] - solar[t]

        constraint_lower[row] = rhs
        constraint_upper[row] = rhs

        row += 1

    # ========================================================
    # 2. BATTERY SOC DYNAMICS
    # ========================================================

    for t in range(hours):

        A[row, idx["soc"].start + t] = 1

        A[row, idx["charge"].start + t] = (
            -CHARGE_EFFICIENCY
        )

        A[row, idx["discharge"].start + t] = (
            1 / DISCHARGE_EFFICIENCY
        )

        if t > 0:

            A[row, idx["soc"].start + t - 1] = -1

            rhs = 0.0

        else:

            rhs = initial_soc_kwh

        constraint_lower[row] = rhs
        constraint_upper[row] = rhs

        row += 1

    # ========================================================
    # 3. CHARGE MODE
    # ========================================================
    #
    # Charge <= MAX_CHARGE * mode
    #

    for t in range(hours):

        A[row, idx["charge"].start + t] = 1

        A[row, idx["mode"].start + t] = -MAX_CHARGE_KW

        constraint_upper[row] = 0

        row += 1

    # ========================================================
    # 4. DISCHARGE MODE
    # ========================================================
    #
    # Discharge <= MAX_DISCHARGE * (1 - mode)
    #
    # Rearranged:
    #
    # Discharge + MAX_DISCHARGE * mode <= MAX_DISCHARGE
    #

    for t in range(hours):

        A[row, idx["discharge"].start + t] = 1

        A[row, idx["mode"].start + t] = MAX_DISCHARGE_KW

        constraint_upper[row] = MAX_DISCHARGE_KW

        row += 1

    # ========================================================
    # 5. TERMINAL SOC
    # ========================================================
    #
    # Keep at least the initial battery reserve at the end
    # of the 24-hour planning horizon.
    #

    A[row, idx["soc"].start + hours - 1] = 1

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

    # Binary variables for charge/discharge mode
    integrality = np.zeros(n)

    integrality[idx["mode"]] = 1

    # --------------------------------------------------------
    # Solve
    # --------------------------------------------------------

    result = milp(
        c=objective,
        integrality=integrality,
        bounds=Bounds(
            lower_bounds,
            upper_bounds,
        ),
        constraints=constraints,
        options={
            "time_limit": 10,
            "mip_rel_gap": 0.0001,
        },
    )

    if not result.success:
        raise RuntimeError(
            f"Optimization failed: {result.message}"
        )

    # --------------------------------------------------------
    # Extract solution
    # --------------------------------------------------------

    solution = result.x

    grid_import = solution[idx["grid"]]
    charge = solution[idx["charge"]]
    discharge = solution[idx["discharge"]]
    soc = solution[idx["soc"]]
    curtailment = solution[idx["curtail"]]

    # --------------------------------------------------------
    # Derived values
    # --------------------------------------------------------

    solar_to_load = np.minimum(
        solar,
        load,
    )

    solar_excess = np.maximum(
        solar - load,
        0,
    )

    solar_to_battery = np.minimum(
        charge,
        solar_excess,
    )

    battery_from_grid = np.maximum(
        charge - solar_excess,
        0,
    )

    grid_cost = grid_import * tariff

    degradation_cost = (
        charge + discharge
    ) * BATTERY_DEGRADATION_COST_RS

    total_operating_cost = (
        grid_cost + degradation_cost
    )

    battery_power = discharge - charge

    # --------------------------------------------------------
    # Operating mode
    # --------------------------------------------------------

    modes = []

    for t in range(hours):

        if discharge[t] > 0.1:
            modes.append("DISCHARGING")

        elif charge[t] > 0.1:
            modes.append("CHARGING")

        else:
            modes.append("IDLE")

    # --------------------------------------------------------
    # Final result table
    # --------------------------------------------------------

    result_df = pd.DataFrame({
        "timestamp": forecast["timestamp"],
        "hour": forecast["hour"],
        "solar_forecast_kw": np.round(solar, 2),
        "load_forecast_kw": np.round(load, 2),
        "tariff_rs_per_kwh": np.round(tariff, 2),

        "solar_to_load_kw": np.round(
            solar_to_load,
            2,
        ),

        "solar_to_battery_kw": np.round(
            solar_to_battery,
            2,
        ),

        "battery_from_grid_kw": np.round(
            battery_from_grid,
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

        "battery_power_kw": np.round(
            battery_power,
            2,
        ),

        "battery_soc_kwh": np.round(
            soc,
            2,
        ),

        "grid_import_kw": np.round(
            grid_import,
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

        "battery_degradation_cost_rs": np.round(
            degradation_cost,
            2,
        ),

        "total_operating_cost_rs": np.round(
            total_operating_cost,
            2,
        ),

        "battery_mode": modes,
    })

    return result_df


# ============================================================
# BASELINE CALCULATION
# ============================================================

def calculate_baseline_cost(
    forecast: pd.DataFrame,
) -> float:

    solar = forecast["predicted_solar_kw"].to_numpy(
        dtype=float
    )

    load = forecast["predicted_load_kw"].to_numpy(
        dtype=float
    )

    tariff = forecast["tariff_rs_per_kwh"].to_numpy(
        dtype=float
    )

    solar = np.clip(solar, 0, 500)
    load = np.clip(load, 50, None)

    for i in range(len(forecast)):

        hour = int(forecast.loc[i, "hour"])

        if not 6 <= hour <= 19:
            solar[i] = 0

    grid_without_battery = np.maximum(
        load - solar,
        0,
    )

    baseline_cost = np.sum(
        grid_without_battery * tariff
    )

    return float(baseline_cost)


# ============================================================
# COMPLETE VOLTFORGE PIPELINE
# ============================================================

if __name__ == "__main__":

    print("\n")
    print("=" * 80)
    print("VOLTFORGE AI DISPATCH OPTIMIZER")
    print("=" * 80)

    # --------------------------------------------------------
    # Generate historical data
    # --------------------------------------------------------

    historical_data = generate_historical_data(
        days=90
    )

    print(
        f"\nHistorical data: "
        f"{len(historical_data)} hourly records"
    )

    # --------------------------------------------------------
    # Train forecasting models
    # --------------------------------------------------------

    print("\nTraining AI forecasting models...")

    solar_model, load_model, metrics = train_models(
        historical_data
    )

    print(
        f"Solar forecast MAE: "
        f"{metrics['solar_mae']} kW"
    )

    print(
        f"Load forecast MAE: "
        f"{metrics['load_mae']} kW"
    )

    # --------------------------------------------------------
    # Create next 24-hour conditions
    # --------------------------------------------------------

    last_timestamp = historical_data[
        "timestamp"
    ].iloc[-1]

    future_conditions = generate_future_conditions(
        last_timestamp + pd.Timedelta(hours=1)
    )

    # --------------------------------------------------------
    # AI forecast
    # --------------------------------------------------------

    forecast = forecast_next_24_hours(
        solar_model,
        load_model,
        future_conditions,
    )

    # --------------------------------------------------------
    # Optimization
    # --------------------------------------------------------

    print("\nRunning 24-hour optimization...")

    dispatch = optimize_dispatch(
        forecast,
        initial_soc_kwh=INITIAL_SOC_KWH,
    )

    # --------------------------------------------------------
    # Baseline
    # --------------------------------------------------------

    baseline_cost = calculate_baseline_cost(
        forecast
    )

    optimized_grid_cost = dispatch[
        "grid_cost_rs"
    ].sum()

    optimized_total_cost = dispatch[
        "total_operating_cost_rs"
    ].sum()

    savings = baseline_cost - optimized_grid_cost

    savings_percentage = (
        (savings / baseline_cost) * 100
        if baseline_cost > 0
        else 0
    )

    # --------------------------------------------------------
    # Display
    # --------------------------------------------------------

    print("\n")
    print("=" * 120)
    print("OPTIMAL 24-HOUR BATTERY DISPATCH")
    print("=" * 120)

    display_columns = [
        "hour",
        "solar_forecast_kw",
        "load_forecast_kw",
        "tariff_rs_per_kwh",
        "battery_charge_kw",
        "battery_discharge_kw",
        "battery_soc_kwh",
        "grid_import_kw",
        "battery_mode",
    ]

    print(
        dispatch[
            display_columns
        ].to_string(index=False)
    )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print("\n")
    print("=" * 80)
    print("VOLTFORGE OPTIMIZATION SUMMARY")
    print("=" * 80)

    print(
        f"Baseline grid cost:        ₹{baseline_cost:,.2f}"
    )

    print(
        f"Optimized grid cost:       ₹{optimized_grid_cost:,.2f}"
    )

    print(
        f"Battery operating cost:    ₹{optimized_total_cost:,.2f}"
    )

    print(
        f"Estimated grid savings:    ₹{savings:,.2f}"
    )

    print(
        f"Cost reduction:            {savings_percentage:.2f}%"
    )

    print(
        f"Final battery SOC:         "
        f"{dispatch.iloc[-1]['battery_soc_kwh']:.2f} kWh"
    )

    print(
        "\nSolver status: OPTIMAL"
    )

    # --------------------------------------------------------
    # Save for frontend / analysis
    # --------------------------------------------------------

    dispatch.to_csv(
        "optimizer_schedule.csv",
        index=False,
    )

    print(
        "\nSchedule saved to:"
        " backend/optimizer_schedule.csv"
    )

    print("=" * 80)