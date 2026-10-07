#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 -m unittest discover -s tests -v
python3 -m mtf_backtest demo
printf '\nOpen outputs/long_win/report.html in your browser.\n'
