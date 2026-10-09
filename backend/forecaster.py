import numpy as np
import pandas as pd
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error


# ============================================================
# VOLTFORGE AI FORECASTING ENGINE
# ============================================================

RANDOM_SEED = 42

SOLAR_FEATURES = [
    "hour",
    "day_of_week",
    "is_weekend",
    "cloud_cover",
    "temperature",
]

LOAD_FEATURES = [
    "hour",
    "day_of_week",
    "is_weekend",
    "cloud_cover",
    "temperature",
]


# ============================================================
# 1. GENERATE HISTORICAL MICROGRID DATA
# ============================================================

def generate_historical_data(days: int = 90) -> pd.DataFrame:
    rng = np.random.default_rng(RANDOM_SEED)

    timestamps = pd.date_range(
        start="2026-01-01",
        periods=days * 24,
        freq="h",
    )

    rows = []

    for timestamp in timestamps:

        hour = timestamp.hour
        day_of_week = timestamp.dayofweek
        is_weekend = int(day_of_week >= 5)

        # ----------------------------------------------------
        # Weather simulation
        # ----------------------------------------------------

        cloud_cover = rng.uniform(0.0, 1.0)

        temperature = (
            25
            + 7 * np.sin((hour - 8) * np.pi / 12)
            + rng.normal(0, 1.5)
        )

        # ----------------------------------------------------
        # Solar generation
        # ----------------------------------------------------

        if 6 <= hour <= 19:

            solar_base = 500 * np.exp(
                -((hour - 13) ** 2) / 12
            )

            cloud_factor = 1 - (0.80 * cloud_cover)

            solar = (
                solar_base
                * cloud_factor
                + rng.normal(0, 8)
            )

        else:
            solar = 0

        solar = max(0, solar)

        # ----------------------------------------------------
        # Campus load
        # ----------------------------------------------------

        morning_peak = 180 * np.exp(
            -((hour - 9) ** 2) / 8
        )

        evening_peak = 220 * np.exp(
            -((hour - 19) ** 2) / 10
        )

        base_load = 180

        temperature_effect = max(
            temperature - 26,
            0
        ) * 6

        weekend_reduction = (
            70 if is_weekend else 0
        )

        load = (
            base_load
            + morning_peak
            + evening_peak
            + temperature_effect
            - weekend_reduction
            + rng.normal(0, 8)
        )

        load = max(50, load)

        rows.append({
            "timestamp": timestamp,
            "hour": hour,
            "day_of_week": day_of_week,
            "is_weekend": is_weekend,
            "cloud_cover": round(cloud_cover, 3),
            "temperature": round(temperature, 2),
            "solar_kw": round(solar, 2),
            "load_kw": round(load, 2),
        })

    return pd.DataFrame(rows)


# ============================================================
# 2. TRAIN XGBOOST MODELS
# ============================================================

def train_models(
    data: pd.DataFrame,
):
    data = data.copy()

    # Last 24 hours reserved for validation
    train_data = data.iloc[:-24]
    test_data = data.iloc[-24:]

    solar_model = XGBRegressor(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="reg:squarederror",
        random_state=RANDOM_SEED,
    )

    load_model = XGBRegressor(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="reg:squarederror",
        random_state=RANDOM_SEED,
    )

    # Train
    solar_model.fit(
        train_data[SOLAR_FEATURES],
        train_data["solar_kw"],
    )

    load_model.fit(
        train_data[LOAD_FEATURES],
        train_data["load_kw"],
    )

    # --------------------------------------------------------
    # Validation
    # --------------------------------------------------------

    solar_predictions = solar_model.predict(
        test_data[SOLAR_FEATURES]
    )

    load_predictions = load_model.predict(
        test_data[LOAD_FEATURES]
    )

    solar_mae = mean_absolute_error(
        test_data["solar_kw"],
        solar_predictions,
    )

    load_mae = mean_absolute_error(
        test_data["load_kw"],
        load_predictions,
    )

    metrics = {
        "solar_mae": round(float(solar_mae), 2),
        "load_mae": round(float(load_mae), 2),
    }

    return solar_model, load_model, metrics


# ============================================================
# 3. CREATE NEXT 24-HOUR WEATHER FORECAST
# ============================================================

def generate_future_conditions(
    start_timestamp: pd.Timestamp,
) -> pd.DataFrame:

    rng = np.random.default_rng(123)

    future_timestamps = pd.date_range(
        start=start_timestamp,
        periods=24,
        freq="h",
    )

    rows = []

    for timestamp in future_timestamps:

        hour = timestamp.hour
        day_of_week = timestamp.dayofweek
        is_weekend = int(day_of_week >= 5)

        # Simulated weather prediction
        cloud_cover = rng.uniform(0.05, 0.75)

        temperature = (
            25
            + 7 * np.sin((hour - 8) * np.pi / 12)
            + rng.normal(0, 1.0)
        )

        rows.append({
            "timestamp": timestamp,
            "hour": hour,
            "day_of_week": day_of_week,
            "is_weekend": is_weekend,
            "cloud_cover": round(cloud_cover, 3),
            "temperature": round(temperature, 2),
        })

    return pd.DataFrame(rows)


# ============================================================
# 4. FORECAST NEXT 24 HOURS
# ============================================================

def forecast_next_24_hours(
    solar_model,
    load_model,
    future_conditions: pd.DataFrame,
) -> pd.DataFrame:

    forecast = future_conditions.copy()

    forecast["predicted_solar_kw"] = solar_model.predict(
        forecast[SOLAR_FEATURES]
    )

    forecast["predicted_load_kw"] = load_model.predict(
        forecast[LOAD_FEATURES]
    )

    # Physical limits
    forecast["predicted_solar_kw"] = (
        forecast["predicted_solar_kw"].clip(lower=0)
    )

    forecast["predicted_load_kw"] = (
        forecast["predicted_load_kw"].clip(lower=50)
    )

    # --------------------------------------------------------
    # Electricity tariff
    # --------------------------------------------------------

    def calculate_tariff(hour: int) -> int:

        if 0 <= hour < 6:
            return 4

        if 6 <= hour < 18:
            return 8

        if 18 <= hour < 22:
            return 15

        return 6

    forecast["tariff_rs_per_kwh"] = forecast["hour"].apply(
        calculate_tariff
    )

    return forecast


# ============================================================
# 5. MAIN
# ============================================================

if __name__ == "__main__":

    print("\nVOLTFORGE AI FORECASTING ENGINE")
    print("=" * 70)

    # Generate historical data
    historical_data = generate_historical_data(days=90)

    print(
        f"Historical records generated: "
        f"{len(historical_data)} hourly records"
    )

    # Train AI models
    print("\nTraining XGBoost models...")

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

    # Generate future weather conditions
    last_timestamp = historical_data["timestamp"].iloc[-1]

    future_conditions = generate_future_conditions(
        last_timestamp + pd.Timedelta(hours=1)
    )

    # Forecast
    forecast = forecast_next_24_hours(
        solar_model,
        load_model,
        future_conditions,
    )

    # Display results
    print("\nNEXT 24-HOUR AI FORECAST")
    print("=" * 100)

    display_columns = [
        "timestamp",
        "predicted_solar_kw",
        "predicted_load_kw",
        "tariff_rs_per_kwh",
    ]

    print(
        forecast[
            display_columns
        ].to_string(index=False)
    )

    print("\n" + "=" * 70)
    print("AI FORECAST COMPLETE")