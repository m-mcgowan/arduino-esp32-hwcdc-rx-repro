<!-- Draft of the PR for espressif/arduino-esp32, from m-mcgowan:fix/hwcdc-keep-pending-rx into master. -->

# fix(hwcdc): keep host data that arrives before begin()

## Description of Change

#13048 added `usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_LL_INTR_MASK)` to `HWCDC::begin()`. That
also clears `USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT`. If the host sent data after a reset but before the
sketch called `Serial.begin()`, the packet is still in the RX FIFO, but with its flag cleared the ISR never
runs to read it, and the peripheral NAKs every later OUT packet. RX stays dead (TX keeps working) until the
ROM bootloader resets the peripheral.

This change leaves `SERIAL_OUT_RECV_PKT` set when `begin()` clears the other flags, so the ISR drains the
pending packet as soon as `begin()` enables the interrupt. The other flags are still cleared as #13048
intended. `end()` is unchanged.

## Test Scenarios

ESP32-S3 (custom board, native USB Serial/JTAG port), macOS host, PlatformIO with pioarduino 55.03.313
(arduino-esp32 3.3.13, ESP-IDF 5.5.6). The change applies unmodified to master; tested as 3.3.13 plus this
commit.

Repro: https://github.com/m-mcgowan/arduino-esp32-hwcdc-rx-repro. The sketch waits 3 s before
`Serial.begin()`; the host resets the board, writes a newline at once, then sends PING and waits for PONG.

| Build | Host writes before `begin()` | Passed |
| --- | --- | --- |
| 3.3.13 | no | 3 of 3 |
| 3.3.13 | yes | 0 of 5 |
| 3.3.13 + this change | yes | 5 of 5 |
| 3.3.13 + this change | no | 3 of 3 |

With this change the early byte is delivered (`Serial.available()` is 1 when the sketch starts) instead of
blocking the port.

Earlier, on a slow-booting image (a stored core dump lengthens the boot), 10 tries each with the host
writing when the port is available without delay: 3.3.13 lost RX 10 of 10 times; 3.3.13 with this change, and 3.3.13 with 3.3.11's
`HWCDC.cpp`, 0 of 10.

## Related links

Closes #ISSUE
Regression from #13048. Related: #13096, #13103.
