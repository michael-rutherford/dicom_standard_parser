"""
Central configuration for the DICOM standard parsing scripts.

Every machine-specific path lives in `config.json` at the repo root, which is
gitignored. Copy `config.example.json` to `config.json` and edit it before
running anything. The location can be overridden with the
DICOM_STANDARD_CONFIG environment variable.

Database credentials are NOT stored here. `credentials_file` points at a
separate JSON file kept outside the repo; see `credentials()` below for the
expected shape.
"""

import json
import os

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.environ.get(
    'DICOM_STANDARD_CONFIG',
    os.path.join(REPO_ROOT, 'config.json')
)

_config = None
_credentials = None


def get_config():
    """Load and cache config.json."""
    global _config
    if _config is None:
        if not os.path.exists(CONFIG_PATH):
            raise FileNotFoundError(
                f"No config file at {CONFIG_PATH}. "
                f"Copy config.example.json to config.json and fill it in, "
                f"or set DICOM_STANDARD_CONFIG to point elsewhere."
            )
        with open(CONFIG_PATH) as f:
            _config = json.load(f)
    return _config


def _require(key):
    value = get_config().get(key)
    if not value:
        raise KeyError(f"'{key}' is not set in {CONFIG_PATH}")
    return value


def data_folder():
    """Working directory for parsed databases and logs."""
    return _require('data_folder')


def log_folder():
    """Where initialize_logging() writes execution logs."""
    return get_config().get('log_folder') or os.path.join(data_folder(), 'logs')


def standard_db_path():
    """Full path to the parsed DICOM standard SQLite database."""
    return os.path.join(data_folder(), _require('standard_db'))


def pt_parse_db_path():
    """Full path to the private-tag parsing SQLite database (in-repo)."""
    return os.path.join(REPO_ROOT, 'private_tags', 'database', 'pt_parse.db')


def excel_export_path():
    """Output path for export_standard_to_excel.py."""
    return get_config().get('excel_export_path') or os.path.join(
        data_folder(), 'dicom_standard_parsed.xlsx'
    )


def credentials():
    """
    Load and cache the credentials file referenced by `credentials_file`.

    Expected shape -- one entry per Posda deployment:

        {
          "tcia": {
            "driver": "postgresql+psycopg2",
            "un": "...", "pw": "...",
            "host": "...", "port": "5432",
            "api_host": "https://...", "api_auth": "..."
          },
          "aries": { ... same keys ... }
        }

    Only `posda/` and `private_tags/combine_and_compare.py` need this; the
    standard parser and the per-source private-tag scrapers do not.
    """
    global _credentials
    if _credentials is None:
        path = _require('credentials_file')
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Credentials file not found at {path} "
                f"(set by 'credentials_file' in {CONFIG_PATH})"
            )
        with open(path) as f:
            _credentials = json.load(f)
    return _credentials


def db_url(system, database):
    """Build a SQLAlchemy URL for a Posda database, e.g. db_url('tcia', 'dicom_dd')."""
    info = credentials()[system]
    return (
        f"{info['driver']}://{info['un']}:{info['pw']}"
        f"@{info['host']}:{info['port']}/{database}"
    )
