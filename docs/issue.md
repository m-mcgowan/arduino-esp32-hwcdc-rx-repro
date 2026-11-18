<!-- Draft of the issue for espressif/arduino-esp32 (bug report form). Fields are in the form's order. -->

# [HWCDC] RX stops for good if the host writes before Serial.begin() (regression in 3.3.13, #13048)

## Board

ESP32-S3-DevKitC-1 compatible (custom ESP32-S3 board, native USB Serial/JTAG port). Should apply to every
SoC with the USB Serial/JTAG peripheral.

## Device Description

ESP32-S3 module on a custom board, connected to the host through the chip's native USB port (USB Serial/JTAG,
no USB-UART bridge).

## Hardware Configuration

Nothing attached that matters here; only the native USB port is used.

## Version

v3.3.13

## Type

Bug

## IDE Name

PlatformIO (pioarduino 55.03.313); Arduino IDE also affected

## Operating System

macOS 14.5

## Flash frequency

80 MHz

## PSRAM enabled

no

## Upload speed

921600

## Description

Since 3.3.13, if the host sends data to the USB Serial/JTAG port after a reset but before the sketch calls
`Serial.begin()`, the port never receives again. The sketch keeps printing, but `Serial.available()` stays 0
and host writes block (the device NAKs every OUT packet). Resetting the chip does not recover it: the state
lasts until the ROM bootloader runs (an esptool upload, or booting with BOOT held).

Hosts that talk first are common: test runners that flush the line on connect, tools that probe new ports
for a bootloader, a key pressed in a terminal during boot. Anything that slows the boot widens the window.
We hit it with a test runner; a stored core dump in flash, which makes the boot longer, made it fail most
of the time.

**Cause.** #13048 added this to `HWCDC::begin()` (`cores/esp32/HWCDC.cpp`):

```cpp
usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_LL_INTR_MASK);
```

It clears `USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT` along with the others. A packet that arrived before
`begin()` is still in the RX FIFO, but with its flag cleared the ISR never runs to read it, and the
peripheral accepts no further OUT packets while the FIFO holds it.

**Fix.** Keep that flag, so the ISR drains the pending packet as soon as `begin()` enables the interrupt:

```cpp
usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_LL_INTR_MASK & ~USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT);
```

PR: <!-- link the PR from m-mcgowan:fix/hwcdc-keep-pending-rx once opened -->

**Measurements** (ESP32-S3, PlatformIO, 10 tries each; host resets the board and writes at once; boot
slowed by a stored core dump):

| arduino-esp32 build | RX dead |
| --- | --- |
| 3.3.13 | 10 of 10 |
| 3.3.13, only the line above changed | 0 of 10 |
| 3.3.13 with 3.3.11's `HWCDC.cpp` | 0 of 10 |
| 3.3.11 | 0 of 10 |

With the core dump erased (shorter boot), every build passed 10 of 10.

**Repro:** https://github.com/m-mcgowan/arduino-esp32-hwcdc-rx-repro. A sketch that waits 3 s before
`Serial.begin()`, and a pyserial script that resets the board, writes a newline at once, then sends PING and
waits for PONG. Its PlatformIO `stock` and `fixed` environments differ only by the line above. With that
sketch there is no core dump involved, and the result is the same every time:

| Build | Early write | Passed |
| --- | --- | --- |
| 3.3.13 | no | 3 of 3 |
| 3.3.13 | yes | 0 of 5 |
| 3.3.13 + fix | yes | 5 of 5 |
| 3.3.13 + fix | no | 3 of 3 |

Related: #13096 / #13103 fixed connection detection after #13048, but not this.

## Sketch

```cpp
#include <Arduino.h>

static String line;

void setup() {
  delay(3000);  // stands in for a slow boot; the host writes during this window
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
```

Host side (pyserial; full script in the repro):

```python
ser = serial.Serial(port, 115200, timeout=0.1, write_timeout=2)
ser.dtr = False; ser.rts = False; time.sleep(0.1)  # reset into the sketch
ser.dtr = True; ser.rts = True
ser.write(b"\n")                                   # lands before Serial.begin()
# ...wait for BOOT, send "PING\n", expect "PONG": never arrives on 3.3.13
```

## Debug Message

host.py against the sketch above, stock 3.3.13. The device prints, but `rx_avail` stays 0 and no PING is
answered:

```
try 1/5
    0.10 > "\n" (early write, before Serial.begin())
    3.10 < BOOT core=3.3.13 reset_reason=11
    3.10 < ALIVE 0 rx_avail=0
    3.10 > PING
    4.10 < ALIVE 1 rx_avail=0
    4.20 > PING
    5.10 < ALIVE 2 rx_avail=0
    5.30 > PING
    6.10 < ALIVE 3 rx_avail=0
    6.30 > PING
    7.10 < ALIVE 4 rx_avail=0
    7.30 > PING
    8.10 < ALIVE 5 rx_avail=0
  FAIL: no PONG (the device is not reading host data)
...
RESULT early_write=True passed=0/5
```

Same sketch and host with the fix: the early newline is still there after `begin()`, and PING is answered.

```
try 1/5
    0.10 > "\n" (early write, before Serial.begin())
    3.10 < BOOT core=3.3.13 reset_reason=11
    3.10 < ALIVE 0 rx_avail=1
    3.10 > PING
    3.10 < PONG
  PASS
...
RESULT early_write=True passed=5/5
```

## Other Steps to Reproduce

Without the early write (`host.py --no-early-write`) the stock build passes 3 of 3, so the write before
`begin()` is the trigger.

## I have checked existing issues, online documentation and the Troubleshooting Guide

- [x] I confirm I have checked existing issues, online documentation and Troubleshooting guide.
