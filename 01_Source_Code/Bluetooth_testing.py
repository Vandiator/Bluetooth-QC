#!/usr/bin/env python3
"""
Bluetooth Scanner CLI — Windows
Scans for both Bluetooth Classic and Bluetooth LE devices.

Dependencies:
    pip install bleak
    pip install PyBluez2          # for Classic scan (Windows socket backend)
    pip install colorama          # for colour output on Windows

Usage:
    python bt_scanner_windows.py              # scan both (default 8 s each)
    python bt_scanner_windows.py --classic    # Classic only
    python bt_scanner_windows.py --ble        # BLE only
    python bt_scanner_windows.py --duration 15
    python bt_scanner_windows.py --loop
    python bt_scanner_windows.py --json

Notes:
    • Run from an elevated prompt (Administrator) for Classic scan.
    • BLE requires Windows 10 1703+ (Creators Update) or later.
    • Classic scan uses WinSock Bluetooth (bt.discover_devices). 
      The Linux-only HCI/DeviceDiscoverer path is not used here.
"""

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

TARGET_DEVICE_NAME = "MOMAN CP-X"
TARGET_DEVICE_ADDRESS = "41:42:6F:47:F9:A2"

# ---------------------------------------------------------------------------
# Windows ANSI colour support
# ---------------------------------------------------------------------------

try:
    import colorama
    colorama.init(autoreset=False)
    _ANSI_READY = True
except ImportError:
    # Try enabling VT100 processing through the Win32 Console API as a fallback.
    try:
        import ctypes
        _kernel32 = ctypes.windll.kernel32
        _ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        _stdout_handle = _kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        _current_mode = ctypes.c_ulong()
        if _kernel32.GetConsoleMode(_stdout_handle, ctypes.byref(_current_mode)):
            _kernel32.SetConsoleMode(
                _stdout_handle,
                _current_mode.value | _ENABLE_VIRTUAL_TERMINAL_PROCESSING,
            )
    except Exception:
        pass
    _ANSI_READY = True

# ---------------------------------------------------------------------------
# Optional library imports
# ---------------------------------------------------------------------------

try:
    from bleak import BleakClient, BleakScanner
    from bleak.backends.device import BLEDevice as _BleakDevice
    BLEAK_AVAILABLE = True
except ImportError:
    BLEAK_AVAILABLE = False
    BleakClient = None

try:
    import bluetooth as bt
    PYBLUEZ_AVAILABLE = True
except ImportError:
    PYBLUEZ_AVAILABLE = False


# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

