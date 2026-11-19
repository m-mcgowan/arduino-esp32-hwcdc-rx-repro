# HWCDC stops receiving when the host writes before `Serial.begin()`

A minimal reproduction of an arduino-esp32 3.3.13 regression on chips with the USB Serial/JTAG
port (ESP32-S3, C3, C6, H2), and a way to try the fix.

**The symptom.** The sketch keeps printing, but never receives another byte from the host.
`Serial.available()` stays 0 and host writes block. A reset doesn't clear it; only the ROM
bootloader does (an esptool upload, or booting with BOOT held).

**The trigger.** The host sends data after the chip resets, before the sketch calls
`Serial.begin()`. Plenty of hosts do this:
- a test runner that flushes the line when it connects;
- a tool that probes new ports for a bootloader;
- a terminal where someone presses a key during boot.

A slow boot widens the window. This sketch makes it certain by waiting 3 s before `Serial.begin()`.

**The cause.** [#13048](https://github.com/espressif/arduino-esp32/pull/13048) made `HWCDC::begin()`
clear every pending USB Serial/JTAG interrupt flag:

```cpp
usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_LL_INTR_MASK);
```

That includes `SERIAL_OUT_RECV_PKT`. A packet the host sent before `begin()` stays in the RX FIFO
with its flag cleared, so the interrupt handler never reads it, and the peripheral refuses
(NAKs) every later packet. 3.3.11 does not clear the flags and is not affected.

**The fix** keeps that one flag:

```cpp
usb_serial_jtag_ll_clr_intsts_mask(USB_SERIAL_JTAG_LL_INTR_MASK & ~USB_SERIAL_JTAG_INTR_SERIAL_OUT_RECV_PKT);
```

## What you need

- An ESP32-S3 board. A C3, C6 or H2 also works; change `board` in `platformio.ini`.
- A cable to the board's **native USB** port. A USB-to-UART bridge port won't show the bug.
- Python 3 with pyserial (`pip install pyserial`).
- PlatformIO, or the Arduino IDE with arduino-esp32 3.3.13.

## Run it with PlatformIO

```bash
pio run -e stock -t upload --upload-port <port>
python host.py <port>          # expect: RESULT early_write=True passed=0/5

pio run -e fixed -t upload --upload-port <port>
python host.py <port>          # expect: RESULT early_write=True passed=5/5
```

Both environments use pioarduino 55.03.313 (arduino-esp32 3.3.13, ESP-IDF 5.5.6). `fixed` swaps
in arduino-esp32 3.3.13 plus the one-line fix, from the branch
[`fix/hwcdc-keep-pending-rx-3.3.13`](https://github.com/m-mcgowan/arduino-esp32/tree/fix/hwcdc-keep-pending-rx-3.3.13).

The upload goes through the ROM bootloader, which clears a stuck port, so each run starts clean.

## Run it with the Arduino IDE

1. Open `repro/repro.ino`, select your board and arduino-esp32 3.3.13.
2. Set **USB CDC On Boot: Enabled** and **USB Mode: Hardware CDC and JTAG**.
3. Upload, close the Serial Monitor, and run `python host.py <port>`.
4. To try the fix, edit `cores/esp32/HWCDC.cpp` in the installed core and replace the line
   shown above in `HWCDC::begin()`. The core is in `~/Library/Arduino15/packages/esp32/hardware/esp32/3.3.13/`
   on macOS, `%LOCALAPPDATA%\Arduino15\packages\esp32\hardware\esp32\3.3.13\` on Windows and
   `~/.arduino15/packages/esp32/hardware/esp32/3.3.13/` on Linux. Then upload and run `host.py` again.

## What `host.py` does

Each try:
1. Opens the port and resets the board by toggling DTR and RTS.
2. Writes `"\n"` straight away, while the sketch is still waiting to call `Serial.begin()`.
3. Waits for the sketch's `BOOT` line, sends `PING` and waits for `PONG`.

`--no-early-write` skips step 2. That run passes on both builds, which shows the early write
is the trigger. `--tries N` sets how many tries to make (default 5).

On the stock build, a try fails like this. The sketch keeps printing, but nothing the host sends
gets in, not even the early newline:

```
try 1/5
    0.10 > "\n" (early write, before Serial.begin())
    3.10 < BOOT core=3.3.13 reset_reason=11
    3.10 < ALIVE 0 rx_avail=0
    3.10 > PING
    4.10 < ALIVE 1 rx_avail=0
    4.20 > PING
    ...
    8.10 < ALIVE 5 rx_avail=0
  FAIL: no PONG (the device is not reading host data)
```

With the fix, the early newline is waiting in `Serial` when the sketch starts, and PING gets its
answer straight away:

```
try 1/5
    0.10 > "\n" (early write, before Serial.begin())
    3.10 < BOOT core=3.3.13 reset_reason=11
    3.10 < ALIVE 0 rx_avail=1
    3.10 > PING
    3.10 < PONG
  PASS
```

Measured on an ESP32-S3 board (macOS host):

| Build | Early write | Passed |
| --- | --- | --- |
| `stock` | no | 3 of 3 |
| `stock` | yes | 0 of 5 |
| `fixed` | yes | 5 of 5 |
| `fixed` | no | 3 of 3 |

## A second issue: the IN-token interrupt's CPU cost

`in-token/` measures another side effect of #13048. To see when a host has the port open,
`HWCDC::begin()` enables the `TOKEN_REC_IN_EP1` interrupt and leaves it on, so while a host has
the port open the chip takes one interrupt for every IN token the host sends. The sketch counts
`loop()` iterations per second at 80 MHz:

```bash
pio run -d in-token -e stock -t upload --upload-port <port>
# then open the port with any serial monitor and read the loops/s lines for ~15 s
```

| Environment | Core | `loop()` iterations/s |
| --- | --- | --- |
| `v3311` | 3.3.11 | 58,495 |
| `stock` | 3.3.13 | about 46,500 |
| `sampled` | 3.3.13, interrupt off, the token's raw status sampled in `isCDC_Connected()` | 58,993 |

`sampled` uses the fork tag
[`3.3.13-hwcdc2`](https://github.com/m-mcgowan/arduino-esp32/tree/3.3.13-hwcdc2), which has both
fixes. `while (!Serial)` still sees the port open with it.

## Related

- [#13048](https://github.com/espressif/arduino-esp32/pull/13048) "fix(hwcdc): detect host open from
  IN tokens and DTR" added the line, and shipped in 3.3.13.
- [#13096](https://github.com/espressif/arduino-esp32/issues/13096) and
  [#13103](https://github.com/espressif/arduino-esp32/pull/13103) are about connection detection after
  that change, and don't cover this.
