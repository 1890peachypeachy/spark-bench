#!/bin/bash
# Read-only disk map for one Spark (run over ssh). No sudo, no writes.
H=$HOME
echo "### df"; df -h / | tail -1
echo "### docker system df"; docker system df 2>/dev/null
echo "### home top-level (>=1G)"; du -x -d1 -BG "$H" 2>/dev/null | awk '$1+0>=1' | sort -rn | head -12
echo "### /var/tmp top-level (>=1G)"; du -x -d1 -BG /var/tmp 2>/dev/null | awk '$1+0>=1' | sort -rn | head -12
echo "### /var/tmp/gr8 (>=1G)"; du -x -d2 -BG /var/tmp/gr8 2>/dev/null | awk '$1+0>=1' | sort -rn | head -8
echo "### /srv /opt /data /mnt (>=1G)"; for d in /srv /opt /data /mnt /models; do [ -d $d ] && du -x -d1 -BG $d 2>/dev/null | awk '$1+0>=1'; done | sort -rn | head -8
echo "### docker images (repo:tag size, containers using)"
docker images --format '{{.Repository}}:{{.Tag}}|{{.ID}}|{{.Size}}|{{.CreatedSince}}' 2>/dev/null
echo "### images in use by a container (running or stopped)"; docker ps -a --format '{{.Image}}|{{.Names}}|{{.Status}}' 2>/dev/null
echo "### docker volumes"; docker volume ls --format '{{.Name}}' 2>/dev/null | head -20
