#!/usr/bin/env python3
import ast
import requests
import pandas as pd
import os
import sys
import logging
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.exc import SQLAlchemyError
import re
import psycopg2
import json

from sqlalchemy.sql.operators import endswith_op


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# The local reconciliation steps (get_combined_pt_records, get_compare_pt_records)
# run entirely against the in-repo SQLite database and need no credentials.
# Only compare_to_tcia() reaches out to a live Posda private_tag_kb, so its
# connection URL is built lazily rather than at import time.
pt_parse_db_url = f"sqlite:///{config.pt_parse_db_path()}"


def tcia_db_url():
    return config.db_url('tcia', 'private_tag_kb')


def aries_db_url():
    return config.db_url('aries', 'private_tag_kb')

def split_camel_case_string(text):
    if not isinstance(text, str):
        return text
    if ' ' in text:
        return text  # already contains spaces, skip splitting

    return re.sub(
        r'(?<=[a-z])(?=[A-Z])|'         # lower → UPPER
        r'(?<=[A-Z])(?=[A-Z][a-z])|'    # ACRONYM → CapitalWord
        r'(?<=[A-Za-z])(?=\d)|'         # Letter → Digit
        r'(?<=\d)(?=[A-Z])',            # Digit → Uppercase letter
        ' ',
        text
    )

def get_combined_pt_records():
    engine = create_engine(pt_parse_db_url, future=True)
    with engine.begin() as conn:
        sources = {
            'clunie_pt': 'cl',
            'gdcm_pt': 'gd',
            'pydicom_pt': 'py',
            'dcmtk_pt': 'dc'
        }

        dfs = []
        for table, prefix in sources.items():
            df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            df["pt_group"] = df["pt_group"].astype(str)
            df["pt_element"] = df["pt_element"].astype(str)            
            df['source'] = prefix
            dfs.append(df)

        combined_df = pd.concat(dfs, ignore_index=True)

        print(f"Combined {len(combined_df)} before deduplication.")
        combined_df.drop_duplicates(inplace=True)
        print(f"Combined {len(combined_df)} after deduplication.")

        shared_keys = ['pt_signature', 'pt_short_signature', 'pt_owner', 'pt_group', 'pt_element']
        pivot_fields = ['pt_consensus_vr', 'pt_consensus_vm', 'pt_consensus_name']

        melted = combined_df[shared_keys + pivot_fields + ['source']]

        wide_df = melted.melt(id_vars=shared_keys + ['source'], value_vars=pivot_fields)
        wide_df['variable'] = wide_df['source'] + '_' + wide_df['variable']
        pivoted = wide_df.pivot_table(
            index=shared_keys,
            columns='variable',
            values='value',
            aggfunc='first'
        ).reset_index()

        pivoted.columns.name = None

        for prefix in ['cl', 'gd', 'py', 'dc']:
            cols = [f"{prefix}_pt_consensus_vr", f"{prefix}_pt_consensus_vm", f"{prefix}_pt_consensus_name"]
            pivoted[f"{prefix}_exist"] = pivoted[cols].notna().any(axis=1)

        for col in pivoted.columns:
            if col.endswith('_pt_consensus_name'):
                pivoted[col] = pivoted[col].apply(
                    lambda name: (
                        "Unknown" if isinstance(name, str) and (
                            "?" in name or
                            name.strip() in ("", "Unknown", "\\N", "OBSOLETE") or
                            name.strip().lower().startswith("<internal")
                        ) else
                        split_camel_case_string(name.strip()) if isinstance(name, str) else
                        None
                    )
                )

        def compute_diff_flag(df, field):
            diffs = []
            for i, row in df.iterrows():
                values = []
                for src in ['cl', 'gd', 'py', 'dc']:
                    if row[f"{src}_exist"]:
                        val = row[f"{src}_pt_consensus_{field}"]
                        values.append(val)
                diffs.append(len(set(values)) > 1)
            return pd.Series(diffs, index=df.index)

        pivoted["name_diff"] = compute_diff_flag(pivoted, "name")
        pivoted["vm_diff"] = compute_diff_flag(pivoted, "vm")
        pivoted["vr_diff"] = compute_diff_flag(pivoted, "vr")

        # Reorder columns
        base_cols = ["pt_signature", "pt_owner", "pt_group", "pt_element"]
        diff_flags = ["name_diff", "vm_diff", "vr_diff"]
        vr_cols = [f"{src}_pt_consensus_vr" for src in ['cl', 'gd', 'py', 'dc']]
        vm_cols = [f"{src}_pt_consensus_vm" for src in ['cl', 'gd', 'py', 'dc']]
        name_cols = [f"{src}_pt_consensus_name" for src in ['cl', 'gd', 'py', 'dc']]
        exist_flags = [f"{src}_exist" for src in ['cl', 'gd', 'py', 'dc']]

        col_order = base_cols + diff_flags + vr_cols + vm_cols + name_cols + exist_flags
        pivoted = pivoted[col_order]
        
        disagree_df = pivoted[pivoted[['name_diff', 'vm_diff', 'vr_diff']].any(axis=1)].copy()
        agree_df = pivoted[~pivoted.index.isin(disagree_df.index)].copy()

        print(f"Writing {len(pivoted)} Pivot Records.")
        pivoted.to_sql('combined_pt', conn, if_exists='replace', index=False)
        
        print(f"Writing {len(agree_df)} Agree Records.")
        agree_df.to_sql('agree_pt', conn, if_exists='replace', index=False)
        
        print(f"Writing {len(disagree_df)} Disagree Records.")
        disagree_df.to_sql('disagree_pt', conn, if_exists='replace', index=False)        


    return None

