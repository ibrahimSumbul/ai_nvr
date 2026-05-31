"""Zone konfigürasyonu — YAML'dan Pydantic'e.

`bridge/config/zones.yaml` veya `.env` üzerinden override edilebilir path'ten
zone tanımları yüklenir. Şema `docs/04-zone-rules.md`'de açıklanmıştır.

M2: tek pilot zone. M5: 10 zone'a kadar genişler.
M6.5: type='door' eklendiğinde TraversalDetector devreye girer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class ZoneRules(BaseModel):
    """Bir zone'un davranış kuralları."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    type: Literal["room", "door"] = "room"

    # Oda (room) kuralları
    first_entry_alarm: bool = True
    exit_alarm: bool = False
    exit_timeout_seconds: int = Field(default=60, ge=5, le=600)
    min_person_score: float = Field(default=0.6, ge=0.0, le=1.0)
    active_hours: str = "00:00-23:59"
    alert_on_empty_arrival: bool = True

    # M4 — bu zone'un Dahua NVR'daki external alarm (virtual input) channel'ı.
    # Gerçek kurulumda her izlenen alan bir NVR channel'ına map edilir.
    dahua_channel: int = Field(default=1, ge=1, le=256)

    # Kapı (door) kuralları — M6.5'te kullanılır
    log_precision: Literal["second", "millisecond"] = "second"
    direction_detection: bool = False
    email_notification: bool = False
    include_short_clip: bool = False
    cooldown_seconds: int = Field(default=3, ge=0, le=60)
    track_objects: list[str] = Field(default_factory=lambda: ["person"])


class ZoneConfig(BaseModel):
    """Tek bir zone tanımı."""

    model_config = ConfigDict(extra="forbid")

    name: str  # bridge için unique adres (örn. 'zone_depo_1')
    camera: str  # Frigate camera adı
    frigate_zone: str  # Frigate config içindeki zone adı
    rules: ZoneRules = Field(default_factory=ZoneRules)


class ZonesConfig(BaseModel):
    """Tüm zone'ların listesi."""

    model_config = ConfigDict(extra="forbid")

    zones: list[ZoneConfig] = Field(default_factory=list)

    def by_name(self, name: str) -> ZoneConfig | None:
        return next((z for z in self.zones if z.name == name), None)

    def for_camera(self, camera: str) -> list[ZoneConfig]:
        return [z for z in self.zones if z.camera == camera]


def load_zones_config(path: str | Path) -> ZonesConfig:
    """YAML dosyasından zones config'i yükle ve validate et."""
    path = Path(path)
    if not path.exists():
        return ZonesConfig(zones=[])
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return ZonesConfig.model_validate(data)
