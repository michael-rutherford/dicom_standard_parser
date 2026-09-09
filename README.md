# DICOM Standard Parser

Python ETL scripts that turn published DICOM reference material into queryable SQLite
databases.

**The DICOM standard.** Downloads the DocBook XML sources for Parts 03, 04, 05, 06, 15 and
16 from [dicom.nema.org](http://dicom.nema.org/medical/dicom/current/source/docbook/) and
parses the normative tables — data elements, SOP classes, IODs, modules, macros, UIDs,
character sets, de-identification profiles, templates and context groups — into a single
relational database.

**Private tag dictionaries.** Collects the private-tag dictionaries maintained by several
open-source DICOM projects (GDCM, DCMTK, pydicom, and David Clunie's dciodvfy), normalizes
them into a common schema, and reports where the sources agree and disagree on VR, VM and
attribute name.

The result is a queryable snapshot of a specific DICOM edition — useful for building
dictionaries, validating IOD conformance, driving de-identification tooling, or diffing
one release against another.

---

## Requirements

* Python 3.9+
* Network access to `dicom.nema.org`, `github.com` and `raw.githubusercontent.com`

```powershell
pip install -r requirements.txt
```

`requirements.txt` covers `pandas`, `requests`, `xmltodict` and `openpyxl`. The private-tag
reconciliation script also uses SQLAlchemy:

```powershell
pip install sqlalchemy psycopg2
```

## Configuration

All machine-specific paths live in `config.json` at the repository root, loaded through
[config.py](config.py). `config.json` is gitignored; `config.example.json` is the committed
template.

```powershell
copy config.example.json config.json    # then edit
```

| Key | Meaning |
| --- | --- |
| `data_folder` | Working directory for the parsed database and logs |
| `log_folder` | Where execution logs are written (defaults to `data_folder/logs`) |
| `standard_db` | Filename of the parsed standard database, e.g. `dicom_standard_parsed_2025c.db` |
| `excel_export_path` | Output path for the Excel export (optional) |
| `credentials_file` | Path to a JSON credentials file kept outside the repository |
| `extra_sop_csv` | Optional supplemental SOP class CSV |

The config file's location can be moved with the `DICOM_STANDARD_CONFIG` environment
variable. Scripts reach the loader by putting the repository root on `sys.path`:

```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
```

Machine-specific paths belong in `config.json` with an accessor in `config.py`, rather than
inline in a script.

### Credentials

Database credentials are kept outside the repository. `credentials_file` points at a JSON
file with one entry per deployment:

```json
{
  "tcia":  { "driver": "postgresql+psycopg2", "un": "...", "pw": "...",
             "host": "...", "port": "5432",
             "api_host": "https://...", "api_auth": "..." },
  "aries": { "...": "same keys" }
}
```

`config.credentials()` loads it and `config.db_url(system, database)` assembles a SQLAlchemy
URL. Both are lazy, so nothing needs credentials at import time. Parsing the standard and
scraping the private-tag sources require no credentials at all.

---

## Parsing the standard

```powershell
python standard/parse_dicom_standard.py
```

[standard/parse_dicom_standard.py](standard/parse_dicom_standard.py) fetches each DocBook
part on demand and runs a series of `update_*()` functions, each of which parses one named
table from one part and writes the corresponding database table.

Two extractors do the underlying work:

* `extract_text(elem)` flattens a DocBook element to a string, rendering `olink`/`xref`
  cross-references as `"link text targetptr"`.
* `extract_table_data(root, table_name=..., sect_name=...)`, and its `_with_includes`
  variant, resolve DICOM's `Include Table ...` rows recursively so that inherited rows are
  materialized alongside the table's own.

| Function | Source | Output table(s) |
| --- | --- | --- |
| `update_elements` | Part 06 Table 6-1 | `dicom_element` |
| `update_sop_classes` | Part 04 Table B.5-1 | `dicom_sop_class` |
| `update_deid_profiles` / `update_safe_private` | Part 15 Tables E.1-1a / E.3.10-1 | `dicom_deid_profile`, `dicom_deid_action_code`, `dicom_safe_private` |
| `update_modules` / `update_module_attributes` | Part 03 IOD and module tables | `dicom_iod_module`, `dicom_module`, `dicom_module_attribute` |
| `update_macros` | Part 03 macro tables | `dicom_macro`, `dicom_macro_attribute` |
| `update_uids` / `update_charsets` | Part 06, Part 03 | `dicom_uid`, `dicom_charset` |
| `update_templates_and_context_groups` | Part 16 | `dicom_template`, `dicom_context_group` |
| `update_class_iod_requirements_from_tables` + `_tags` | joins the above | `dicom_class_iod_requirement`, `dicom_class_iod_requirement_tag` |

`main()` runs the full sequence in dependency order, ending with `create_indexes()` and the
derived requirement tables. Each step replaces its output table outright, so steps can be
commented out to refresh only part of the database — provided the order above is respected,
since `dicom_class_iod_requirement*` is derived from the module and macro tables.

A full run downloads six DocBook parts and parses several thousand tables, so expect it to
take a while. Each part is fetched once per process and reused.

### Selecting a DICOM edition

The edition is set by the URLs in the `import_part_*` functions, where `current` is active
and prior editions (`2023e`, `2024a`, `2025a`) are listed alongside it. Point those at the
edition you want and set `standard_db` in `config.json` to a matching filename, so that each
edition lands in its own database.

### Excel export

```powershell
python standard/export_standard_to_excel.py
```

Exports the parsed tables to a workbook. It reads the plural table names
(`dicom_sop_classes`, `dicom_deid_profiles`) used by earlier database snapshots.

---

## Private tag dictionaries

Each source has its own subdirectory under [private_tags/](private_tags/) with a
`<source>_pt_parse.py` that fetches upstream, deduplicates against what is already stored
using a `pt_signature` hash, and inserts into a `<source>_pt` table in the shared database
`private_tags/database/pt_parse.db`. Re-running a scraper picks up only what is new.

```powershell
python private_tags/gdcm/gdcm_pt_parse.py
python private_tags/dcmtk/dcmtk_pt_parse.py
python private_tags/pydicom/pydicom_pt_parse.py
python private_tags/clunie/clunie_pt_parse.py      # see note on inputs below
python private_tags/other/other_pt_parse.py
python private_tags/combine_and_compare.py
```

| Source | Origin |
| --- | --- |
| `gdcm` | GDCM `privatedicts.xml` from GitHub, parsed with `xmltodict` |
| `dcmtk` | DCMTK dictionary source from GitHub |
| `pydicom` | pydicom private dictionary source from GitHub |
| `clunie` | `.tpl` files from a local dciodvfy installation |
| `other` | hand-maintained entries |

The Clunie dictionaries are not published as a single downloadable file. Extract the `.tpl`
files from the dciodvfy `elmdict` folder into `private_tags/clunie/files/` before running
that scraper — see [private_tags/clunie/note.txt](private_tags/clunie/note.txt).

### Reconciliation

[private_tags/combine_and_compare.py](private_tags/combine_and_compare.py) pivots the
per-source tables into a single view and reports on the conflicts between them:

| Table | Contents |
| --- | --- |
| `combined_pt` | one row per tag, one column group per source |
| `agree_pt` / `disagree_pt` | split by whether the sources agree on VR, VM and name |
| `compare_pt` | the combined view compared against a reference knowledge base |
| `tcia_pt_insert` / `tcia_pt_update` | resulting insert and update work queues |

`get_combined_pt_records()` and `get_compare_pt_records()` run entirely against the local
SQLite database. Only `compare_to_tcia()` connects to an external database, and it builds
its URL lazily inside `tcia_db_url()` so the module stays importable without credentials.
Select the steps you want in `main()`.

---

## Implementation notes

* Tags are normalized by stripping the `<>` delimiters and lowercasing. For private tags,
  only the hexadecimal portions are lowercased; the quoted private creator string is
  preserved as written.
* `update_class_requirements()` distributes work across a `ProcessPoolExecutor` using the
  `spawn` start method, so `process_sop_class` stays picklable and receives the parsed XML
  root as an argument.
* Table naming moved from plural to singular (`dicom_sop_class`, `dicom_deid_profile`) in
  the current parser; snapshots produced by earlier versions use the plural form.
* `old/convert_standard.py` is retained for reference only and is superseded by
  `standard/parse_dicom_standard.py`.

## Repository contents

Local configuration, credentials, database snapshots and deployment-specific integration
scripts are excluded by `.gitignore`:

| Excluded | Reason |
| --- | --- |
| `config.json`, `*_pw.json` | machine paths and credentials |
| `posda/` | deployment-specific integration scripts |
| `parsed/` | database snapshots and execution logs |
| `private_tags/database/` | working database populated from a live knowledge base |
| `private_tags/clunie/files/` | `.tpl` inputs from a local dciodvfy installation |
| `.vs/`, `.vscode/`, `*.pyproj.user` | editor state containing absolute paths |

No credentials are committed. Every connection string is assembled at runtime from the
external credentials file, and tracked source contains no hostnames, usernames or absolute
paths.

## Source material

The DICOM standard is published by NEMA and is available at
<https://www.dicomstandard.org/current>; the DocBook XML sources parsed here are served
from <http://dicom.nema.org/medical/dicom/current/source/docbook/>. Private tag dictionaries
are drawn from the GDCM, DCMTK and pydicom projects and from David Clunie's `dicom3tools`,
each under its own upstream license.
