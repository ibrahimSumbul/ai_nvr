"""Frigate MQTT event modelleri.

Frigate `frigate/events` topic'ine üç tip event publish eder:
- new:    yeni obje tespit edildi (tracking başlar)
- update: takip edilen obje güncellendi (pozisyon, zone, score)
- end:    obje kayboldu (tracking sona erdi)

Bridge bu event'leri JSON olarak alır, Pydantic ile validate eder,
zone state machine'e yönlendirir.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FrigateObject(BaseModel):
    """Frigate'in tespit ettiği bir obje (person/car/truck/...)."""

    # Frigate versiyonları arasında yeni alanlar gelebilir
    model_config = ConfigDict(extra="allow")

    id: str
    camera: str
    label: str
    score: float = Field(ge=0.0, le=1.0)
    frame_time: float
    current_zones: list[str] = Field(default_factory=list)
    entered_zones: list[str] = Field(default_factory=list)
    box: Sequence[int] | None = None  # [x, y, w, h]
    has_snapshot: bool = False
    stationary: bool = False


class FrigateEvent(BaseModel):
    """Frigate event wrapper — `frigate/events` topic'inden gelir."""

    model_config = ConfigDict(extra="allow")

    type: Literal["new", "update", "end"]
    before: FrigateObject | None = None
    after: FrigateObject

    @property
    def event_id(self) -> str:
        """Bir tracking session boyunca sabit kalır (new → update → end)."""
        return self.after.id

    @property
    def camera(self) -> str:
        return self.after.camera

    @property
    def label(self) -> str:
        return self.after.label

    @property
    def score(self) -> float:
        return self.after.score

    @property
    def current_zones(self) -> list[str]:
        return self.after.current_zones

    @property
    def is_first_in_zone(self) -> bool:
        """Bu güncellemede obje bir zone'a *yeni* mi girdi?

        `entered_zones`: bu update'te yeni girilen zone(lar) (set difference).
        `current_zones`: o anda içinde olduğu tüm zone(lar).
        """
        return bool(self.after.entered_zones)
