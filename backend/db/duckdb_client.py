"""DuckDB read-only client — ported from Quiver as-is (plan.md §13).

The feature store data model stays DuckDB/Parquet, unchanged. This is the
embedded analytical client used by the Finance module and the web backend.
"""

from pathlib import Path
import os
from contextlib import contextmanager

import duckdb

_DEFAULT_DB = os.environ.get(
    "QUIVER_DUCKDB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "metadata" / "quiver.duckdb"),
)


class DuckDBClient:
    """Lightweight embedded DuckDB interface for analytical time series data.

    Supports both read-write (scheduler/pipeline) and read-only (API server)
    connections to avoid write-lock conflicts when both processes access the
    same .duckdb file.

    Connections are transient: each operation opens a fresh connection and
    closes it on exit. A long-lived process (API) must not pin the file lock,
    otherwise the worker and test processes can no longer open the same file
    (DuckDB allows one read-write holder at a time). Use `session()` for
    multi-statement writes so the lock is held only for the duration of the
    operation.
    """

    def __init__(self, db_path: str = _DEFAULT_DB, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only

    def _open(self):
        # Create the parent directory so a fresh checkout can initialize the
        # feature store without manual setup (start.sh / first job run).
        parent = Path(self.db_path).parent
        if not self.read_only and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        return duckdb.connect(self.db_path, read_only=self.read_only)

    def get_conn(self):
        """Open a fresh connection (caller owns closing it)."""
        return self._open()

    def session(self):
        """Context manager yielding a fresh connection closed on exit."""

        @contextmanager
        def _session():
            conn = self._open()
            try:
                yield conn
            finally:
                conn.close()

        return _session()

    def execute(self, query: str, parameters=None):
        conn = self._open()
        try:
            if parameters:
                return conn.execute(query, parameters)
            return conn.execute(query)
        finally:
            conn.close()

    def df(self, query: str, parameters=None):
        """Execute and return results as a Pandas DataFrame."""
        conn = self._open()
        try:
            res = conn.execute(query, parameters) if parameters else conn.execute(query)
            return res.df()
        finally:
            conn.close()

    def close(self) -> None:
        """No-op for API compatibility.

        Connections are transient (opened/closed per operation), so there is no
        cached connection to drop. Kept so callers that used to reset the shared
        connection (e.g. tests switching to a temporary DuckDB path) keep working.
        """


# Global default client (read-write for pipeline/table creation).
client = DuckDBClient()

_ro_client_instance = None


def get_read_only_client() -> DuckDBClient:
    """Return a cached read-only client for the API server."""
    global _ro_client_instance
    if _ro_client_instance is None:
        _ro_client_instance = DuckDBClient(read_only=True)
    return _ro_client_instance