def get_compare_pt_records():
    engine = create_engine(pt_parse_db_url, future=True)
    
    agree_sql = "SELECT * FROM agree_pt"
    disagree_sql = "SELECT * FROM disagree_pt"

    def pick_value_with_flag(row, field_prefix):
        for source in ['cl', 'gd', 'py', 'dc']:
            if row.get(f"{source}_exist") and pd.notnull(row.get(f"{source}_{field_prefix}")):
                return row[f"{source}_{field_prefix}"]
        return None

    # Agreement Records
    with engine.begin() as conn:
        agree_df = pd.read_sql(text(agree_sql), conn)

        compare_agree_df = agree_df[["pt_signature", "pt_owner", "pt_group", "pt_element"]].copy()

        compare_agree_df["pt_consensus_vr"] = agree_df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_vr"), axis=1)
        compare_agree_df["pt_consensus_vm"] = agree_df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_vm"), axis=1)
        compare_agree_df["pt_consensus_name"] = agree_df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_name"), axis=1)

        compare_agree_df = compare_agree_df.dropna(subset=["pt_consensus_vr", "pt_consensus_vm", "pt_consensus_name"])

        compare_agree_df.to_sql("compare_pt", conn, if_exists="replace", index=False)

        print(f"Inserted {len(compare_agree_df)} agreement records into compare_pt.")

    # Disagreement Records
    with engine.begin() as conn:
        disagree_df = pd.read_sql(text(disagree_sql), conn)

        compare_disagree_df = disagree_df[["pt_signature", "pt_owner", "pt_group", "pt_element"]].copy()

        compare_disagree_df["pt_consensus_vr"] = disagree_df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_vr"), axis=1)
        compare_disagree_df["pt_consensus_vm"] = disagree_df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_vm"), axis=1)
        compare_disagree_df["pt_consensus_name"] = disagree_df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_name"), axis=1)

        compare_disagree_df = compare_disagree_df.dropna(subset=["pt_consensus_vr", "pt_consensus_vm", "pt_consensus_name"])

        compare_disagree_df.to_sql("compare_pt", conn, if_exists="append", index=False)

        print(f"Inserted {len(compare_disagree_df)} disagreement records into compare_pt.")