class Color:
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    DIM    = "\033[2m"
    CYAN   = "\033[96m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    RED    = "\033[91m"

    @classmethod
    def bold(cls, text: str) -> str:
        return f"{cls.BOLD}{text}{cls.RESET}"

    @classmethod
    def green(cls, text: str) -> str:
        return f"{cls.GREEN}{text}{cls.RESET}"

    @classmethod
    def dim(cls, text: str) -> str:
        return f"{cls.DIM}{text}{cls.RESET}"

    @classmethod
    def yellow(cls, text: str) -> str:
        return f"{cls.YELLOW}{text}{cls.RESET}"

    @classmethod
    def red(cls, text: str) -> str:
        return f"{cls.RED}{text}{cls.RESET}"

    @classmethod
    def cyan_bold(cls, text: str) -> str:
        return f"{cls.BOLD}{cls.CYAN}{text}{cls.RESET}"


# ---------------------------------------------------------------------------
# Signal-strength helper
# ---------------------------------------------------------------------------

def signal_bars(rssi: Optional[int]) -> str:
    """Return a 5-block Unicode bar representing Bluetooth signal strength.

    Thresholds (dBm):  ≥-60 excellent  ≥-70 good  ≥-80 fair  ≥-90 weak  else poor
    """
    if rssi is None:
        return "·····"
    filled = (
        5 if rssi >= -60 else
        4 if rssi >= -70 else
        3 if rssi >= -80 else
        2 if rssi >= -90 else
        1
    )
    return "█" * filled + "░" * (5 - filled)


def matches_target(
    device_name: str,
    device_address: str,
    target_name: str,
    target_address: str,
) -> bool:
    name_ok = False
    if target_name:
        target_name_l = target_name.strip().lower()
        device_name_l = (device_name or "").strip().lower()
        name_ok = target_name_l in device_name_l or device_name_l in target_name_l
    else:
        name_ok = True

    address_ok = False
    if target_address:
        target_address_l = target_address.strip().lower()
        device_address_l = (device_address or "").strip().lower()
        address_ok = target_address_l == device_address_l
    else:
        address_ok = True

    return name_ok and address_ok


# ---------------------------------------------------------------------------
# Device data models
# ---------------------------------------------------------------------------

@dataclass
class ClassicDevice:
    address: str
    name: str
    device_class: Optional[int] = None
    rssi: Optional[int] = None
    uuids: list = field(default_factory=list)

    def display_name(self) -> str:
        return self.name or "(unknown)"

    def rssi_str(self) -> str:
        bar = signal_bars(self.rssi)
        return f"{self.rssi} dBm  {bar}" if self.rssi is not None else f"n/a  {bar}"

    def uuids_preview(self) -> str:
        if not self.uuids:
            return ""
        preview = self.uuids[:3]
        suffix = f" … +{len(self.uuids) - 3} more" if len(self.uuids) > 3 else ""
        return ", ".join(preview) + suffix

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "name": self.name,
            "device_class": self.device_class,
            "rssi": self.rssi,
            "uuids": self.uuids,
        }


@dataclass
class BLEDevice:
    address: str
    name: str
    rssi: Optional[int] = None
    uuids: list = field(default_factory=list)
    manufacturer_data: dict = field(default_factory=dict)

    def display_name(self) -> str:
        return self.name or "(no name)"

    def rssi_str(self) -> str:
        bar = signal_bars(self.rssi)
        return f"{self.rssi} dBm  {bar}" if self.rssi is not None else f"n/a  {bar}"

    def uuids_preview(self) -> str:
        if not self.uuids:
            return ""
        preview = self.uuids[:3]
        suffix = f" … +{len(self.uuids) - 3} more" if len(self.uuids) > 3 else ""
        return ", ".join(preview) + suffix

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "name": self.name,
            "rssi": self.rssi,
            "uuids": self.uuids,
            "manufacturer_data": {
                str(k): v.hex() for k, v in self.manufacturer_data.items()
            },
        }


# ---------------------------------------------------------------------------
# Renderer — all terminal output lives here
# ---------------------------------------------------------------------------

