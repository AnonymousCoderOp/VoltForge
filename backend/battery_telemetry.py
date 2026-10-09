"""Illustrative battery telemetry estimates for VoltForge's synthetic simulation.

These estimates are software-model outputs, not sensor readings and not a
validated electrochemical or thermal model for a specific battery chemistry.
"""

from __future__ import annotations

import pandas as pd

BATTERY_CAPACITY_KWH = 1000.0
MAX_CHARGE_KW = 250.0
MAX_DISCHARGE_KW = 250.0

# Demonstration-only assumptions; calibrate before making engineering claims.
TEMP_RISE_COEFFICIENT_C_PER_KW2 = 0.00008
DEGRADATION_PERCENT_PER_EQUIVALENT_FULL_CYCLE = 0.03
INITIAL_HEALTH_PERCENT_ASSUMPTION = 100.0
INTERVAL_HOURS = 1.0


def estimate_battery_telemetry(
    forecast: pd.DataFrame,
    dispatch: pd.DataFrame,
) -> dict:
    """Estimate battery thermal/cycle indicators from a simulated schedule."""
    if len(forecast) != len(dispatch):
        raise ValueError("Forecast and dispatch must have the same number of rows.")

    if dispatch.empty:
        raise ValueError("Cannot estimate battery telemetry from an empty schedule.")

    hourly_estimates = []
    total_throughput_kwh = 0.0

    forecast_rows = forecast.reset_index(drop=True)
    dispatch_rows = dispatch.reset_index(drop=True)

    for index in range(len(dispatch_rows)):
        forecast_row = forecast_rows.iloc[index]
        dispatch_row = dispatch_rows.iloc[index]

        charge_kw = max(0.0, float(dispatch_row.get("battery_charge_kw", 0.0)))
        discharge_kw = max(0.0, float(dispatch_row.get("battery_discharge_kw", 0.0)))
        soc_kwh = float(dispatch_row.get("battery_soc_kwh", 0.0))
        ambient_c = float(forecast_row.get("temperature", 25.0))

        # Simple instantaneous load proxy; not a physical cell thermal model.
        temperature_rise_c = TEMP_RISE_COEFFICIENT_C_PER_KW2 * (
            charge_kw ** 2 + discharge_kw ** 2
        )
        estimated_battery_temp_c = ambient_c + temperature_rise_c

        throughput_kwh = (charge_kw + discharge_kw) * INTERVAL_HOURS
        total_throughput_kwh += throughput_kwh

        timestamp = dispatch_row.get("timestamp", forecast_row.get("timestamp"))
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()

        hourly_estimates.append({
            "timestamp": timestamp,
            "hour": int(dispatch_row.get("hour", index)),
            "battery_soc_kwh": round(soc_kwh, 2),
            "battery_soc_pct": round(
                max(0.0, min(100.0, soc_kwh / BATTERY_CAPACITY_KWH * 100)),
                2,
            ),
            "battery_charge_kw": round(charge_kw, 2),
            "battery_discharge_kw": round(discharge_kw, 2),
            "ambient_temperature_assumption_c": round(ambient_c, 2),
            "estimated_battery_temperature_c": round(estimated_battery_temp_c, 2),
        })

    equivalent_full_cycles = total_throughput_kwh / (
        2.0 * BATTERY_CAPACITY_KWH
    )
    estimated_degradation_pct = (
        equivalent_full_cycles
        * DEGRADATION_PERCENT_PER_EQUIVALENT_FULL_CYCLE
    )
    estimated_health_pct = max(
        0.0,
        INITIAL_HEALTH_PERCENT_ASSUMPTION - estimated_degradation_pct,
    )

    snapshot = hourly_estimates[0]
    temperatures = [
        item["estimated_battery_temperature_c"]
        for item in hourly_estimates
    ]

    return {
        "source": "illustrative_model_estimate_not_hardware_telemetry",
        "horizon_hours": len(hourly_estimates),
        "battery": {
            "capacity_kwh": BATTERY_CAPACITY_KWH,
            "minimum_soc_kwh": 100.0,
            "maximum_charge_kw": MAX_CHARGE_KW,
            "maximum_discharge_kw": MAX_DISCHARGE_KW,
            "initial_health_pct_assumption": INITIAL_HEALTH_PERCENT_ASSUMPTION,
            "representative_snapshot": snapshot,
            "estimated_temperature_min_c": round(min(temperatures), 2),
            "estimated_temperature_max_c": round(max(temperatures), 2),
            "energy_throughput_kwh_over_horizon": round(total_throughput_kwh, 2),
            "equivalent_full_cycles_over_horizon": round(equivalent_full_cycles, 5),
            "estimated_degradation_pct_over_horizon": round(
                estimated_degradation_pct, 5
            ),
            "estimated_health_pct_after_horizon": round(
                estimated_health_pct, 5
            ),
        },
        "hourly_estimates": hourly_estimates,
        "assumptions": {
            "temperature_model": (
                "Ambient temperature plus 0.00008 * "
                "(charge_kw^2 + discharge_kw^2); illustrative proxy only."
            ),
            "degradation_model": (
                "0.03 percentage points per equivalent full cycle, "
                "starting from an assumed 100% health for this horizon."
            ),
            "limitations": [
                "No physical temperature sensor is connected.",
                "No chemistry-specific thermal, calendar-aging, or electrochemical model is included.",
                "Health and degradation are horizon estimates, not cumulative lifetime measurements.",
            ],
        },
    }
