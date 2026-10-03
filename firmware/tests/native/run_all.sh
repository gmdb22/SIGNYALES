#!/bin/bash
# Signyales — Run all native firmware logic tests
# No ESP32 toolchain, no PlatformIO, no hardware — just g++.
set -e

cd "$(dirname "$0")"

echo "=== Building ==="
g++ -Wall -Wextra -I../../glove/src -o test_packet_logic test_packet_logic.cpp
g++ -Wall -Wextra -I../../receiver/src -o test_frame_logic test_frame_logic.cpp

echo ""
echo "=== packet.h (glove <-> receiver) ==="
./test_packet_logic
PACKET_RESULT=$?

echo ""
echo "=== frame.h (receiver <-> Pi) ==="
./test_frame_logic
FRAME_RESULT=$?

echo ""
if [ $PACKET_RESULT -eq 0 ] && [ $FRAME_RESULT -eq 0 ]; then
  echo "ALL NATIVE LOGIC TESTS PASSED"
  exit 0
else
  echo "SOME TESTS FAILED — see output above"
  exit 1
fi
