#!/bin/bash
# Pull the TensorFold build/runtime image on THIS node (detached tmux, log + marker).
mkdir -p ~/logs ~/x35-state
rm -f ~/x35-state/IMAGE_DONE
docker pull nvcr.io/nvidia/pytorch:26.07-py3 > ~/logs/x35-image-pull.log 2>&1
if docker image inspect nvcr.io/nvidia/pytorch:26.07-py3 >/dev/null 2>&1; then
  docker image inspect nvcr.io/nvidia/pytorch:26.07-py3 --format '{{.Id}} {{.Size}}' > ~/x35-state/IMAGE_DONE
  echo "image present"
else
  echo "IMAGE PULL FAILED" >> ~/logs/x35-image-pull.log
fi
