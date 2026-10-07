# DBD Haptics

An experimental, external screen-reading haptics bridge for **Dead by Daylight**. It watches visible HUD elements with screen capture/OpenCV/Tesseract and sends vibration commands to Buttplug-compatible hardware through **Intiface Central**.

> **Unofficial project.** Not affiliated with, endorsed by, or supported by Behaviour Interactive, Dead by Daylight, Buttplug.io, or Intiface.

## What it detects

- **Terror-radius / heartbeat state** → constant low buzz while active
- **Injury/red HUD flash** → short stronger effect
- **Action text** such as Repair, Heal, Recover, Wiggle, Struggle, Cleanse, etc. → continuous configurable output while the action is visible

Overlapping effects use the stronger requested output. For example, an injury effect can temporarily override a heartbeat/action and then return to the continuous effect underneath it.

## External-only design

This project captures pixels from the display. It does **not** read game memory, inject DLLs, hook the game, inspect game network traffic, or attempt to bypass anti-cheat. That does not constitute a guarantee that any third-party tool is permitted by a game's rules; users are responsible for deciding whether to run it.

## Requirements

- Windows (current calibration/testing target)
- Python 3.10+
- Tesseract OCR
- Intiface Central
- A Buttplug-compatible vibration device
- Dead by Daylight at a compatible HUD layout/resolution

The current default capture regions were calibrated for **1920×1080** and may require editing for other resolutions or HUD scales.

## Install

1. Install Python 3.10 or newer.
2. Install Tesseract OCR. The default script path is `C:\Program Files\Tesseract-OCR\tesseract.exe`.
3. Install and start Intiface Central, then start its Engine.
4. Clone/download this repository.
5. In PowerShell, from the repository folder, run:

```powershell
py -m pip install -r requirements.txt
```

## Test Intiface first

Before running the detector:

```powershell
py buttplug_test.py
```

It scans for 10 seconds and briefly tests vibration at 30%. If this fails, troubleshoot Intiface/device connectivity before troubleshooting screen detection.

## Run

```powershell
py dbd_haptics.py
```

Press **Q** in the detector window to quit. The program sends a stop command to connected devices during normal shutdown.

## Configuration

The main settings are near the top of `dbd_haptics.py`:

- `MONITOR_NUMBER`
- `TESSERACT_PATH`
- `INTIFACE_ADDRESS`
- `regions`
- `ACTION_STRENGTHS`
- `HEARTBEAT_STRENGTH`
- `INJURY_STRENGTH`
- detection thresholds

`config.example.py` also contains the key calibration values as a quick reference.

### Current 1920×1080 regions

| Region | x | y | width | height |
|---|---:|---:|---:|---:|
| Health | 50 | 380 | 300 | 420 |
| Heartbeat | 605 | 400 | 695 | 600 |
| Action bar | 800 | 815 | 340 | 180 |

Coordinates are relative to the selected monitor; the program adds the monitor's desktop offset automatically.

## Troubleshooting

**Intiface connects but no hardware appears:** confirm the Engine is running, the device is powered on, and another phone/app is not already connected to it.

**`btleplug ... NotConnected`:** test the device directly in Intiface Central, power-cycle it, make sure another app does not own the BLE connection, then retry `buttplug_test.py`.

**OCR fails:** verify `TESSERACT_PATH`, HUD scale, resolution, and the action-bar capture region.

**Wrong part of screen captured:** set `MONITOR_NUMBER` correctly and recalibrate `regions` for your display/HUD setup.

## Repository files

- `dbd_haptics.py` — main detector + Intiface integration
- `buttplug_test.py` — standalone hardware test
- `config.example.py` — calibration/configuration reference
- `requirements.txt` — Python dependencies
- `CONTRIBUTING.md` — contribution guidance
- `LICENSE` — MIT license
- `.gitignore` — common Python/editor exclusions

## Dependencies / acknowledgements

This project builds on OpenCV, MSS, NumPy, pytesseract/Tesseract, and the Buttplug Python client. Intiface Central provides the hardware server.

## Safety

Start with low output levels. Device behavior and supported capabilities vary. Stop the program or Intiface Engine if output behaves unexpectedly.