def compare_to_tcia():
    tcia_engine = create_engine(tcia_db_url(), future=True)
    tcia_pt_df = pd.read_sql_query("SELECT * FROM pt", tcia_engine)

    parse_engine = create_engine(pt_parse_db_url, future=True)
    with parse_engine.begin() as parse_conn:
        parse_pt_df = pd.read_sql_query("SELECT * FROM compare_pt", parse_conn)

        # Normalize pt_signature for comparison
        tcia_signatures = set(tcia_pt_df["pt_signature"])

        # INSERT candidates: in parse but not in TCIA
        insert_df = parse_pt_df[~parse_pt_df["pt_signature"].isin(tcia_signatures)].copy()
        insert_df.to_sql("tcia_pt_insert", parse_conn, if_exists="replace", index=False)
        print(f"Inserted {len(insert_df)} new entries into tcia_pt_insert.")

        # UPDATE candidates: signatures in both
        shared_df = parse_pt_df[parse_pt_df["pt_signature"].isin(tcia_signatures)].copy()
        tcia_lookup = tcia_pt_df.set_index("pt_signature")

        # Only compare fields in parse_pt_df (TCIA may have more)
        compare_fields = [col for col in parse_pt_df.columns if col != "pt_signature"]

        updates = []
        for _, row in shared_df.iterrows():
            sig = row["pt_signature"]
            tcia_row = tcia_lookup.loc[sig]

            diff = False
            diffs = {"pt_signature":sig}
            diff_flag = {}
            for col in compare_fields:
                parse_val = row[col]
                tcia_val = tcia_row[col] if col in tcia_row else None

                diffs[f"{col}_parse"] = parse_val
                diffs[f"{col}_tcia"] = tcia_val

                if pd.isna(parse_val) and pd.isna(tcia_val):
                    continue
                if parse_val != tcia_val:
                    diff = True
                    diff_flag[f"vr_diff"] = True if col.endswith("vr") else False
                    diff_flag[f"vm_diff"] = True if col.endswith("vm") else False
                    diff_flag[f"name_diff"] = True if col.endswith("name") else False
                    diff_flag[f"pt_consensus_disposition"] = tcia_row["pt_consensus_disposition"]
            if diff == True:
                diffs.update(diff_flag)
                updates.append(diffs)

        if updates:
            update_df = pd.DataFrame(updates)
            update_df.to_sql("tcia_pt_update", parse_conn, if_exists="replace", index=False)
            print(f"Inserted {len(update_df)} update entries into tcia_pt_update.")
        else:
            print("No updates required.")

def write_to_add_pt(conn, new_records_df):
    """
    Write the new records to the add_pt table.
    """
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS add_pt;")
        # Create table using the columns of new_records_df
        col_defs = ", ".join(f"{col} TEXT" for col in new_records_df.columns)
        cur.execute(f"CREATE TABLE add_pt ({col_defs});")
        conn.commit()

    # NOTE: dead code. Only reachable from the commented-out block in main(),
    # which calls combine_pt_records()/compare_to_destination() -- neither of
    # which exists any more. It also predates the current credentials layout
    # (it expected username/password/hostname/database rather than
    # un/pw/host/port). Left in place for reference; use compare_to_tcia().
    from sqlalchemy import create_engine
    engine = create_engine(config.db_url('tcia', 'private_tag_kb'))
    new_records_df.to_sql('add_pt', engine, index=False, if_exists='append')
    print("Inserted new records into add_pt.")

def main():


    #get_combined_pt_records()
    #get_compare_pt_records()
    compare_to_tcia()
    

    # extract_agreeement_pt_records()
    # generate_disagreement_table()

    # try:
    #     combined_df = combine_pt_records()
    #     new_records_df = compare_to_destination(conn, combined_df)
    #     if not new_records_df.empty:
    #         write_to_add_pt(conn, new_records_df)
    #     else:
    #         print("No new records to insert.")
    # finally:
    #     conn.close()

if __name__ == '__main__':
    main()







# name = split_camel_case_string(name) if name else None
# name = None if name is None else re.sub(r'\bNo\.?$', 'Number', name.strip())
# name = None if name is None else ' '.join(word[0].upper() + word[1:] if word else '' for word in name.split())

# def extract_agreeement_pt_records():
#     engine = create_engine(pt_parse_db_url, future=True)

#     agreement_sql = """
#         SELECT *
#         FROM combined_pt
#         WHERE
#             (SELECT COUNT(DISTINCT val) FROM (
#                 SELECT cl_pt_consensus_name AS val WHERE cl_exist = 1
#                 UNION SELECT gd_pt_consensus_name WHERE gd_exist = 1
#                 UNION SELECT py_pt_consensus_name WHERE py_exist = 1
#                 UNION SELECT dc_pt_consensus_name WHERE dc_exist = 1
#             )) <= 1
#         AND
#             (SELECT COUNT(DISTINCT val) FROM (
#                 SELECT cl_pt_consensus_vm AS val WHERE cl_exist = 1
#                 UNION SELECT gd_pt_consensus_vm WHERE gd_exist = 1
#                 UNION SELECT py_pt_consensus_vm WHERE py_exist = 1
#                 UNION SELECT dc_pt_consensus_vm WHERE dc_exist = 1
#             )) <= 1
#         AND
#             (SELECT COUNT(DISTINCT val) FROM (
#                 SELECT cl_pt_consensus_vr AS val WHERE cl_exist = 1
#                 UNION SELECT gd_pt_consensus_vr WHERE gd_exist = 1
#                 UNION SELECT py_pt_consensus_vr WHERE py_exist = 1
#                 UNION SELECT dc_pt_consensus_vr WHERE dc_exist = 1
#             )) <= 1;
#     """

