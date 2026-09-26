#/bin/sh

scripts/run  --lang en --debugUtils --port 7777 --vsync 2 --altControls &
scripts/autoplay  --port 7777 --agent-p2
