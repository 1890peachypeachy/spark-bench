FROM nvcr.io/nvidia/pytorch:26.08-py3

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN apt-get update && apt-get install -y --no-install-recommends \
      git ffmpeg libsndfile1 && rm -rf /var/lib/apt/lists/*

ARG COMFY_REF=v0.38.1
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /opt/ComfyUI \
 && cd /opt/ComfyUI && git checkout ${COMFY_REF}

WORKDIR /opt/ComfyUI

# NGC base already ships a GB10-tuned torch stack. Never let pip replace it.
RUN sed -i -E "/^(torch|torchvision|torchaudio|torchsde|numpy)([=<>~!].*)?$/d" requirements.txt \
 && pip install --no-deps -r requirements.txt \
 && pip install torchsde einops safetensors aiohttp yarl pyyaml Pillow scipy tqdm psutil \
      transformers tokenizers sentencepiece soundfile av spandrel kornia alembic SQLAlchemy \
      comfyui-frontend-package comfyui-workflow-templates comfyui-embedded-docs

RUN mkdir -p custom_nodes \
 && cd custom_nodes \
 && git clone --depth 1 https://github.com/1038lab/Comfyui-Minimax-H3-Promptor.git \
 && git clone --depth 1 https://github.com/NidAll/comfyui-ming-image-prompt-builder.git \
 && git clone --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git || true

EXPOSE 8188
ENTRYPOINT ["python3", "main.py"]
