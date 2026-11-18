// HWCDC RX dies when the host writes before Serial.begin() (arduino-esp32 3.3.13).
//
// The sketch waits BEGIN_DELAY_MS before Serial.begin(), standing in for a slow boot. A host
// that writes during that window leaves a packet in the USB Serial/JTAG RX FIFO. On 3.3.13,
// begin() clears that packet's interrupt flag, nothing reads it, and the port never delivers
// host data again. TX keeps working, so the heartbeat shows the sketch is alive.
//
//   PING -> PONG
//
// Build with USB CDC On Boot enabled and USB Mode "Hardware CDC and JTAG"
// (ARDUINO_USB_CDC_ON_BOOT=1, ARDUINO_USB_MODE=1), and plug in the board's native USB port.

#include <Arduino.h>

#ifndef BEGIN_DELAY_MS
#define BEGIN_DELAY_MS 3000
#endif

static String line;

void setup() {
  delay(BEGIN_DELAY_MS);
  Serial.begin(115200);
  Serial.printf("BOOT core=%s reset_reason=%d\n", ESP_ARDUINO_VERSION_STR, (int)esp_reset_reason());
}

void loop() {
  static uint32_t last = 0, beat = 0;
  if (millis() - last >= 1000) {
    last = millis();
    Serial.printf("ALIVE %lu rx_avail=%d\n", (unsigned long)beat++, Serial.available());
  }
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') {
      continue;
    }
    if (c != '\n') {
      line += c;
      continue;
    }
    if (line == "PING") {
      Serial.println("PONG");
    }
    line = "";
  }
}
