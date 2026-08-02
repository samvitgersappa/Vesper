"""DuckDB read-only client — ported from Quiver as-is (plan.md §13).

The feature store data model stays DuckDB/Parquet, unchanged. This is the
embedded analytical client used by the Finance module and the web backend.
"""

from pathlib import Path
import os

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
    """

    def __init__(self, db_path: str = _DEFAULT_DB, read_only: bool = False):
        self.db_path = db_path
        self.read_only = read_only
        self._conn = None

    def get_conn(self):
        if self._conn is None:
            # Create the parent directory so a fresh checkout can initialize the
            # feature store without manual setup (start.sh / first job run).
            parent = Path(self.db_path).parent
            if not self.read_only and not parent.exists():
                parent.mkdir(parents=True, exist_ok=True)
            self._conn = duckdb.connect(self.db_path, read_only=self.read_only)
        return self._conn

    def execute(self, query: str, parameters=None):
        conn = self.get_conn()
        if parameters:
            return conn.execute(query, parameters)
        return conn.execute(query)

    def df(self, query: str, parameters=None):
        """Execute and return results as a Pandas DataFrame."""
        return self.execute(query, parameters).df()

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# Global default client (read-write for pipeline/table creation).
client = DuckDBClient()

_ro_client_instance = None


def get_read_only_client() -> DuckDBClient:
    """Return a cached read-only client for the API server."""
    global _ro_client_instance
    if _ro_client_instance is None:
        _ro_client_instance = DuckDBClient(read_only=True)
    return _ro_client_instance
