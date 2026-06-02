"""battery_usage — pipeline to download and analyze ThinkPad battery telemetry.

Stages
------
1. s3_download  : discover users in S3 and download a filtered cohort locally.
2. parse        : load + clean one user's raw CSV/JSON into tidy structures.
3. features     : derive per-user usage/health metrics (SOH, cycles, AC ratio, DoD ...).
4. aggregate    : build a cross-user cohort table, summary stats and usage personas.
5. visualize    : cohort + per-user plots.
6. report       : assemble a markdown report.

Run `python -m battery_usage --help` for the CLI.
"""

__version__ = "0.1.0"
