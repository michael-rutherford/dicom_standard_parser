# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A set of standalone Python ETL scripts (no package, no tests, no build) that:

1. Scrape the DICOM standard from NEMA's DocBook XML into a local SQLite database.
2. Scrape private-tag dictionaries from several open-source projects into a second SQLite database, reconcile them, and diff against TCIA's knowledge base.
3. Push both result sets into the Posda/TCIA PostgreSQL databases (`dicom_dd`, `private_tag_kb`).

Each script is run individually and decides for itself which steps to perform. There is no orchestrator.

**The `posda/` and `parsed/` directories are gitignored and excluded from the public repository** (see "Public repository boundary" below). Stage 3 below only applies when working in the full private tree.

## Configuration

All machine-specific paths live in `config.json` at the repo root, loaded through [config.py](config.py). It is gitignored; `config.example.json` is the committed template. Override its location with the `DICOM_STANDARD_CONFIG` environment variable.

Never reintroduce a hardcoded absolute path — add a key to `config.json` and an accessor to `config.py` instead. Scripts reach the loader with:

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
```

Database credentials are *not* in `config.json`. It holds `credentials_file`, a path to a JSON file kept outside the repo with one entry per Posda deployment (`tcia`, `aries`), each carrying `driver`/`un`/`pw`/`host`/`port` plus `api_host`/`api_auth`. `config.credentials()` loads it and `config.db_url(system, database)` builds a SQLAlchemy URL. Both are lazy — nothing needs credentials at import time.

## Commands

```powershell
pip install -r requirements.txt
# Not in requirements.txt but imported by several scripts:
pip install sqlalchemy psycopg2
# Stage 3 (private tree) only:
pip install --no-cache-dir git+https://github.com/michael-rutherford/posda_utils.git

# One-time setup
copy config.example.json config.json    # then edit

# Stage 1 — parse the standard into SQLite (edit main() first, see below)
python standard/parse_dicom_standard.py

# Stage 2 — private tag sources -> private_tags/database/pt_parse.db
python private_tags/clunie/clunie_pt_parse.py      # needs .tpl files extracted first
python private_tags/dcmtk/dcmtk_pt_parse.py
python private_tags/gdcm/gdcm_pt_parse.py
python private_tags/pydicom/pydicom_pt_parse.py
python private_tags/other/other_pt_parse.py
python private_tags/combine_and_compare.py

# Stage 3 — push to Posda/TCIA Postgres (PRIVATE TREE ONLY, posda/ is gitignored)
python posda/copy_standard_to_posda2.py            # current standard -> dicom_dd
python posda/update_posda_dd.py                    # incremental element diff -> dicom_dd
python posda/update_posda_ptkb.py                  # pt inserts -> private_tag_kb
python posda/output_posda_ptkb.py                  # pull PT KB back into the SQLite db

