// How much CPU does the USB Serial/JTAG IN-token interrupt take while a host has the port open?
//
// Runs at 80 MHz and counts loop() iterations per second. Compare cores with the port open and
// read: the more interrupts the chip takes, the fewer iterations it gets through.
//
// The boot line also shows whether `while (!Serial)` saw the port open, and how long it took.

#include <Arduino.h>

static constexpr uint32_t OPEN_WAIT_MS = 10000;

void setup() {
  setCpuFrequencyMhz(80);
  Serial.begin(115200);
  const uint32_t t0 = millis();
  while (!Serial && millis() - t0 < OPEN_WAIT_MS) {
    delay(10);
  }
  Serial.printf("BOOT core=%s cpu=%luMHz serial_open=%d after=%lums\n", ESP_ARDUINO_VERSION_STR,
                (unsigned long)getCpuFrequencyMhz(), (bool)Serial ? 1 : 0, (unsigned long)(millis() - t0));
}

void loop() {
  static uint32_t loops = 0;
  static uint32_t t0 = millis();
  loops++;
  const uint32_t now = millis();
  if (now - t0 >= 1000) {
    Serial.printf("loops/s=%lu\n", (unsigned long)loops);
    loops = 0;
    t0 = now;
  }
}