#     with engine.begin() as conn:
#         df = pd.read_sql(text(agreement_sql), conn)

#         output_df = df[["pt_signature", "pt_owner", "pt_group", "pt_element"]].copy()

#         def pick_value_with_flag(row, field_prefix):
#             for source in ['cl', 'gd', 'py', 'dc']:
#                 if row.get(f"{source}_exist") and pd.notnull(row.get(f"{source}_{field_prefix}")):
#                     return row[f"{source}_{field_prefix}"]
#             return None

#         output_df["pt_consensus_vr"] = df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_vr"), axis=1)
#         output_df["pt_consensus_vm"] = df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_vm"), axis=1)
#         output_df["pt_consensus_name"] = df.apply(lambda r: pick_value_with_flag(r, "pt_consensus_name"), axis=1)

#         output_df.to_sql("compare_pt", conn, if_exists="replace", index=False)

#     print(f"Inserted {len(output_df)} agreement records into compare_pt.")
#     return output_df

# def extract_disagreement_tables():
#     engine = create_engine(pt_parse_db_url, future=True)

#     # Templates for individual field disagreement SQL
#     sql_template = """
#     SELECT *
#     FROM combined_pt
#     WHERE
#         (
#             SELECT COUNT(DISTINCT val)
#             FROM (
#                 SELECT {cl_field} AS val WHERE cl_exist = 1
#                 UNION SELECT {gd_field} WHERE gd_exist = 1
#                 UNION SELECT {py_field} WHERE py_exist = 1
#                 UNION SELECT {dc_field} WHERE dc_exist = 1
#             )
#         ) > 1
#     """

#     # Field groupings for name, vm, vr
#     field_sets = {
#         "name_diff_pt": [
#             "pt_signature", "pt_owner", "pt_group", "pt_element",
#             "cl_pt_consensus_name", "gd_pt_consensus_name", "py_pt_consensus_name", "dc_pt_consensus_name"
#         ],
#         "vm_diff_pt": [
#             "pt_signature", "pt_owner", "pt_group", "pt_element",
#             "cl_pt_consensus_vm", "gd_pt_consensus_vm", "py_pt_consensus_vm", "dc_pt_consensus_vm"
#         ],
#         "vr_diff_pt": [
#             "pt_signature", "pt_owner", "pt_group", "pt_element",
#             "cl_pt_consensus_vr", "gd_pt_consensus_vr", "py_pt_consensus_vr", "dc_pt_consensus_vr"
#         ]
#     }

#     with engine.begin() as conn:
#         for table_name, cols in field_sets.items():
#             field_suffix = cols[4].split("_")[-1]  # "name", "vm", or "vr"
#             sql = sql_template.format(
#                 cl_field=f"cl_pt_consensus_{field_suffix}",
#                 gd_field=f"gd_pt_consensus_{field_suffix}",
#                 py_field=f"py_pt_consensus_{field_suffix}",
#                 dc_field=f"dc_pt_consensus_{field_suffix}"
#             )
#             df = pd.read_sql(text(sql), conn)

#             # Subset to just relevant columns
#             output_df = df[cols].copy()
#             output_df.to_sql(table_name, conn, if_exists="replace", index=False)
#             print(f"Inserted {len(output_df)} rows into {table_name}")





# def generate_disagreement_table():
#     engine = create_engine(pt_parse_db_url, future=True)

#     sql_template = """
#     SELECT *
#     FROM combined_pt
#     WHERE
#         (
#             SELECT COUNT(DISTINCT val)
#             FROM (
#                 SELECT {cl_field} AS val WHERE cl_exist = 1
#                 UNION SELECT {gd_field} WHERE gd_exist = 1
#                 UNION SELECT {py_field} WHERE py_exist = 1
#                 UNION SELECT {dc_field} WHERE dc_exist = 1
#             )
#         ) > 1
#     """

#     field_suffixes = ["name", "vm", "vr"]
#     diff_flags = {}
#     full_results = []

