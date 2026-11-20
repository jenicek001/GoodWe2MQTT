"""A device's own online/offline status and a read-only Home Assistant MQTT discovery (SmartHomeDesign-EMS REQ-081).

`<base>/status` is retained: `online` while the device (inverter, SEC1000S) has answered within its window, `offline`
when it has not, and `offline` as goodwe2mqtt's MQTT last will when goodwe2mqtt itself is gone. Before 2026-11-20 it
was a quoted "online" every 30 s, sent even while the device could not be read, and never offline.

The discovery announces one measured value with that availability topic and no command topic: a monitor that reads
discovery (the SmartHomeDesign EMS edge, Home Assistant) finds the device and its status, and nothing gains control.
"""
import json
from typing import List, Optional, Tuple

ONLINE, OFFLINE = "online", "offline"
MIN_WINDOW_S = 60.0                     # never offline sooner than this after the last good read


def window_s(interval_s: float) -> float:
    """How long after its last good read a device still counts as online: three of its reads, at least a minute."""
    return max(3.0 * float(interval_s), MIN_WINDOW_S)


def device_state(last_ok: Optional[float], now: float, window: float) -> str:
    return ONLINE if last_ok is not None and now - last_ok <= window else OFFLINE


def status_discovery(prefix: str, uid: str, name: str, model: str, state_topic: str, value_key: str, unit: str,
                     device_class: str, status_topic: str) -> List[Tuple[str, str]]:
    """(topic, payload) to publish retained; none when the prefix is empty (discovery off)."""
    if not prefix:
        return []
    cfg = {"name": value_key.replace("_", " ").capitalize(), "uniq_id": f"{uid}_{value_key}_status",
           "stat_t": state_topic, "val_tpl": "{{ value_json.%s }}" % value_key, "unit_of_meas": unit,
           "dev_cla": device_class, "stat_cla": "measurement",
           "avty_t": status_topic, "pl_avail": ONLINE, "pl_not_avail": OFFLINE,
           "dev": {"ids": [uid], "name": name, "mf": "GoodWe", "mdl": model}}
    return [(f"{prefix}/sensor/{uid}/{value_key}/config", json.dumps(cfg))]
