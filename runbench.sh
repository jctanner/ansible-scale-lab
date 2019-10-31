#!/bin/bash

PLAYBOOK=run_scale_strategy.yml

for FORKCOUNT in $(seq 5 100 5); do
    for HOSTCOUNT in $(seq 100 200 100); do
        echo "hosts:$HOSTCOUNT forks:$FORKCOUNT"
        export HOSTCOUNT=$HOSTCOUNT
        export BENCHMARK_RESULTS="results.h${HOSTCOUNT}.f${FORKCOUNT}"
        if [[ -d $BENCHMARK_RESULTS ]];  then
            rm -rf $BENCHMARK_RESULTS
        fi
        mkdir $BENCHMARK_RESULTS
        PERF_FILE="$BENCHMARK_RESULTS/perf.csv"
        PERF_CMD="perf stat -x, -I 100"
        PERF_CMD="$PERF_CMD -e branches -e instructions -e task-clock -e context-switches -e page-faults -e cpu-migrations"
        PERF_CMD="$PERF_CMD -o $PERF_FILE"
        echo "$PERF_CMD"
        $PERF_CMD $(which ansible-playbook) -i 'localhost,' --forks=$FORKCOUNT $PLAYBOOK
    done
done
