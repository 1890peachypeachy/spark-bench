# dsv41-tf4: TensorFold TP4 on LibertAI EXL3 3.5bpw (replaces dsv41-tp4 / dsv41-tp3 on :8888)

Source of truth: ~/recipe-db/DeepSeek-V4.1-Flash-TP2-and-TP4-DGX-Sparks (tonyd2wild), recipe v0.3.5 (b88fae2).
Engine: TensorFold 0a0b69a (v0.3.5's) + two of Tony's patches rebased on top (TF_RDMA_GID, TF_SEED_RANDOM/TF_TOP_K_MAX).
Patches 0001/0002 are already upstream in 0a0b69a. 0004 hit one conflict (upstream greedy_only guard): both sides kept.
Weights: LibertAIDAI/DeepSeek-V4.1-Flash-1017-EXL3-3.5bpw @ 04a492fc (239.95 GiB, 47/47 sha256).
NOTE: the v0.3.5 recipe is benchmarked on bertholomus 4.0bpw. 3.5bpw on this engine is not a documented combination;
it booted and passed chat/math/tool-call here (2026-10-24).

Same endpoint and name as before so Hermes needs no change: http://100.99.120.29:8888/v1, GLM-5.3-Flash-EXL3. Context capped 262144 (Victor).
Rank order: 0=spark3 (10.73.0.3) 1=spark4 2=spark1 3=spark2. Both rails: rocep1s0f1+roceP2p1s0f1, RoCE v2 GID index 3.

Measured 2026-10-24 (temperature 0, 400 tokens): 1 stream 74.0 tok/s; 4 streams 180.8 tok/s aggregate (45.6 each).
Prior dsv41-tp3 (SGLang) was not benchmarked, so no like-for-like comparison yet.

Files: x35_chunkdl.sh/x35_fanin.sh/x35_verify.py (split download), x35_worker_prep.sh/x35_head_prep.sh/x35_model_dir.sh
(per-node inputs), config.spark-fleet.env (lane config), manifest.json/split-*.json (pinned revision tree).
Lane control: ops/spark-lane up|down|verify dsv41-tf4.  Rollback to SGLang TP3: spark-lane down dsv41-tf4 && spark-lane up dsv41-tp3.
