from datetime import datetime
from typing import Any

import pandas as pd

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from forecaster import (
    generate_historical_data,
    train_models,
    generate_future_conditions,
    forecast_next_24_hours,
)

from optimizer import optimize_dispatch

from resilience import optimize_resilience


# ============================================================
# VOLTFORGE API
# ============================================================

app = FastAPI(
    title="VoltForge API",
    description=(
        "AI-driven microgrid optimization "
        "and resilience API"
    ),
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# GLOBAL SYSTEM STATE
# ============================================================

SYSTEM_STATE: dict[str, Any] = {

    "mode": "OPTIMIZED",

    "grid_available": True,

    "cloud_cover": False,

    "load_spike": False,

    "last_updated": None,
}


# ============================================================
# TRAIN MODELS ON STARTUP
# ============================================================

print("=" * 70)
print("STARTING VOLTFORGE BACKEND")
print("=" * 70)

historical_data = generate_historical_data(
    days=90
)

solar_model, load_model, forecast_metrics = train_models(
    historical_data
)

print(
    f"Solar forecast MAE: "
    f"{forecast_metrics['solar_mae']} kW"
)

print(
    f"Load forecast MAE: "
    f"{forecast_metrics['load_mae']} kW"
)

print("=" * 70)


# ============================================================
# FORECAST GENERATOR
# ============================================================

def generate_current_forecast(
    cloud_override: bool = False,
    load_spike: bool = False,
) -> pd.DataFrame:

    last_timestamp = (
        historical_data["timestamp"].iloc[-1]
    )

    future_conditions = generate_future_conditions(
        last_timestamp + pd.Timedelta(hours=1)
    )

    # --------------------------------------------------------
    # CLOUD COVER OVERRIDE
    # --------------------------------------------------------

    if cloud_override:

        future_conditions["cloud_cover"] = (
            future_conditions["cloud_cover"] + 0.80
        ).clip(0, 1)

    # --------------------------------------------------------
    # AI FORECAST
    # --------------------------------------------------------

    forecast = forecast_next_24_hours(
        solar_model,
        load_model,
        future_conditions,
    )

    # --------------------------------------------------------
    # LOAD SPIKE OVERRIDE
    # --------------------------------------------------------

    if load_spike:

        forecast["predicted_load_kw"] *= 1.35

    return forecast


# ============================================================
# DATAFRAME → JSON
# ============================================================

def dataframe_to_records(
    dataframe: pd.DataFrame,
) -> list[dict]:

    result = dataframe.copy()

    # Convert datetime
    for column in result.columns:

        if pd.api.types.is_datetime64_any_dtype(
            result[column]
        ):

            result[column] = result[column].apply(
                lambda value: (
                    value.isoformat()
                    if pd.notna(value)
                    else None
                )
            )

    # Replace missing values
    result = result.where(
        pd.notna(result),
        None,
    )

    records = result.to_dict(
        orient="records"
    )

    # Convert NumPy values to Python values
    for record in records:

        for key, value in record.items():

            if hasattr(value, "item"):

                record[key] = value.item()

    return records


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():

    return {
        "name": "VoltForge",

        "description": (
            "AI-driven microgrid optimization "
            "and resilience system"
        ),

        "status": "running",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    SYSTEM_STATE["last_updated"] = (
        datetime.now().isoformat()
    )

    return {

        "status": "online",

        "service": "VoltForge",

        "mode": SYSTEM_STATE["mode"],

        "grid_available": (
            SYSTEM_STATE["grid_available"]
        ),

        "forecast_model": "XGBoost",

        "optimizer": "SciPy MILP",

        "timestamp": SYSTEM_STATE["last_updated"],
    }


# ============================================================
# STATE
# ============================================================

@app.get("/state")
def get_state():

    return {

        **SYSTEM_STATE,

        "forecast_metrics": forecast_metrics,
    }


# ============================================================
# FORECAST
# ============================================================

@app.get("/forecast")
def get_forecast():

    forecast = generate_current_forecast(

        cloud_override=(
            SYSTEM_STATE["cloud_cover"]
        ),

        load_spike=(
            SYSTEM_STATE["load_spike"]
        ),
    )

    return {

        "model": "XGBoost",

        "horizon_hours": 24,

        "metrics": forecast_metrics,

        "forecast": dataframe_to_records(
            forecast
        ),
    }


# ============================================================
# DISPATCH
# ============================================================

@app.get("/dispatch")
def get_dispatch():

    forecast = generate_current_forecast(

        cloud_override=(
            SYSTEM_STATE["cloud_cover"]
        ),

        load_spike=(
            SYSTEM_STATE["load_spike"]
        ),
    )

    # --------------------------------------------------------
    # NORMAL GRID-CONNECTED MODE
    # --------------------------------------------------------

    if SYSTEM_STATE["grid_available"]:

        dispatch = optimize_dispatch(

            forecast,

            initial_soc_kwh=400,
        )

        mode = "OPTIMIZED"

    # --------------------------------------------------------
    # GRID BLACKOUT / ISLAND MODE
    # --------------------------------------------------------

    else:

        dispatch, _ = optimize_resilience(

            forecast,

            initial_soc_kwh=400,

            blackout_start_hour=18,

            blackout_end_hour=21,
        )

        mode = "ISLAND"

    return {

        "mode": mode,

        "grid_available": (
            SYSTEM_STATE["grid_available"]
        ),

        "dispatch": dataframe_to_records(
            dispatch
        ),
    }


# ============================================================
# METRICS
# ============================================================

@app.get("/metrics")
def get_metrics():

    forecast = generate_current_forecast(

        cloud_override=(
            SYSTEM_STATE["cloud_cover"]
        ),

        load_spike=(
            SYSTEM_STATE["load_spike"]
        ),
    )

    # ========================================================
    # NORMAL MODE
    # ========================================================

    if SYSTEM_STATE["grid_available"]:

        dispatch = optimize_dispatch(

            forecast,

            initial_soc_kwh=400,
        )

        current = dispatch.iloc[0]

        total_cost = float(
            dispatch["grid_cost_rs"].sum()
        )

        total_grid = float(
            dispatch["grid_import_kw"].sum()
        )

        return {

            "system_mode": "OPTIMIZED",

            "grid_available": True,

            "current": {

                "solar_kw": float(
                    current["solar_forecast_kw"]
                ),

                "load_kw": float(
                    current["load_forecast_kw"]
                ),

                "grid_import_kw": float(
                    current["grid_import_kw"]
                ),

                "battery_soc_kwh": float(
                    current["battery_soc_kwh"]
                ),

                "tariff_rs_per_kwh": float(
                    current["tariff_rs_per_kwh"]
                ),
            },

            "financial": {

                "optimized_grid_cost_rs": (
                    total_cost
                ),

                "grid_energy_kwh": (
                    total_grid
                ),
            },

            "forecast_accuracy": (
                forecast_metrics
            ),
        }

    # ========================================================
    # ISLAND MODE
    # ========================================================

    resilience_results, resilience_score = (
        optimize_resilience(

            forecast,

            initial_soc_kwh=400,

            blackout_start_hour=18,

            blackout_end_hour=21,
        )
    )

    outage_results = resilience_results[
        resilience_results["blackout"] == True
    ]

    # --------------------------------------------------------
    # Pick outage snapshot
    # --------------------------------------------------------

    if not outage_results.empty:

        current = outage_results.iloc[0]

    else:

        current = resilience_results.iloc[0]

    critical_load = float(
        current["critical_load_kw"]
    )

    critical_served = float(
        current["critical_served_kw"]
    )

    critical_coverage = (

        (critical_served / critical_load)
        * 100

        if critical_load > 0

        else 100
    )

    return {

        "system_mode": "ISLAND",

        "grid_available": False,

        "current": {

            "solar_kw": float(
                current["solar_kw"]
            ),

            "load_kw": float(
                current["total_load_kw"]
            ),

            "grid_import_kw": 0.0,

            "battery_soc_kwh": float(
                current["battery_soc_kwh"]
            ),

            "tariff_rs_per_kwh": float(
                current["tariff_rs_per_kwh"]
            ),
        },

        "resilience": {

            "score": float(
                resilience_score
            ),

            "critical_load_coverage": round(
                critical_coverage,
                2,
            ),
        },

        "financial": {

            "optimized_grid_cost_rs": 0.0,

            "grid_energy_kwh": 0.0,
        },

        "forecast_accuracy": (
            forecast_metrics
        ),
    }


# ============================================================
# CHAOS CONTROL — CLOUD COVER
# ============================================================

@app.post("/simulate/cloud")
def simulate_cloud():

    SYSTEM_STATE["cloud_cover"] = True

    SYSTEM_STATE["last_updated"] = (
        datetime.now().isoformat()
    )

    return {

        "success": True,

        "event": "SUDDEN_CLOUD_COVER",

        "message": (
            "Solar generation reduced. "
            "Forecast and dispatch will be recalculated."
        ),

        "cloud_override": True,

        "timestamp": SYSTEM_STATE[
            "last_updated"
        ],
    }


# ============================================================
# CHAOS CONTROL — LOAD SPIKE
# ============================================================

@app.post("/simulate/load-spike")
def simulate_load_spike():

    SYSTEM_STATE["load_spike"] = True

    SYSTEM_STATE["last_updated"] = (
        datetime.now().isoformat()
    )

    return {

        "success": True,

        "event": "LOAD_SPIKE",

        "message": (
            "Localized demand increased. "
            "VoltForge will recalculate dispatch."
        ),

        "load_spike": True,

        "timestamp": SYSTEM_STATE[
            "last_updated"
        ],
    }


# ============================================================
# CHAOS CONTROL — GRID BLACKOUT
# ============================================================

@app.post("/simulate/blackout")
def simulate_blackout():

    SYSTEM_STATE["grid_available"] = False

    SYSTEM_STATE["mode"] = "ISLAND"

    SYSTEM_STATE["last_updated"] = (
        datetime.now().isoformat()
    )

    return {

        "success": True,

        "event": "GRID_BLACKOUT",

        "message": (
            "Grid failure detected. "
            "VoltForge entered Island Mode."
        ),

        "mode": "ISLAND",

        "grid_available": False,

        "timestamp": SYSTEM_STATE[
            "last_updated"
        ],
    }


# ============================================================
# RESTORE GRID
# ============================================================

@app.post("/simulate/restore")
def restore_grid():

    SYSTEM_STATE["grid_available"] = True

    SYSTEM_STATE["mode"] = "OPTIMIZED"

    SYSTEM_STATE["cloud_cover"] = False

    SYSTEM_STATE["load_spike"] = False

    SYSTEM_STATE["last_updated"] = (
        datetime.now().isoformat()
    )

    return {

        "success": True,

        "event": "GRID_RESTORED",

        "message": (
            "Grid connection restored. "
            "VoltForge returned to optimized mode."
        ),

        "mode": "OPTIMIZED",

        "grid_available": True,

        "timestamp": SYSTEM_STATE[
            "last_updated"
        ],
    }


# ============================================================
# RESILIENCE
# ============================================================

@app.get("/resilience")
def get_resilience():

    forecast = generate_current_forecast(

        cloud_override=(
            SYSTEM_STATE["cloud_cover"]
        ),

        load_spike=(
            SYSTEM_STATE["load_spike"]
        ),
    )

    results, resilience_score = (
        optimize_resilience(

            forecast,

            initial_soc_kwh=400,

            blackout_start_hour=18,

            blackout_end_hour=21,
        )
    )

    return {

        "resilience_score": resilience_score,

        "mode": SYSTEM_STATE["mode"],

        "grid_available": (
            SYSTEM_STATE["grid_available"]
        ),

        "schedule": dataframe_to_records(
            results
        ),
    }