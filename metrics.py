"""Prometheus metrics for the API.

Two kinds of metrics live here:

* Event counters (uploads, downloads, logins, ...) incremented by the routers.
* A collector that reads current totals from the database on every scrape,
  so the numbers are always correct even after a restart.

HTTP request metrics (rate, latency, status codes) come from
prometheus-fastapi-instrumentator in main.py.
"""

import logging

from prometheus_client import REGISTRY, Counter
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import func, select

from database import SessionLocal
from models import FileRecord, Folder, User

log = logging.getLogger(__name__)

UPLOADS = Counter(
    "pcs_file_uploads_total",
    "Upload attempts, by result",
    ["result"],
)
UPLOAD_BYTES = Counter(
    "pcs_file_upload_bytes_total",
    "Bytes stored by successful uploads",
)
DOWNLOADS = Counter(
    "pcs_file_downloads_total",
    "Presigned download URLs issued, by kind (redirect or share_link)",
    ["kind"],
)
DELETES = Counter(
    "pcs_file_deletes_total",
    "Files deleted",
)
LOGINS = Counter(
    "pcs_login_attempts_total",
    "Login attempts, by result",
    ["result"],
)


class StorageCollector(Collector):
    """Reads storage and account totals from PostgreSQL at scrape time."""

    def describe(self):
        # Returning nothing stops prometheus_client from calling collect()
        # (and querying the database) when the collector is registered.
        return []

    def collect(self):
        db_up = GaugeMetricFamily(
            "pcs_metrics_db_up", "1 if the metrics collector could query the database"
        )
        try:
            with SessionLocal() as db:
                files, stored = db.execute(
                    select(func.count(FileRecord.id), func.coalesce(func.sum(FileRecord.size), 0))
                ).one()
                users = db.execute(
                    select(User.is_active, func.count(User.id)).group_by(User.is_active)
                ).all()
                folders = db.execute(
                    select(Folder.is_shared, func.count(Folder.id)).group_by(Folder.is_shared)
                ).all()
                per_user = db.execute(
                    select(
                        User.username,
                        User.quota_bytes,
                        func.coalesce(func.sum(FileRecord.size), 0),
                    )
                    .outerjoin(FileRecord, FileRecord.owner_id == User.id)
                    .where(User.is_active.is_(True))
                    .group_by(User.id)
                ).all()
        except Exception:
            log.exception("metrics collector could not query the database")
            db_up.add_metric([], 0)
            yield db_up
            return

        db_up.add_metric([], 1)
        yield db_up

        yield GaugeMetricFamily("pcs_files", "Files stored", value=int(files))
        yield GaugeMetricFamily("pcs_stored_bytes", "Total size of stored files", value=int(stored))

        user_gauge = GaugeMetricFamily("pcs_users", "Accounts, by status", labels=["status"])
        counts = {bool(active): n for active, n in users}
        user_gauge.add_metric(["active"], counts.get(True, 0))
        user_gauge.add_metric(["inactive"], counts.get(False, 0))
        yield user_gauge

        folder_gauge = GaugeMetricFamily("pcs_folders", "Folders, by type", labels=["type"])
        folder_counts = {bool(shared): n for shared, n in folders}
        folder_gauge.add_metric(["shared"], folder_counts.get(True, 0))
        folder_gauge.add_metric(["private"], folder_counts.get(False, 0))
        yield folder_gauge

        used = GaugeMetricFamily(
            "pcs_user_used_bytes", "Bytes used per active user", labels=["username"]
        )
        quota = GaugeMetricFamily(
            "pcs_user_quota_bytes", "Quota per active user", labels=["username"]
        )
        for username, quota_bytes, used_bytes in per_user:
            used.add_metric([username], int(used_bytes))
            quota.add_metric([username], int(quota_bytes))
        yield used
        yield quota


_collector_registered = False


def register_storage_collector() -> None:
    global _collector_registered
    if not _collector_registered:
        REGISTRY.register(StorageCollector())
        _collector_registered = True
