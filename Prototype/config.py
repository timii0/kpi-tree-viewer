"""
config.py - Shared configuration for the KPI tree pipeline.

This is the single source of truth for settings that affect multiple modules.
Import from here rather than defining settings in individual files.
"""

# ---------------------------------------------------------------------------
# CASCADE_BASIS
# ---------------------------------------------------------------------------
# Controls how contributions AND stretch distribution are calculated.
# Changing this value affects:
#   1. Tree node contributions (converter.py → calc_contributions)
#   2. Cascade stretch distribution (cascade.py → cascade_goals)
#   3. App display contributions (app.py → calc_contributions)
#
# Options:
#   "num" (default): child.num / parent.num (performance share).
#       Preserves uniform percentage improvement across children.
#       Higher-performing children receive more absolute stretch.
#   "den": child.den / parent.den (volume share).
#       Distributes by opportunity volume regardless of performance.
#       Larger-volume children receive more absolute stretch.
CASCADE_BASIS = "num"
