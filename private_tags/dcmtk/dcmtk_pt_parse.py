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

dcmtk_private_dict_url = r"https://raw.githubusercontent.com/DCMTK/dcmtk/refs/heads/master/dcmdata/data/private.dic"

def get_dcmtk_private_tags(url):
    import requests
    import pandas as pd
    import re
    import logging

    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch dcmtk private dict: {e}")
        return pd.DataFrame()

    rows = []
    for line in response.text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split("\t")
        if len(parts) < 4:
            logging.warning(f"Skipping short/unparseable line: {line}")
            continue

        tag, vr, name, vm = parts[:4]

        match = re.match(r'^\((?P<group>[0-9A-Fa-f]{4}),\s*"(?P<owner>[^"]+)",\s*(?P<element>[0-9A-Fa-f]+)\)$', tag)

        if not match:
            logging.warning(f"Skipping malformed tag entry: {tag}")
            continue

        try:
            owner = match.group("owner")
            
            group_str = match.group("group").lower()
            element_str = match.group("element").lower()
            if len(element_str) == 4:
                element_str = element_str[-2:]

            group_int = int(group_str, 16)
            element_int = int(element_str, 16)
            
            signature = f"({group_int:04x},\"{owner}\",{element_int:02x})"

            row = {
                "pt_signature": signature,
                "pt_short_signature": signature,
                "pt_owner": owner,
                "pt_group": group_int,
                "pt_element": element_int,
                "pt_consensus_vr": vr,
                "pt_consensus_vm": vm,
                "pt_consensus_name": name.strip() if name else None
            }
            rows.append(row)

        except Exception as e:
            logging.warning(f"Skipping row due to error: {line} - {e}")
            continue

    return pd.DataFrame(rows)



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
    df = get_dcmtk_private_tags(dcmtk_private_dict_url)
    if df.empty:
        logging.info("No tags extracted from dcmtk private dict.")
        return

    try:
        engine = create_engine(pt_parse_db_url, future=True)
        table_name = "dcmtk_pt"

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
                logging.info(f"Inserted {len(df_new)} dcmtk private tag definitions.")

    except SQLAlchemyError as e:
        logging.error(f"Database operation failed: {e}")

if __name__ == "__main__":
    main()
