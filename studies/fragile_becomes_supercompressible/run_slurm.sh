#!/bin/bash
#SBATCH --job-name="supercompressible"
#SBATCH --time=00:30:00
#SBATCH --mem=2G
#SBATCH --cpus-per-task=1
#SBATCH --partition=batch
#SBATCH --account=default
#SBATCH --output=logs/%j.out
#SBATCH --error=logs/%j.err

# Submit the fragile_becomes_supercompressible pipeline to SLURM.
#
# Usage:
#   sbatch run_slurm.sh [hydra_overrides...]
#
# Launches a single low-resource orchestrator job that runs:
#   uv run main.py cluster=slurm ++mode=slurm ++rootdir=$ROOTDIR <overrides>
# f3dasm's orchestrator then submits each pipeline step (and the parallel
# lin_buckle / riks array jobs) itself. Extra Hydra overrides are forwarded,
# e.g.:
#   sbatch run_slurm.sh ++scripts_dir=/path/to/abaqus2py/scripts

ROOTDIR="${ROOTDIR:-/scratch/$USER/supercompressible}"

export HYDRA_FULL_ERROR=1

echo "======================================="
echo " Job:      $SLURM_JOB_ID"
echo " Root dir: $ROOTDIR"
echo " Overrides: $*"
echo "======================================="

uv run main.py cluster=slurm ++mode=slurm ++rootdir="$ROOTDIR" "$@"