class Renderer:
    WIDTH = 60

    def header(self, title: str) -> None:
        line = "─" * self.WIDTH
        print(f"\n{Color.cyan_bold(line)}")
        print(f"{Color.cyan_bold(f'  {title}')}")
        print(f"{Color.cyan_bold(line)}\n")

    def classic_device(self, dev: ClassicDevice, idx: int) -> None:
        print(
            f"  {Color.bold(f'[{idx}]')} {Color.green(dev.display_name())}"
            f"  {Color.dim(f'(RSSI: {dev.rssi_str()})')}"
        )
        print(f"       Address : {dev.address}")
        if dev.device_class is not None:
            print(f"       Class   : 0x{dev.device_class:06X}")
        if dev.uuids:
            print(f"       UUIDs   : {dev.uuids_preview()}")
        print()

    def ble_device(self, dev: BLEDevice, idx: int) -> None:
        print(
            f"  {Color.bold(f'[{idx}]')} {Color.green(dev.display_name())}"
            f"  {Color.dim(f'(RSSI: {dev.rssi_str()})')}"
        )
        print(f"       Address : {dev.address}")
        if dev.uuids:
            print(f"       UUIDs   : {dev.uuids_preview()}")
        for company_id, data in dev.manufacturer_data.items():
            print(f"       Mfr 0x{company_id:04X}: {data.hex()}")
        print()

    def summary(self, label: str, count: int) -> None:
        print(f"  {Color.bold(f'Total {label}: {count}')}\n")

    def not_found(self, label: str) -> None:
        print(f"  {Color.dim(f'No {label} devices found.')}\n")

    def scan_counter(self, num: int) -> None:
        print(f"\n{Color.dim(f'── Scan #{num} ──────────────────────────────')}")

    def waiting(self, seconds: int) -> None:
        print(Color.dim(f"Waiting {seconds}s before next scan …"))

    def interrupted(self) -> None:
        print(f"\n\n{Color.yellow('Scan interrupted by user.')}\n")

    def banner(self) -> None:
        print(f"\n{Color.bold('Bluetooth Scanner')}  {Color.dim('(press Ctrl+C to stop)')}")

    def missing_library(self, lib: str, install: str) -> None:
        print(Color.yellow(f"  [!] {lib} not installed — skipping scan."))
        print(f"      Install with: {install}\n")

    def scan_error(self, message: str) -> None:
        print(f"\n  {Color.red(f'Error: {message}')}")
        print(Color.dim(
            "  Ensure Bluetooth is enabled and the script is run as Administrator.\n"
        ))

    def no_libraries(self) -> None:
        print(Color.red("No Bluetooth libraries found. Install at least one:"))
        print("  BLE     : pip install bleak")
        print("  Classic : pip install PyBluez2")

    def target_details(self, dev: object, info: dict) -> None:
        print(f"\n{Color.green('Target device details')}\n")
        print(f"  Name      : {getattr(dev, 'display_name', lambda: str(dev))()}")
        print(f"  Address   : {getattr(dev, 'address', 'n/a')}")
        device_class = getattr(dev, 'device_class', None)
        if device_class is not None:
            print(f"  Class     : 0x{device_class:06X}")
        rssi_value = getattr(dev, 'rssi', None)
        if hasattr(dev, 'rssi_str'):
            print(f"  RSSI      : {dev.rssi_str()}")
        elif rssi_value is not None:
            print(f"  RSSI      : {rssi_value} dBm")
        else:
            print("  RSSI      : n/a")
        uuids = getattr(dev, 'uuids', [])
        if uuids:
            print(f"  UUIDs     : {dev.uuids_preview()}")
        print(f"  Connected : {'yes' if info.get('connected') else 'no'}")
        if info.get("reason"):
            print(f"  Reason    : {info['reason']}")
        services = info.get("services", [])
        if services:
            print("  Services  :")
            for svc in services[:8]:
                if isinstance(svc, dict):
                    name = svc.get("name") or svc.get("uuid") or "(no name)"
                    if svc.get("port") is not None:
                        print(f"    - {name} | port={svc.get('port')} | protocol={svc.get('protocol', '')}")
                    else:
                        print(f"    - {name}")
                else:
                    print(f"    - {svc}")
        else:
            print("  Services  : none discovered")
        if info.get("port") is not None:
            print(f"  Port      : {info['port']}")
        print()


# ---------------------------------------------------------------------------
# ClassicScanner  (Windows — WinSock backend only)
# ---------------------------------------------------------------------------

