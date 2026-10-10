#!/bin/bash
# run.sh <label> <python> <pythonpath> [extra env...]: 1-s MemAvailable/swap logger + nice bench
# Takes no lock itself; caller holds ~/pi-timing.lock.
L=$1; PY=$2; PP=$3; shift 3
cd "$HOME/exp64/kit" || exit 1
st=$(curl -s localhost/api/recording/status | grep -o '"enabled":[a-z]*')
[ "$st" = '"enabled":false' ] || { echo "recording enabled? $st - abort"; exit 1; }
rm -f mem_$L.log
( while sleep 1; do free -m | awk '/Mem/{m=$7}/Swap/{s=$3}END{print "avail",m,"swapused",s}'; done ) > mem_$L.log &
W=$!
s0=$(free -m | awk '/Swap/{print $3}')
t0=$(date +%s.%N); env "$@" PYTHONPATH="$PP" nice -n 10 "$PY" bench.py drive out_$L.json 2>&1 | grep -v "Unsupported persisted\|^Traceback\|^  File\|^    \|^ *\^\|~~~" | tail -4
echo "wall $(awk "BEGIN{print $(date +%s.%N) - $t0}") s"
kill $W
echo "$L min avail: $(sort -k2 -n mem_$L.log | head -1)  max swap: $(sort -k4 -n mem_$L.log | tail -1) (swap at start $s0)"
sha256sum out_$L.json | cut -c1-16
