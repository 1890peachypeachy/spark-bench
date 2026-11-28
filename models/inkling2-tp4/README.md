# Inkling-2-Small TP4 on our 4 Sparks (2026-11-23)
Recipe: ~/recipe-db/inkling2-sparks @ v0.3 (swbiggart/inkling2-sparks, tarball sha256 27fe1df9...069d). Engine: TensorFold-native, DSpark + vision on.
Lane contract: spark3 head (rank 0) -> http://100.99.120.29:8888/v1, model id `GLM-5.3-Flash-EXL3` (via EXTRA_ARGS `--name`), same as the glm53-tp4 lane.
Ranks: spark3, spark1, spark2, spark4. ROOT=/var/tmp/inkling2-tp4 (host processes, no container). HTTP 0.0.0.0, NO api key (same exposure as the GLM lane).
Our fabric differs from the recipe: cage 1 (enp1s0f1np1 10.73.0.x + enP2p1s0f1np1 10.74.0.x), 100G/half, not cage 0 @ 200G. No --fabric-install needed.
Weights: checkpoint was split-downloaded (spark1: shards 10,12,15,17,19,21,23,24; spark2: rest). spark1's half rsynced to spark2 over 10.73.0.x, then setup.sh `--checkpoint spark2:/home/spark2/models/Inkling-2-Small` hash-verified it vs pinned rev and built rank folders (~93-95G/node).
Run: cd ~/recipe-db/inkling2-sparks/recipe/inkling2-tp4 && bash setup.sh <this dir>/our-sparks.conf {start|stop|status|smoke}
Rollback: `setup.sh ... stop`, then `spark-lane up glm53-tp4`.
Result 2026-11-23: boot 48s, SMOKE PASS, oracle: 1 near-tie departure (tool_call, informational). Single samples: code 88 tok/s, prose 38 tok/s, 10.4k prompt TTFT 6.1s. Not the recipe's 200G numbers.

Context: CONTEXT=262144 (256k, the owner 2026-11-23) -> 4 streams (rank0 log: 4 whole contexts fit); MAX_STREAMS=4 default.
Registered in ops/spark-lane as lane `inkling2-tp4` (up|down|verify|rotate; host-process census via pgrep pseudo-container; exclusive). Backup: ops/spark-lane.bak-20261124T055455Z.