# Ad-hoc export
python standard/export_standard_to_excel.py
```

There is no test suite, linter, or build step.

## Architecture

### Stage 1: `standard/parse_dicom_standard.py` (~1900 lines, the core of the repo)

Downloads DocBook XML for DICOM parts 03, 04, 05, 06, 15, 16 from `dicom.nema.org` into module-level globals (`part_03_root`, etc.). Each part is fetched lazily by an `import_part_NN()` call guarded by `if not part_NN_root`.

Everything is built on two extractors:

- `extract_text(elem)` — flattens a DocBook element to a string, rendering `olink`/`xref` as `"link text targetptr"` (this is why downstream code strips `<...>` from tags and section ids).
- `extract_table_data(root, table_name=..., sect_name=...)` and its `_with_includes` variant, which resolve DICOM's `Include Table ...` rows recursively.

On top of those sit `update_*()` functions, each of which parses one named table from one part and writes a whole table with `to_sql(..., if_exists='replace')`:

| function | source | output table |
| --- | --- | --- |
| `update_elements` | Part 06 Table 6-1 | `dicom_element` |
| `update_sop_classes` | Part 04 Table B.5-1 | `dicom_sop_class` |
| `update_deid_profiles` / `update_safe_private` | Part 15 Table E.1-1a / E.3.10-1 | `dicom_deid_profile`, `dicom_deid_action_code`, `dicom_safe_private` |
| `update_modules` / `update_module_attributes` | Part 03 IOD + module tables | `dicom_iod_module`, `dicom_module`, `dicom_module_attribute` |
| `update_macros` | Part 03 macro tables | `dicom_macro`, `dicom_macro_attribute` |
| `update_uids` / `update_charsets` | Part 06, Part 03 | `dicom_uid`, `dicom_charset` |
| `update_templates_and_context_groups` | Part 16 | `dicom_template`, `dicom_context_group` |
| `update_class_iod_requirements_from_tables` + `_tags` | joins the above | `dicom_class_iod_requirement`, `..._tag` |

**`main()` is a checklist of commented-out calls.** To re-run a stage you uncomment the relevant lines. The dependency order is the table order above — `dicom_class_iod_requirement*` is derived from modules/macros and must be rebuilt after them.

**Per-release changes touch two places.** The output database name is `standard_db` in `config.json`; the edition being parsed is pinned in the `import_part_*` URLs, where `current` is active and prior editions (`2023e`, `2024a`, `2025a`) sit commented out. Change both together or you will silently overwrite one edition's database with another's contents.

`update_class_requirements()` uses a `ProcessPoolExecutor` with `multiprocessing.set_start_method("spawn")`, so `process_sop_class` must stay picklable and take the XML root as an argument rather than reading the globals.

### Stage 2: `private_tags/`

One subdirectory per source, each with a `<source>_pt_parse.py` that fetches upstream and writes `<source>_pt` into the shared `private_tags/database/pt_parse.db` (`insert_in_batches` at batch size 500):

- `gdcm` — GDCM `privatedicts.xml` from GitHub (via `xmltodict`)
- `dcmtk`, `pydicom` — dictionary source files from GitHub
- `clunie` — **manual step**: extract `.tpl` files from the dciodvfy `elmdict` folder into `private_tags/clunie/files/` first (see `note.txt`), then run
- `other` — miscellaneous hand-maintained entries

`combine_and_compare.py` then produces `combined_pt`, `compare_pt`, `agree_pt`/`disagree_pt` (where sources conflict on VR/VM/name), and the `tcia_pt_insert` / `tcia_pt_update` work queues that `posda/update_posda_ptkb.py` consumes.

This is the one published file that touches Posda, so it is deliberately split: `get_combined_pt_records()` and `get_compare_pt_records()` run entirely against the in-repo SQLite database and need no credentials, while only `compare_to_tcia()` reaches a live `private_tag_kb`. Its connection URL is built lazily by `tcia_db_url()` — **keep it that way**; hoisting it back to module scope would make the whole file unimportable without credentials. `write_to_add_pt()` is dead code (its callers no longer exist) and predates the current credentials layout.

### Stage 3: `posda/`

- `copy_standard_to_posda2.py` is the current full-copy script (`copy_standard_to_posda.py` is its predecessor). It reads every `dicom_*` table out of the parsed SQLite db into globals via `fill_std_dfs()`, normalizes in `prep_std_dfs()`, bulk-replaces into Posda `dicom_dd` in `insert_std_dfs()`, then `create_indexes()` / `create_views()`. Like `parse_dicom_standard.main()`, **the `bulk_insert` calls in `insert_std_dfs()` are selectively commented out** — only the uncommented ones run.
- `update_posda_dd.py` is the incremental alternative: diffs `dicom_dictionary` against the live `dicom_element` table and issues targeted INSERT/UPDATE.
- `output_posda_ptkb.py` reads the TCIA and ARIES `pt` tables, unions them with a `system` column, and maps free-text dispositions to canonical codes via the `disp_replace` dict (`d`/`dd`/`delete`/`ds` → `X`, `h` → `U`, `k` → `K`, `o`/`oi` → `C`).

### Conventions and gotchas

- Scripts under `posda/` still read credentials directly rather than through `config.py`. They are gitignored, so this was left alone; if that ever changes, route them through `config.credentials()` first.
- Posda scripts go through `posda_utils` (`PosdaDB`, `PosdaAPI`, `DBManager`) rather than raw SQLAlchemy.
- **Tag normalization is repeated everywhere**: strip `<>` from `tag`, lowercase it, and for private tags lowercase only the hex portions while preserving the quoted creator — see `lowercase_hex_private()`, which is duplicated in both `copy_standard_to_posda*.py`.
- Table names changed between releases. Older snapshots use plurals (`dicom_sop_classes`, `dicom_deid_profiles`); the current parser writes singulars (`dicom_sop_class`, `dicom_deid_profile`). `export_standard_to_excel.py` still expects the plural form and will not run against a current database.
- `old/convert_standard.py` is superseded by `standard/parse_dicom_standard.py` — don't extend it. Its `data_folder` is intentionally blank.

## Public repository boundary

This tree is published with the Posda/TCIA integration removed. `.gitignore` enforces it; when adding files, keep to the same lines:

| Excluded | Why |
| --- | --- |
| `config.json`, `*_pw.json` | machine paths and credentials |
| `posda/` | infrastructure-specific integration scripts |
| `parsed/` | database snapshots, logs, and a dump of TCIA's private tag KB |
| `private_tags/database/` | contains data pulled from live TCIA/ARIES `private_tag_kb`, including the `tcia_pt_insert`/`tcia_pt_update` queues |
| `private_tags/clunie/files/` | `.tpl` files from a local dciodvfy install |
| `.vs/`, `.vscode/`, `*.pyproj.user` | editor state embedding absolute paths |

No credentials have ever been committed — every connection string is assembled at runtime from the external credentials file. Keep it that way: no hostnames, usernames, or absolute paths in tracked source.