class ClassicScanner:
    """Discovers Classic (BR/EDR) Bluetooth devices on Windows.

    Uses bt.discover_devices() which calls the WinSock Bluetooth APIs
    (WSALookupServiceBegin / WSALookupServiceNext).  The Linux-only
    DeviceDiscoverer / HCI path is not available on Windows; consequently
    RSSI values are not reported for Classic devices.

    After discovery an SDP query fetches service-class UUIDs per device.
    """

    def __init__(self, renderer: Renderer):
        self._renderer = renderer

    # ── SDP UUID lookup ───────────────────────────────────────────────────

    def _read_uuids(self, address: str) -> list[str]:
        """SDP query — returns sorted service-class UUID strings."""
        try:
            services = bt.find_service(address=address)
            uuids: set[str] = set()
            for svc in services:
                for uuid in svc.get("service-classes", []):
                    uuids.add(str(uuid))
            return sorted(uuids)
        except Exception:
            return []

    # ── discovery via WinSock ─────────────────────────────────────────────

    def _collect_services(self, address: str) -> list[dict]:
        try:
            services = bt.find_service(address=address)
        except Exception:
            return []

        detailed = []
        for svc in services:
            detailed.append(
                {
                    "name": svc.get("name", ""),
                    "description": svc.get("description", ""),
                    "service-classes": [str(uuid) for uuid in svc.get("service-classes", [])],
                    "protocol": svc.get("protocol", ""),
                    "port": svc.get("port"),
                    "host": svc.get("host", ""),
                }
            )
        return detailed

    def _scan_winsock(self, duration: int) -> list[dict]:
        """bt.discover_devices() — Windows WinSock Bluetooth backend.

        RSSI is not available through this API path; the field is set to None.
        """
        raw = bt.discover_devices(
            duration=duration,
            lookup_names=True,
            lookup_class=True,
            flush_cache=True,
        )
        return [
            {
                "address":      addr,
                "name":         name or "",
                "device_class": cls,
                "rssi":         None,
            }
            for addr, name, cls in raw
        ]

    def connect_to_device(self, device: ClassicDevice) -> dict:
        if not PYBLUEZ_AVAILABLE:
            return {
                "services": [],
                "connected": False,
                "reason": "PyBluez2 is not available in this Python environment.",
            }

        try:
            services = self._collect_services(device.address)
        except Exception as exc:
            return {
                "services": [],
                "connected": False,
                "reason": f"SDP service lookup failed: {exc}",
            }

        if services:
            for svc in services:
                port = svc.get("port")
                if not isinstance(port, int):
                    continue
                try:
                    sock = bt.BluetoothSocket(bt.RFCOMM)
                    sock.connect((device.address, port))
                    sock.close()
                    return {"services": services, "connected": True, "port": port}
                except Exception as exc:
                    last_error = str(exc)
            return {
                "services": services,
                "connected": False,
                "reason": f"Discovered services, but none accepted an RFCOMM connection ({last_error}).",
                "port": None,
            }

        candidate_ports = [1, 2, 3, 5, 7, 9, 11, 15, 17, 19, 21, 23, 25, 29, 30, 31, 32, 33, 35, 37, 39, 41, 43, 45, 47, 49, 50, 51, 53, 55, 59, 60]
        for port in candidate_ports:
            try:
                sock = bt.BluetoothSocket(bt.RFCOMM)
                sock.connect((device.address, port))
                sock.close()
                return {"services": [], "connected": True, "port": port}
            except Exception:
                continue

        return {
            "services": [],
            "connected": False,
            "reason": "No SDP/RFCOMM services were exposed by the device, or the device is not accepting classic connections from this host.",
            "port": None,
        }

    # ── public scan ───────────────────────────────────────────────────────

    def scan(self, duration: int) -> list[ClassicDevice]:
        if not PYBLUEZ_AVAILABLE:
            self._renderer.missing_library(
                "PyBluez2", "pip install PyBluez2"
            )
            return []

        print(f"  Scanning for Classic devices ({duration}s) …", end="", flush=True)
        try:
            raw_infos = self._scan_winsock(duration)
        except OSError as exc:
            self._renderer.scan_error(str(exc))
            return []

        print(f" done ({len(raw_infos)} found). Querying SDP records …\n")

        return [
            ClassicDevice(
                address=info["address"],
                name=info["name"],
                device_class=info["device_class"],
                rssi=info["rssi"],
                uuids=self._read_uuids(info["address"]),
            )
            for info in raw_infos
        ]


# ---------------------------------------------------------------------------
# BLEScanner
# ---------------------------------------------------------------------------

