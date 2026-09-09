import ast
import requests
import pandas as pd
import os
import logging
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
import re

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

script_dir = os.path.dirname(os.path.abspath(__file__))
pt_parse_db_path = os.path.join(script_dir, "..", "database", "pt_parse.db")
pt_parse_db_url = f"sqlite:///{pt_parse_db_path}"

clunie_files_dir = os.path.join(script_dir, "files")

def get_clunie_private_tags(files_path):
    import pandas as pd
    import os
    import re
    import logging

    rows = []

    for filename in os.listdir(files_path):
        full_path = os.path.join(files_path, filename)
        if not os.path.isfile(full_path) or not filename.endswith(".tpl"):
            continue

        with open(full_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                # Extract tag
                tag_match = re.match(r"^\((?P<group>[0-9A-Fa-f]{4}),(?P<element>[0-9A-Fa-f]{4})\)", line)
                if not tag_match:
                    logging.warning(f"Skipping line with malformed tag: {line}")
                    continue

                group_str = tag_match.group("group").lower()
                element_str = tag_match.group("element")[2:].lower()
                
                try:
                    group_int = int(group_str, 16)
                    element_int = int(element_str, 16)
                except ValueError:
                    logging.warning(f"Skipping line with non-hex tag: {line}")
                    continue
                
                # Extract key-value fields
                vr_match = re.search(r'VR="([^"]+)"', line)
                vm_match = re.search(r'VM="([^"]+)"', line)
                owner_match = re.search(r'Owner="([^"]+)"', line)
                name_match = re.search(r'Name="([^"]+)"', line)

                if not (vr_match and vm_match and owner_match and name_match):
                    logging.warning(f"Missing one or more fields in line: {line}")
                    continue

                vr = vr_match.group(1)
                vm = vm_match.group(1)
                owner = owner_match.group(1)
                name = name_match.group(1)

                signature = f"({group_int:04x},\"{owner}\",{element_int:02x})"

                rows.append({
                    "pt_signature": signature,
                    "pt_short_signature": signature,
                    "pt_owner": owner,
                    "pt_group": group_int,
                    "pt_element": element_int,
                    "pt_consensus_vr": vr,
                    "pt_consensus_vm": vm,
                    "pt_consensus_name": name.strip() if name else None
                })

    return_df = pd.DataFrame(rows)
    return_df = return_df.drop_duplicates().reset_index(drop=True)
    
    return return_df




def insert_in_batches(df, conn, table_name, batch_size=500):
    for start in range(0, len(df), batch_size):
        end = start + batch_size
        df.iloc[start:end].to_sql(
            table_name,
            con=conn,
            if_exists="append",
            index=False,
            method="multi"
        )

def main():
    df = get_clunie_private_tags(clunie_files_dir)
    if df.empty:
        logging.info("No tags extracted from clunie private dict.")
        return

    try:
        engine = create_engine(pt_parse_db_url, future=True)
        table_name = "clunie_pt"

        with engine.begin() as conn:
            inspector = inspect(conn)

            if table_name in inspector.get_table_names():
                try:
                    existing_sigs = pd.read_sql(f"SELECT pt_signature FROM {table_name}", conn)
                    existing_set = set(existing_sigs["pt_signature"])
                    df_new = df[~df["pt_signature"].isin(existing_set)]
                    logging.info(f"Found {len(df_new)} new entries (after deduplication).")
                except SQLAlchemyError as e:
                    logging.error(f"Error reading existing data: {e}")
                    return
            else:
                logging.warning(f"Table '{table_name}' not found. Inserting all {len(df)} rows.")
                df_new = df

            if df_new.empty:
                logging.info("No new tags to insert.")
            else:
                insert_in_batches(df_new, conn, table_name)
                logging.info(f"Inserted {len(df_new)} clunie private tag definitions.")

    except SQLAlchemyError as e:
        logging.error(f"Database operation failed: {e}")

if __name__ == "__main__":
    main()
