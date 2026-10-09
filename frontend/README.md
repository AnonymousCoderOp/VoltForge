# VoltForge Dashboard

A responsive React + TypeScript control-room dashboard for the VoltForge FastAPI backend. This frontend is isolated under `frontend/` and was developed on `feat/parallel-dashboard` so it can be worked on in parallel with another frontend implementation.

## Features

- Light and dark themes with a remembered preference
- Responsive energy operations dashboard with animated cards and charts
- 24-hour solar/load forecast and dispatch visualization
- Battery SOC, charge/discharge and illustrative battery telemetry estimates
- Renewable utilization and estimated CO₂ avoided indicators
- Rolling 30-day simulated financial history
- Resilience schedule and critical-load coverage
- Blackout, cloud-cover, load-spike, and restore simulation controls
- WebSocket connection status and periodic system snapshots
- API errors are surfaced in the UI; charts label estimated/synthetic data appropriately

## Run locally

From the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL printed in your terminal (usually `http://localhost:5173`). Ensure the FastAPI backend is running at `http://127.0.0.1:8000`.

To point at another backend, copy `.env.example` to `.env.local` and set `VITE_API_BASE_URL`.

## Build verification

```bash
npm run build
```

All battery temperature, battery-health, sustainability and financial savings values returned by the current backend are illustrative estimates based on synthetic data, not physical telemetry or metered bills.
