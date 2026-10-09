"""Sustainability indicators for VoltForge's simulated microgrid.

Emissions are estimates based on a configurable grid emissions factor, not
metered emissions or a certified carbon accounting result.
"""
from __future__ import annotations

import os
import pandas as pd

DEFAULT_GRID_EMISSIONS_KG_CO2_PER_KWH = float(
    os.getenv("GRID_EMISSIONS_KG_CO2_PER_KWH", "0.708")
)


def calculate_sustainability(
    forecast: pd.DataFrame,
    dispatch: pd.DataFrame,
    grid_emissions_kg_co2_per_kwh: float | None = None,
) -> dict:
    if forecast.empty or dispatch.empty:
        raise ValueError("Forecast and dispatch must not be empty.")

    factor = (
        DEFAULT_GRID_EMISSIONS_KG_CO2_PER_KWH
        if grid_emissions_kg_co2_per_kwh is None
        else float(grid_emissions_kg_co2_per_kwh)
    )
    if factor < 0:
        raise ValueError("Grid emissions factor must be non-negative.")

    f = forecast.reset_index(drop=True)
    d = dispatch.reset_index(drop=True)
    if len(f) != len(d):
        raise ValueError("Forecast and dispatch must have the same number of rows.")

    solar_forecast_kwh = float(f["predicted_solar_kw"].clip(lower=0).sum())
    solar_to_load_kwh = float(d.get("solar_to_load_kw", pd.Series([0] * len(d))).clip(lower=0).sum())
    solar_to_battery_kwh = float(d.get("solar_to_battery_kw", pd.Series([0] * len(d))).clip(lower=0).sum())
    curtailed_kwh = float(d.get("solar_curtailed_kw", pd.Series([0] * len(d))).clip(lower=0).sum())
    renewable_used_kwh = solar_to_load_kwh + solar_to_battery_kwh
    renewable_utilization_pct = (
        min(100.0, renewable_used_kwh / solar_forecast_kwh * 100.0)
        if solar_forecast_kwh > 0 else 0.0
    )
    grid_import_kwh = float(d.get("grid_import_kw", pd.Series([0] * len(d))).clip(lower=0).sum())

    # Estimated avoided emissions = renewable energy used * assumed grid factor.
    # Battery charging is counted at charging input, so this is an indicative
    # avoided-grid estimate and does not model lifecycle emissions or losses.
    co2_avoided_kg = renewable_used_kwh * factor

    return {
        "source": "simulated_dispatch_estimate",
        "horizon_hours": int(min(len(f), len(d))),
        "grid_emissions_factor_kg_co2_per_kwh": round(factor, 4),
        "renewable_generation_forecast_kwh": round(solar_forecast_kwh, 2),
        "renewable_energy_utilized_kwh": round(renewable_used_kwh, 2),
        "renewable_utilization_pct": round(renewable_utilization_pct, 2),
        "solar_curtailed_kwh": round(curtailed_kwh, 2),
        "grid_import_kwh": round(grid_import_kwh, 2),
        "estimated_co2_avoided_kg": round(co2_avoided_kg, 2),
        "methodology": (
            "Indicative estimate: solar energy routed to load or battery multiplied "
            "by the configurable grid emissions factor. Not metered or lifecycle carbon accounting."
        ),
    }