class BLEScanner:
    """Discovers Bluetooth LE devices via bleak (Windows.Devices.Bluetooth / WinRT)."""

    def __init__(self, renderer: Renderer):
        self._renderer = renderer

    async def _collect(self, duration: int) -> list[BLEDevice]:
        discovered: dict[str, tuple] = {}

        def _on_device(device: "_BleakDevice", adv_data) -> None:
            discovered[device.address] = (device, adv_data)

        async with BleakScanner(detection_callback=_on_device):
            await asyncio.sleep(duration)

        results = []
        for address, (device, adv) in discovered.items():
            results.append(BLEDevice(
                address=address,
                name=device.name or adv.local_name or "",
                rssi=adv.rssi,
                uuids=list(adv.service_uuids) if adv.service_uuids else [],
                manufacturer_data=dict(adv.manufacturer_data) if adv.manufacturer_data else {},
            ))
        return results

    async def _inspect_ble_target(self, device: BLEDevice) -> dict:
        if not BLEAK_AVAILABLE or BleakClient is None:
            return {
                "connected": False,
                "reason": "bleak is not available in this Python environment.",
                "services": [],
            }

        try:
            async with BleakClient(device.address, timeout=10.0) as client:
                if not client.is_connected:
                    return {
                        "connected": False,
                        "reason": "BLE client could not connect to the device.",
                        "services": [],
                    }
                services = await client.get_services()
                service_info = []
                for svc in services:
                    characteristics = []
                    for char in svc.characteristics:
                        characteristics.append({
                            "uuid": str(char.uuid),
                            "properties": list(char.properties),
                        })
                    service_info.append({
                        "uuid": str(svc.uuid),
                        "characteristics": characteristics,
                    })
                return {"connected": True, "reason": "", "services": service_info}
        except Exception as exc:
            return {
                "connected": False,
                "reason": f"BLE GATT probe failed: {exc}",
                "services": [],
            }

    def scan(self, duration: int) -> list[BLEDevice]:
        if not BLEAK_AVAILABLE:
            self._renderer.missing_library("bleak", "pip install bleak")
            return []

        print(f"  Scanning for BLE devices ({duration}s) …", end="", flush=True)
        try:
            devices = asyncio.run(self._collect(duration))
        except Exception as exc:
            self._renderer.scan_error(str(exc))
            return []

        print(" done.\n")
        devices.sort(key=lambda d: d.rssi if d.rssi is not None else -999, reverse=True)
        return devices


# ---------------------------------------------------------------------------
# BluetoothScanner — orchestrator
# ---------------------------------------------------------------------------

