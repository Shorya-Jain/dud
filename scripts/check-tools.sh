#!/bin/sh
# Read-only. Shows which tools milestone 2 can use on this node.
# It removes GPU UUIDs from the output.
strip_ids() { sed -E 's/GPU-[0-9a-fA-F-]{8,}/GPU-<removed>/g'; }

echo "== python";        python3 --version 2>&1
echo "== pip";           python3 -m pip --version 2>&1
echo "== torch";         python3 -c "import torch; print(torch.__version__, 'cuda', torch.version.cuda, 'available', torch.cuda.is_available(), 'gpus', torch.cuda.device_count())" 2>&1 | tail -1
echo "== dcgmi";         (command -v dcgmi && dcgmi --version) 2>&1 | head -5
echo "== nv-hostengine"; command -v nv-hostengine 2>&1
echo "== package tools"; for t in apt-get dnf yum conda; do command -v "$t"; done
echo "== os";            grep PRETTY_NAME /etc/os-release 2>&1
echo "== driver";        cat /proc/driver/nvidia/version 2>&1 | head -2
echo "== nvcc";          (command -v nvcc && nvcc --version | tail -2) 2>&1
echo "== nvlink";        nvidia-smi nvlink -s 2>&1 | head -30 | strip_ids
echo "== smi version";   nvidia-smi --version 2>&1 | strip_ids
echo "== disk";          df -h . 2>&1 | tail -1
echo "== memory";        free -g 2>&1 | head -2
echo "== whoami";        id -u 2>&1
