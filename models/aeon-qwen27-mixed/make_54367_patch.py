#!/usr/bin/env python3
"""Build the #54367 modelopt.py patch by copying the image's own file and
inserting the missing FP8_PER_CHANNEL_PER_TOKEN dispatch branch.
Usage: extract_container_modelopt.py <image> <out_path>
Requires docker on the host. Run against the image on the serving node.
"""
import ast
import subprocess
import sys

def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    image, out = sys.argv[1], sys.argv[2]

    cid = subprocess.check_output(
        ["docker", "create", image, "/bin/true"], text=True
    ).strip()
    tmp = "/tmp/container_modelopt.py"
    try:
        subprocess.run(["docker", "cp", f"{cid}:/usr/local/lib/python3.12/site-packages/"
                        "vllm/model_executor/layers/quantization/modelopt.py", tmp],
                       check=True)
    finally:
        subprocess.run(["docker", "rm", cid], check=True)

    with open(tmp) as f:
        content = f.read()

    needle = '''            if quant_algo == "MXFP8":
                return ModelOptMxFp8LinearMethod(self.mxfp8_config)
            # Layer not in quantized_layers — leave unquantized
            return UnquantizedLinearMethod()'''
    replacement = '''            if quant_algo == "MXFP8":
                return ModelOptMxFp8LinearMethod(self.mxfp8_config)
            if quant_algo == "FP8_PER_CHANNEL_PER_TOKEN":
                return ModelOptFp8PcPtLinearMethod(self.fp8_config)
            # Layer not in quantized_layers — leave unquantized
            return UnquantizedLinearMethod()'''

    assert needle in content, "dispatch needle not found — image already patched or changed"
    content = content.replace(needle, replacement, 1)
    ast.parse(content)  # syntax gate
    with open(out, "w") as f:
        f.write(content)
    print(f"patched -> {out} ({content.count(chr(10))} lines)")

if __name__ == "__main__":
    main()
