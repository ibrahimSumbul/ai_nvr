"""Disk doluluk izleme + snapshot retention budama — M7.

Enterprise model (bkz. ROADMAP M7, docs/08-operations.md):
  • **Zaman-tabanlı budama**: bridge snapshot store'da `snapshot_retention_days`'ten
    eski dosyalar silinir → disk bizim tarafımızdan unbounded büyümez, hiç dolmaz.
  • **Eşik alarmı**: disk doluluk `disk_warn_threshold_pct` aşınca bir kez Dahua
    external alarm → DMSS push (kamera offline ile aynı yol). Histerezis ile
    flapping önlenir: ancak doluluk (eşik − margin) altına düşünce flag resetlenir.
  • **Grafana paneli**: `disk_status` tablosu canlı doluluk + snapshot boyutunu gösterir.

Ham video FIFO'su (en eskiyi üzerine yazma) **kapsam dışı** — kayıt Dahua NVR'da,
o native ring-buffer'ı kendi yönetir. Burada baskı-altı silme YOK (bkz. tasarım
notu: dolunca-sil aktif olayı silebilir; enterprise disiplini diski hiç doldurmaz).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog

from bridge.config import Settings
from bridge.dahua import DahuaAlarmClient, DahuaAlarmError
from bridge.db import Database

log = structlog.get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class DiskSample:
    """Bir örnekleme turunun ölçümleri."""

    used_pct: float
    used_bytes: int
    total_bytes: int
    snapshot_bytes: int
    snapshot_files: int


@dataclass(frozen=True)
class PruneResult:
    deleted_files: int
    freed_bytes: int


class DiskMonitor:
    """Disk doluluğunu örnekler, eski snapshot'ları budar, eşikte DMSS alarm verir.

    `check()` tek tur: (gerekiyorsa) buda → örnekle → `disk_status` upsert →
    eşik kararı. Periyodik çağrı `_disk_monitor_loop` (main.py) tarafından yapılır.
    """

    def __init__(
        self,
        settings: Settings,
        db: Database,
        snapshot_dir: Path,
        clock: Callable[[], datetime] = _utcnow,
        dahua: DahuaAlarmClient | None = None,
        usage_fn: Callable[[str], tuple[int, int, int]] | None = None,
    ) -> None:
        self._settings = settings
        self._db = db
        self._snapshot_dir = snapshot_dir
        self._clock = clock
        self._dahua = dahua
        # İzlenen mount = snapshot dizininin bulunduğu dosya sistemi. Container'da
        # bu ainvr-media volume → host diski (asıl dolma riski olan yer).
        self._mount = str(snapshot_dir)
        self._warn_pct = settings.disk_warn_threshold_pct
        self._recover_pct = max(0.0, self._warn_pct - settings.disk_recover_margin_pct)
        self._retention = timedelta(days=settings.snapshot_retention_days)
        self._prune_interval_s = settings.snapshot_prune_interval_s
        self._channel = settings.dahua_alarm_channel
        self._usage_fn = usage_fn or _disk_usage
        self._last_prune_at: datetime | None = None
        self._last_pruned_files = 0

    @property
    def mount(self) -> str:
        return self._mount

    async def check(self) -> None:
        """Bir tur: buda (gerekiyorsa) → örnekle → upsert → eşik kararı."""
        now = self._clock()

        if self._due_for_prune(now):
            result = await asyncio.to_thread(self._prune_snapshots, now)
            self._last_prune_at = now
            self._last_pruned_files = result.deleted_files
            if result.deleted_files:
                log.info(
                    "disk.snapshots_pruned",
                    files=result.deleted_files,
                    freed_mb=round(result.freed_bytes / 1_048_576, 1),
                    retention_days=self._settings.snapshot_retention_days,
                )

        sample = await asyncio.to_thread(self._sample)
        await self._db.upsert_disk_status(
            self._mount,
            now,
            sample.used_pct,
            sample.used_bytes,
            sample.total_bytes,
            sample.snapshot_bytes,
            sample.snapshot_files,
            self._last_prune_at,
            self._last_pruned_files,
        )
        await self._handle_threshold(sample.used_pct)

    def _due_for_prune(self, now: datetime) -> bool:
        # Throttle yalnız bellekte (_last_prune_at). Restart'ta None → ilk check'te
        # bir kez budanır; prune idempotent + correctness-safe olduğu için bu kasıtlı
        # ve zararsız (boot başına tek ekstra walk; alarm flag'i ise DB'de restart-safe).
        if self._last_prune_at is None:
            return True
        return (now - self._last_prune_at).total_seconds() >= self._prune_interval_s

    def _sample(self) -> DiskSample:
        """Disk kullanımı + snapshot dizini boyutu (blocking → to_thread'den çağrılır).

        Doluluk yüzdesi `df Use%` ile aynı tabanda: `used/(used+free)` — fiziksel
        `total` değil, kullanılabilir alan payda (root-rezerve bloklar hariç). Böylece
        eşik, operatörün df/Grafana'da gördüğü değerle tutarlı olur (ext4 %5 rezerve
        nedeniyle total tabanı ~%5 düşük doluluk gösterirdi).
        """
        total, used, free = self._usage_fn(self._mount)
        denom = used + free
        pct = (100.0 * used / denom) if denom > 0 else 0.0
        snap_bytes, snap_files = _dir_size(self._snapshot_dir)
        return DiskSample(
            used_pct=round(pct, 2),
            used_bytes=used,
            total_bytes=total,
            snapshot_bytes=snap_bytes,
            snapshot_files=snap_files,
        )

    def _prune_snapshots(self, now: datetime) -> PruneResult:
        """Retention'dan eski snapshot dosyalarını sil + boşalan dizinleri temizle.

        Blocking → to_thread. `topdown=False`: alt dizinler önce işlenir, böylece
        dosyaları silinip boşalan tarih dizini (`YYYY-MM-DD/`) aynı turda kaldırılır
        → uzun ömürlü kurulumda boş dizin/inode birikmez. Yazıcı `mkdir(parents=True)`
        ile yeniden oluşturduğu için kaldırma güvenli; kök snapshot dizini korunur.
        """
        cutoff = (now - self._retention).timestamp()
        root_dir = os.path.normpath(str(self._snapshot_dir))
        deleted = 0
        freed = 0
        for root, _dirs, files in os.walk(self._snapshot_dir, topdown=False):
            for name in files:
                fp = os.path.join(root, name)
                try:
                    stat = os.stat(fp)
                    if stat.st_mtime < cutoff:
                        size = stat.st_size
                        os.unlink(fp)
                        deleted += 1
                        freed += size
                except OSError as exc:  # dosya yarışı / izin — atla, turu bozma
                    log.warning("disk.prune_unlink_failed", path=fp, error=str(exc))
            # Boşalan alt dizini kaldır (kök hariç). os.rmdir yalnız boş dizinde
            # başarılı; dolu dizin / yazıcı yarışı → OSError, zararsızca atla.
            if os.path.normpath(root) != root_dir:
                with contextlib.suppress(OSError):
                    os.rmdir(root)
        return PruneResult(deleted_files=deleted, freed_bytes=freed)

    async def _handle_threshold(self, used_pct: float) -> None:
        """Eşik aşıldıysa tek-uyarı DMSS alarm; histerezis altına düşünce reset."""
        status = await self._db.get_disk_status(self._mount)
        alert_sent = bool(status["alert_sent"]) if status else False

        if used_pct >= self._warn_pct and not alert_sent:
            await self._db.set_disk_alert_sent(self._mount, True)
            log.warning(
                "disk.threshold_exceeded",
                used_pct=used_pct,
                threshold_pct=self._warn_pct,
                mount=self._mount,
            )
            await self._emit_disk_alarm(used_pct)
        elif used_pct < self._recover_pct and alert_sent:
            await self._db.set_disk_alert_sent(self._mount, False)
            log.info("disk.recovered", used_pct=used_pct, mount=self._mount)

    async def _emit_disk_alarm(self, used_pct: float) -> None:
        """Disk doluluk eşiği → Dahua external alarm → DMSS push (best-effort)."""
        if self._dahua is None:
            return
        try:
            await self._dahua.trigger_external_alarm(
                channel=self._channel,
                event_type="disk_full",
                description=f"Disk doluluk %{used_pct:.0f} (esik %{self._warn_pct:.0f})",
            )
        except DahuaAlarmError as exc:
            log.warning("disk.alarm_failed", error=str(exc))
            return
        log.info("disk.alarm_sent", used_pct=used_pct, channel=self._channel)


def _disk_usage(path: str) -> tuple[int, int, int]:
    """`(total, used, free)` bytes. Path yoksa en yakın var olan üst dizine düşer.

    `free` = kullanılabilir alan (POSIX'te f_bavail, root-rezerve bloklar HARİÇ);
    doluluk yüzdesi `used/(used+free)` ile `df Use%` tabanına oturur.
    """
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    usage = shutil.disk_usage(str(p))
    return usage.total, usage.used, usage.free


def _dir_size(path: Path) -> tuple[int, int]:
    """`(toplam_bytes, dosya_sayısı)` — dizin yoksa (0, 0)."""
    total_bytes = 0
    file_count = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total_bytes += os.stat(os.path.join(root, name)).st_size
                file_count += 1
            except OSError:
                continue
    return total_bytes, file_count
