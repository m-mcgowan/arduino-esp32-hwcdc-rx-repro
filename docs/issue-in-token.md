<!-- Draft of the issue for espressif/arduino-esp32 (bug report form). Fields are in the form's order. -->

# [HWCDC] The IN-token interrupt from #13048 takes ~20% of the CPU while a host has the port open (3.3.13)

## Board

ESP32-S3-DevKitC-1 compatible (custom ESP32-S3 board, native USB Serial/JTAG port). Should apply to every
SoC with the USB Serial/JTAG peripheral.

## Device Description

ESP32-S3 module on a custom board, connected to the host through the chip's native USB port (USB Serial/JTAG,
no USB-UART bridge).

## Hardware Configuration

For the measurement below, nothing but the native USB port. In our application a UART at 230400 baud
(UART0, default pins) talks to a modem-like peripheral.

## Version

v3.3.13

## Type

Bug

## IDE Name

PlatformIO (pioarduino 55.03.313)

## Operating System

macOS 14.5

## Flash frequency

80 MHz

## PSRAM enabled

no

## Upload speed

921600

## Description

Since 3.3.13, while a host has the USB Serial/JTAG port open, the chip spends about a fifth of its CPU
time at 80 MHz in the HWCDC interrupt, even when the sketch sends and receives nothing over USB.

**Cause.** To tell when a host has the port open, #13048 enables `USB_SERIAL_JTAG_INTR_TOKEN_REC_IN_EP1` in
`HWCDC::begin()` and never disables it. A host with the port open polls the IN endpoint continuously, so
the chip takes one interrupt per IN token for as long as the port is open.

**Impact.** Anything with a tight CPU budget slows down whenever a USB host is attached and reading. We
found it as a UART that started losing bytes: our firmware reads 8 KB from a peripheral at 230400 baud,
one byte per `read()`, at 80 MHz. On 3.3.11 it reads at 16.5 KB/s without loss; on 3.3.13, with the port
open, the UART's RX ring buffer fills and its FIFO overflows (`UART_BUFFER_FULL_ERROR` 15 times,
`UART_FIFO_OVF_ERROR` 14 times) and about 1.7 KB of the 8.2 KB are lost, every time. Only removing the
IN-token interrupt from 3.3.13 brings it back to the 3.3.11 numbers exactly.

**Measurement.** The sketch below counts `loop()` iterations per second at 80 MHz while a serial monitor
has the port open, on the same board and platform (pioarduino 55.03.313, ESP-IDF 5.5.6), changing only
the Arduino core:

| Core | `loop()` iterations/s |
|---|---|
| 3.3.11 | 58,495 |
| ❌ 3.3.13 | 46,074 – 46,532 |
| ✅ 3.3.13, IN-token interrupt off, token sampled instead (below) | 58,993 |

That is about 21% fewer iterations on 3.3.13. Per-token rates depend on the host, so other hosts may
see more or less.

**Suggested fix.** The interrupt is not needed to see the tokens: `TOKEN_REC_IN_EP1`'s raw status bit
latches without it. Leaving the interrupt off and sampling the bit in `isCDC_Connected()` keeps the open
detection (a token since the last check counts as a token now) without an interrupt per token:

```cpp
// isCDC_Connected(), before the token time is read
const bool polled = (usb_serial_jtag_ll_get_intraw_mask() & USB_SERIAL_JTAG_INTR_TOKEN_REC_IN_EP1) != 0;
if (polled) {
  usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_INTR_TOKEN_REC_IN_EP1);
}
portENTER_CRITICAL_SAFE(&hw_cdc_tx_mux);
now = esp_timer_get_time();
if (polled) {
  last_in_token_us = now;
}
token_us = last_in_token_us;
```

plus dropping `USB_SERIAL_JTAG_INTR_TOKEN_REC_IN_EP1` from the mask in `begin()`, and clearing it with
`USB_SERIAL_JTAG_INTR_BUS_RESET` in the ISR, so a token latched before a bus reset does not count after it.
With that, `while (!Serial)` still sees the port open (the "3.3.13, token sampled" row above), and our UART
reads without loss again. The change is in a fork commit on top of 3.3.13:
https://github.com/m-mcgowan/arduino-esp32/commit/bdbd56e247e590d4ad322fcd0b0bce45c5df4ed3. The checks are spaced by how often the sketch writes, so a close is seen one check
later than now; we did not see any other difference.

This is a second issue from #13048, next to #13137 (RX stops if the host writes before `Serial.begin()`).

## Sketch

```cpp
// How much CPU does the USB Serial/JTAG IN-token interrupt take while a host has the port open?
// Runs at 80 MHz and counts loop() iterations per second.
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
```

A PlatformIO project with the three cores as environments: https://github.com/m-mcgowan/arduino-esp32-hwcdc-rx-repro/tree/main/in-token.

## Debug Message

```
3.3.13:                       loops/s=46451 46467 46480 46532 46527 46500 ...
3.3.13, token sampled:        loops/s=58993 58993 58993 58993 58993 58993 ...
3.3.11:                       loops/s=58495 58495 58495 58494 58495 58495 ...
```

## Other Steps to Reproduce

Open the port with any serial monitor and leave it open; the monitor only has to be reading.

## I have checked existing issues, online documentation and the Troubleshooting Guide

- [x] I confirm I have checked existing issues, online documentation and Troubleshooting Guide.
