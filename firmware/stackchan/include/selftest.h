#pragma once

// LAN-01 hardware bring-up self-test. Runs once at boot and prints a
// PASS/FAIL report to serial. It does not claim remote verification.
void run_selftest();
