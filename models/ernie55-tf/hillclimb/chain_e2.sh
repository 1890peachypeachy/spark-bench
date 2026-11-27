#!/usr/bin/env bash
HC=/var/tmp/ernie55/hillclimb/tf
for e in e2a-g64-max2 e2b-g64-max2-table e2c-g64-after4; do
  SKIP_LONG=1 bash $HC/run_exp.sh $e > $HC/logs/$e.tmux.log 2>&1
done
bash $HC/prof_run.sh eprof-base > $HC/logs/eprof-base.tmux.log 2>&1
echo "== $(date -Is) chain done; restoring production" >> $HC/logs/chain_e2.log
bash /var/tmp/ernie55/start_tensorfold.sh >> $HC/logs/chain_e2.log 2>&1
/usr/local/bin/nsys shutdown --session=tfprof >/dev/null 2>&1 || true
echo "== $(date -Is) production restored" >> $HC/logs/chain_e2.log
