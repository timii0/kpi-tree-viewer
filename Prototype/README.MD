# KPI Tree Viewer

Interactive tool for visualizing KPI goal trees and cascading stretch targets down organizational hierarchies.

## What It Does

1. **Builds a KPI tree** from raw operational data using a configurable hierarchy definition
2. **Cascades goals** from leadership targets down to every node in the tree (same stretch % applied proportionally)
3. **Visualizes the tree** in a Streamlit app with graph view, editing, and statistics

## Project Structure

```
Prototype/
├── app.py                  # Streamlit viewer/editor (run this to see the tree)
├── converter2.0.py         # Builds the base tree from parquet data + hierarchy
├── cascade.py              # Applies goals from goals.csv and cascades stretch down
├── hierarchy.json          # Hierarchy definition engine (nesting order, transforms)
├── goals.csv               # Input: leadership goal targets (truth source)
├── teradata_cache.parquet  # Cached raw data (flat rows with dimensions + num/den)
├── output/                 # Generated tree JSONs (consumed by app.py)
├── cascaded_output/        # Cascaded goal CSVs (summary tables)
├── assets/                 # Logo and static files
└── requirements.txt        # Python dependencies
```

## Prerequisites

- Python 3.12 or later

## Setup

```bash
# Clone the repo and navigate to Prototype/
cd Prototype

# Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# Install dependencies
pip install -r requirements.txt
```

## Usage

### Step 1: Build the base tree

Reads `teradata_cache.parquet` and `hierarchy.json`, outputs `output/D0 2.0.json`:

```bash
python converter2.0.py
```

### Step 2: Cascade goals

Reads `goals.csv` (leadership targets), applies the stretch to all descendant nodes, updates `output/D0 2.0.json` and writes `cascaded_output/D0_cascaded.csv`:

```bash
python cascade.py
```

### Step 3: Launch the viewer

```bash
streamlit run app.py
```

Opens at http://localhost:8501. Use the sidebar to select KPIs, adjust tree depth, and max stations displayed.

## Key Files Explained

| File | Role |
|------|------|
| `hierarchy.json` | Defines the nesting order of dimensions (system → carrier → dc_carrier → ...) and value transforms. Edit this to change the tree structure without touching Python. |
| `goals.csv` | Truth source for goal targets. Format: `KPI_Name, Node_Name, Baseline, Stretch, KPI_Num, KPI_Den, Goal`. The cascade engine reads from here. |
| `converter2.0.py` | Reads raw data + hierarchy, aggregates num/den at each level, computes baselines and contributions. Produces the initial tree JSON. |
| `cascade.py` | Takes the tree from converter, overlays goals from `goals.csv`, and cascades the stretch % to all descendants. Overwrites the tree JSON and exports a flat CSV. |
| `app.py` | Streamlit app. Tree navigation, node editing (add/edit/delete), graph visualization, and statistics tab showing the cascaded output. |

## Data Flow

```
goals.csv ──────────┐
                    ▼
hierarchy.json ──► cascade.py ──► output/D0 2.0.json ──► app.py
                    ▲                                     (viewer)
teradata_cache  ────┘          ──► cascaded_output/
  .parquet                         D0_cascaded.csv
```

## Notes

- `goals.csv` is the truth source for anchor nodes. Baseline, goal, num, and den from that file override computed values.
- The stretch % from `goals.csv` is applied uniformly to all descendants of the anchor node.
- The graph view roots from the currently selected node, not the full tree.
- KPI JSON files in `output/` can be edited directly in the app and saved back.
