# KPI Tree Viewer

Interactive tool for visualizing KPI goal trees, cascading stretch targets down organizational hierarchies, and reallocating num between nodes within a tier.

## What It Does

1. **Extracts KPI data** from Teradata into a local parquet cache
2. **Builds a KPI tree** from the cached data using a configurable hierarchy definition (`hierarchy.json`)
3. **Cascades goals** from leadership targets down to every node proportionally based on num contribution
4. **Visualizes the tree** in a Streamlit app with interactive graph view, node editing, reallocation, and statistics
5. **Validates rollup** — ensures children's num sums to parent at every level and contributions are consistent

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

Opens at `http://localhost:8501`. Use the sidebar to select a KPI, adjust max stations, and control tree display depth.

## App Features

- **Tree Tab** — Expandable tree with lazy rendering (depth-limited). Select any node to view properties (baseline, goal, contribution, num, den). Actions:
  - *Edit*: Change name, category, type, or contribution
  - *Add Child*: Insert a new child node
  - *Reallocate*: Move num between siblings within the same tier (see below)
  - *Delete*: Remove a node and its subtree
  - *Save Tree*: Persists both the tree JSON and regenerates the statistics CSV

- **Graph Tab** — Two views:
  - *Graph*: Plotly network diagram rooted at the selected node. Color-coded by type (Goal vs Target). Hover for full node details.
  - *Hierarchy*: Renders the `hierarchy.json` definition as a visual diagram.

- **Statistics Tab** — Displays the per-KPI CSV from the output directory. Updated on Save Tree.

- **QA Validation** — Two checks run at every level:
  - *Contribution Sum*: Verifies primary and split children contributions each sum to 100%
  - *Num Rollup*: Verifies children's num sums to parent's num (with rounding tolerance for cascaded values)

## Num Reallocation

The Reallocate feature allows moving num between sibling nodes at the same tier within the primary branch. This models scenarios like a carrier deciding to shift volume targets between its sub-carriers to meet overall goals.

**How it works:**
1. Select a node in the tree, click "Reallocate"
2. The UI shows all siblings of the selected node (children of the same parent)
3. Pick a source (giving num) and destination (receiving num)
4. Enter the amount to transfer — a live preview shows the resulting baselines
5. Click "Apply Reallocation"

**What gets recalculated:**
- Source and destination `num` values (sum stays constant at parent level)
- Source and destination `baseline` (num/den)
- All sibling `contribution` values (child_num / parent_num)
- Parent num is unchanged — the rollup stays valid

**What does NOT change:**
- Denominator (`den`) — only num moves
- Parent's num, baseline, or goal
- Nodes outside the affected tier

## Cascading Logic

1. Anchor nodes are identified by `Node_Name` in `goals.csv` (format: `category;name`, e.g. `carrier;ML`)
2. Carrier aliases are resolved (`ML` → `DL` in data)
3. Each anchor receives explicit baseline/goal values from the CSV
4. The num delta (`goal_num - baseline_num`) is distributed to children proportionally by each child's num contribution (`child_num / parent_num`)
5. Den stays constant — only num grows, so the rate improvement cascades uniformly
6. Children with their own explicit goals are skipped during cascading
7. After cascading, `propagate_goal_nums` writes goal_num back into the `num` field at every level so the tree is internally consistent

## Key Files

| File | Role |
|------|------|
| `hierarchy.json` | Declares nesting order of dimensions and optional value transforms. Edit this to restructure the tree without touching Python. |
| `goals.csv` | Truth source for anchor nodes. Format: `KPI_Name, Node_Name, Baseline, Baseline_Num, Baseline_Den, Stretch, KPI_Num, KPI_Den, Goal`. |
| `kpi_statistics.py` | Connects to Teradata and pulls flight-level KPI data into `teradata_cache.parquet`. |
| `converter2.0.py` | Reads parquet + hierarchy, aggregates at each level, computes baselines and contributions. |
| `cascade.py` | Overlays goals onto matching nodes, cascades stretch proportionally, computes YTD actuals, exports JSON and CSV. |
| `app.py` | Streamlit app with tree navigation, node editing, num reallocation, graph visualization, statistics, and QA validation. |

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
                          │         │
                          ▼         ▼
                   output/*.csv   cascaded_output/
                  (on Save Tree)  D0_cascaded.csv
```

## Notes

- `goals.csv` baseline num/den must match the parquet data exactly. If the parquet is refreshed, re-derive the goal values to avoid rollup mismatches.
- The graph view roots from the currently selected node, not the full tree root.
- Tree JSON files in `output/` can be edited in the app and saved back. Saving also regenerates the statistics CSV.
- The parquet cache covers flight data from 2025-06-01 to 2026-05-30.
- YTD actuals in the cascaded CSV use the latest year present in the data.
