#!/usr/bin/env bash
# Example Bash script executed under QR
# Run with: qr run -- bash examples/bash/hello.sh

echo "========================================"
echo "Running Framework-Agnostic Experiment"
echo "Host: $(hostname)"
echo "Date: $(date)"
echo "========================================"

echo "Simulating workload step 1..."
sleep 1
echo "Simulating workload step 2..."
sleep 1
echo "Experiment completed successfully!"