class BluetoothScanner:
    def __init__(
        self,
        duration: int = 2,
        target_name: str = TARGET_DEVICE_NAME,
        target_address: str = TARGET_DEVICE_ADDRESS,
    ):
        self.duration = duration
        self.target_name = target_name
        self.target_address = target_address
        self._renderer = Renderer()
        self._classic = ClassicScanner(self._renderer)
        self._ble = BLEScanner(self._renderer)

    # ── single pass ──────────────────────────────────────────────────────────

    def scan_classic(self) -> list[ClassicDevice]:
        self._renderer.header("Bluetooth Classic Scan")
        devices = self._classic.scan(self.duration)
        if devices:
            for i, dev in enumerate(devices, 1):
                self._renderer.classic_device(dev, i)
                if matches_target(dev.display_name(), dev.address, self.target_name, self.target_address):
                    info = self._classic.connect_to_device(dev)
                    self._renderer.target_details(dev, info)
                    break
            self._renderer.summary("Classic", len(devices))
        else:
            self._renderer.not_found("Classic")
        return devices

    def scan_ble(self) -> list[BLEDevice]:
        self._renderer.header("Bluetooth LE Scan")
        devices = self._ble.scan(self.duration)
        if devices:
            for i, dev in enumerate(devices, 1):
                self._renderer.ble_device(dev, i)
                if matches_target(dev.display_name(), dev.address, self.target_name, self.target_address):
                    info = asyncio.run(self._ble._inspect_ble_target(dev))
                    self._renderer.target_details(dev, info)
                    break
            self._renderer.summary("BLE", len(devices))
        else:
            self._renderer.not_found("BLE")
        return devices

    def run_once(
        self, do_classic: bool = True, do_ble: bool = True
    ) -> tuple[list[ClassicDevice], list[BLEDevice]]:
        classic = self.scan_classic() if do_classic else []
        ble     = self.scan_ble()     if do_ble     else []
        return classic, ble

    # ── continuous loop ───────────────────────────────────────────────────────

    def run_loop(
        self, do_classic: bool = True, do_ble: bool = True
    ) -> tuple[list[ClassicDevice], list[BLEDevice]]:
        last_classic: list[ClassicDevice] = []
        last_ble:     list[BLEDevice]     = []
        scan_num = 0
        try:
            while True:
                scan_num += 1
                self._renderer.scan_counter(scan_num)
                last_classic, last_ble = self.run_once(do_classic, do_ble)
                self._renderer.waiting(self.duration)
                time.sleep(self.duration)
        except KeyboardInterrupt:
            self._renderer.interrupted()
        return last_classic, last_ble

    # ── JSON output ───────────────────────────────────────────────────────────

    @staticmethod
    def to_json(classic: list[ClassicDevice], ble: list[BLEDevice]) -> str:
        return json.dumps(
            {"classic": [d.to_dict() for d in classic],
             "ble":     [d.to_dict() for d in ble]},
            indent=2,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bt_scanner_windows",
        description="Scan for Bluetooth Classic and Bluetooth LE devices (Windows).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python bt_scanner_windows.py                  # scan both (default 8 s each)
  python bt_scanner_windows.py --classic        # Classic only
  python bt_scanner_windows.py --ble            # BLE only
  python bt_scanner_windows.py --duration 15    # longer scan window
  python bt_scanner_windows.py --loop           # keep scanning until Ctrl+C
  python bt_scanner_windows.py --json           # output as JSON

Notes:
  Run as Administrator for Classic Bluetooth scanning.
  BLE scanning requires Windows 10 version 1703 (Creators Update) or later.
        """,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--classic", action="store_true", help="Scan Classic Bluetooth only")
    mode.add_argument("--ble",     action="store_true", help="Scan Bluetooth LE only")

    parser.add_argument("--duration", "-d", type=int, default=8,
                        metavar="SECS", help="Scan duration in seconds (default: 8)")
    parser.add_argument("--loop", "-l", action="store_true",
                        help="Repeat scans continuously until Ctrl+C")
    parser.add_argument("--json", "-j", action="store_true",
                        help="Output results as JSON")
    parser.add_argument("--target-name", default=TARGET_DEVICE_NAME,
                        help="Device name to look for and inspect")
    parser.add_argument("--target-address", default=TARGET_DEVICE_ADDRESS,
                        help="Device address to look for and inspect")
    return parser


def main() -> None:
    args     = build_parser().parse_args()
    renderer = Renderer()

    if not BLEAK_AVAILABLE and not PYBLUEZ_AVAILABLE:
        renderer.no_libraries()
        sys.exit(1)

    renderer.banner()

    do_classic = not args.ble
    do_ble     = not args.classic
    scanner    = BluetoothScanner(
        duration=args.duration,
        target_name=args.target_name,
        target_address=args.target_address,
    )

    try:
        if args.loop:
            classic, ble = scanner.run_loop(do_classic, do_ble)
        else:
            classic, ble = scanner.run_once(do_classic, do_ble)
    except KeyboardInterrupt:
        renderer.interrupted()
        classic, ble = [], []

    if args.json:
        print(BluetoothScanner.to_json(classic, ble))


if __name__ == "__main__":
    main()

