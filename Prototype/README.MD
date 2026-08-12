# KPI Tree Viewer

Interactive tool for visualizing KPI goal trees and cascading stretch targets down organizational hierarchies.

## What It Does

1. **Extracts KPI data** from Teradata into a local parquet cache
2. **Builds a KPI tree** from the cached data using a configurable hierarchy definition (`hierarchy.json`)
3. **Cascades goals** from leadership targets down to every node proportionally based on contribution (den ratio)
4. **Visualizes the tree** in a Streamlit app with interactive graph view, node editing, and statistics

## Project Structure

```
Prototype/
├── app.py                  # Streamlit viewer/editor (main UI)
├── kpi_statistics.py       # Teradata query → teradata_cache.parquet
├── converter2.0.py         # Builds the base tree JSON from parquet + hierarchy
├── cascade.py              # Applies goals from goals.csv and cascades stretch down
├── hierarchy.json          # Hierarchy definition (nesting order + transforms)
├── goals.csv               # Leadership goal targets (truth source for anchors)
├── teradata_cache.parquet  # Cached raw data (flat rows with dimensions + num/den)
├── output/                 # Generated tree JSONs + per-KPI CSVs (consumed by app.py)
├── cascaded_output/        # Cascaded goal CSVs (summary tables with YTD actuals)
├── assets/                 # Logo and static files
└── requirements.txt        # Python dependencies
```

## Prerequisites

- Python 3.12 or later
- Network access to Teradata (`dwprod`) for data refresh (optional if parquet cache exists)

## Setup

```bash
cd Prototype

# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Step 1: Refresh data cache (optional)

Queries Teradata and writes `teradata_cache.parquet`. Requires `TD_USER` and `TD_PASS` environment variables (or prompts interactively):

```bash
python kpi_statistics.py
```

Skip this step if the parquet cache is already up to date.

### Step 2: Build the base tree

Reads `teradata_cache.parquet` and `hierarchy.json`, outputs `output/D0 2.0.json`:

```bash
python converter2.0.py
```

### Step 3: Cascade goals

Reads `goals.csv`, applies stretch to anchor nodes, cascades proportionally to all descendants, and writes:
- `output/D0 2.0.json` (updated tree with goal values)
- `cascaded_output/D0_cascaded.csv` (flat summary with YTD actuals)

```bash
python cascade.py
```

### Step 4: Launch the viewer

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. Use the sidebar to:
- Select a KPI from the output directory
- Adjust max stations displayed in the graph
- Control tree display depth

## Key Files

| File | Role |
|------|------|
| `hierarchy.json` | Declares nesting order of dimensions (`system → carrier → dc_carrier → month → first_flt → dom_int → fleet → vendor → station`) and optional value transforms (e.g., int_flag mapping `1` → "First Flight"). Edit this to restructure the tree without touching Python. |
| `goals.csv` | Truth source for anchor nodes. Format: `KPI_Name, Node_Name, Baseline, Baseline_Num, Baseline_Den, Stretch, KPI_Num, KPI_Den, Goal`. The cascade engine reads from here. |
| `kpi_statistics.py` | Connects to Teradata (`dwprod`, LDAP auth) and pulls flight-level KPI data into `teradata_cache.parquet`. |
| `converter2.0.py` | Reads parquet + hierarchy, aggregates num/den at each level via groupby, computes baselines and contributions, writes the initial tree JSON. |
| `cascade.py` | Overlays goals from `goals.csv` onto matching nodes, cascades stretch % to all descendants (proportional to contribution), computes YTD actuals from the parquet, and exports both JSON and CSV. |
| `app.py` | Streamlit app. Three tabs: **Tree** (navigation + node edit/add/delete), **Graph** (Plotly network visualization + hierarchy view), **Statistics** (cascaded CSV data table). |

## Data Flow

```
                         kpi_statistics.py
                               │
                               ▼
                      teradata_cache.parquet
                               │
            ┌──────────────────┼──────────────────┐
            │                  │                  │
            ▼                  ▼                  ▼
     hierarchy.json     converter2.0.py      cascade.py
                               │                  │
                               ▼                  │
                        output/D0 2.0.json ◄──────┘
                               │            goals.csv
                               ▼
                       app.py (Streamlit)
                               │
                        cascaded_output/
                        D0_cascaded.csv
```

## App Features

- **Tree Tab** — Expandable tree with lazy rendering (depth-limited). Select any node to view properties (baseline, goal, contribution, num, den). Edit, add children, or delete nodes. Save changes back to JSON.
- **Graph Tab** — Two views:
  - *Graph*: Plotly network diagram rooted at the selected node. Color-coded by type (Goal vs Target). Hover for full node details.
  - *Hierarchy*: Renders the `hierarchy.json` definition as a visual diagram.
- **Statistics Tab** — Displays the per-KPI CSV from the output directory.
- **QA Validation** — Checks that child contributions sum to 100% at every level and flags imbalances.

## Cascading Logic

1. Anchor nodes are identified by `Node_Name` in `goals.csv` (format: `category;name`, e.g. `carrier;ML`)
2. Carrier aliases are resolved (`ML` → `DL` in data)
3. Each anchor receives explicit baseline/goal values from the CSV
4. Stretch is cascaded to all descendants: `child_goal_rate = child_baseline_rate × (1 + stretch)`
5. Denominator grows by the anchor's den growth factor: `child_goal_den = child_baseline_den × (goal_den / baseline_den)`
6. Children with their own explicit goals are skipped during cascading

## Notes

- `goals.csv` is the truth source for anchor nodes. Baseline, goal, num, and den from that file override computed values.
- The graph view roots from the currently selected node, not the full tree root.
- KPI JSON files in `output/` can be edited directly in the app and saved back.
- The parquet cache covers flight data from 2025-06-01 to 2026-05-30. YTD actuals in the cascaded CSV use the latest year in the data.