#     with engine.begin() as conn:
#         base_cols = ["pt_signature", "pt_owner", "pt_group", "pt_element"]

#         # Loop through each field type
#         for field in field_suffixes:
#             cl_field = f"cl_pt_consensus_{field}"
#             gd_field = f"gd_pt_consensus_{field}"
#             py_field = f"py_pt_consensus_{field}"
#             dc_field = f"dc_pt_consensus_{field}"

#             sql = sql_template.format(
#                 cl_field=cl_field,
#                 gd_field=gd_field,
#                 py_field=py_field,
#                 dc_field=dc_field
#             )
#             df = pd.read_sql(text(sql), conn)

#             # Keep only the base cols + 4 source values
#             cols = base_cols + [cl_field, gd_field, py_field, dc_field]
#             df = df[cols].copy()

#             # Add a diff flag
#             df[f"{field}_diff"] = True

#             # Fill in placeholder for other fields to allow full merge
#             for other_field in field_suffixes:
#                 if other_field != field:
#                     for src in ['cl', 'gd', 'py', 'dc']:
#                         col_name = f"{src}_pt_consensus_{other_field}"
#                         df[col_name] = None
#                     df[f"{other_field}_diff"] = False

#             full_results.append(df)

#         # Combine all rows with differences in any field
#         combined_df = pd.concat(full_results, ignore_index=True)

#         # Drop duplicate rows (same tag appearing with multiple diffs)
#         combined_df = combined_df.groupby(["pt_signature", "pt_owner", "pt_group", "pt_element"], dropna=False).agg({
#             "name_diff": "max",
#             "vm_diff": "max",
#             "vr_diff": "max",
#             **{f"{src}_pt_consensus_name": 'first' for src in ['cl', 'gd', 'py', 'dc']},
#             **{f"{src}_pt_consensus_vm": 'first' for src in ['cl', 'gd', 'py', 'dc']},
#             **{f"{src}_pt_consensus_vr": 'first' for src in ['cl', 'gd', 'py', 'dc']}
#         }).reset_index()

#         # Write final table
#         combined_df.to_sql("disagree_pt", conn, if_exists="replace", index=False)
#         print(f"Inserted {len(combined_df)} rows into disagree_pt")

# import pandas as pd
# from sqlalchemy import create_engine, text

# def generate_disagreement_table():
#     engine = create_engine(pt_parse_db_url, future=True)

#     with engine.begin() as conn:
#         df = pd.read_sql("SELECT * FROM combined_pt", conn)

#         # Helper to compute field-level difference flags
#         def compute_diff_flag(df, field):
#             diffs = []
#             for i, row in df.iterrows():
#                 values = []
#                 for src in ['cl', 'gd', 'py', 'dc']:
#                     if row[f"{src}_exist"]:
#                         val = row[f"{src}_pt_consensus_{field}"]
#                         values.append(val)
#                 # Compare only the values from existing sources
#                 diffs.append(len(set(values)) > 1)
#             return pd.Series(diffs, index=df.index)

#         # Compute difference flags
#         df['name_diff'] = compute_diff_flag(df, 'name')
#         df['vm_diff'] = compute_diff_flag(df, 'vm')
#         df['vr_diff'] = compute_diff_flag(df, 'vr')

#         # Keep only rows with any differences
#         disagree_df = df[df[['name_diff', 'vm_diff', 'vr_diff']].any(axis=1)].copy()

#         # Reorder columns
#         base_cols = ["pt_signature", "pt_owner", "pt_group", "pt_element"]
#         diff_flags = ["name_diff", "vm_diff", "vr_diff"]
#         vr_cols = [f"{src}_pt_consensus_vr" for src in ['cl', 'gd', 'py', 'dc']]
#         vm_cols = [f"{src}_pt_consensus_vm" for src in ['cl', 'gd', 'py', 'dc']]
#         name_cols = [f"{src}_pt_consensus_name" for src in ['cl', 'gd', 'py', 'dc']]
#         exist_flags = [f"{src}_exist" for src in ['cl', 'gd', 'py', 'dc']]

#         col_order = base_cols + diff_flags + vr_cols + vm_cols + name_cols + exist_flags
#         disagree_df = disagree_df[col_order]

#         # Write to SQLite
#         disagree_df.to_sql("disagree_pt", conn, if_exists="replace", index=False)
#         print(f"Inserted {len(disagree_df)} rows into disagree_pt.")