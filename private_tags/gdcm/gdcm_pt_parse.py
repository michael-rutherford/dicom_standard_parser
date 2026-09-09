import xmltodict
import requests
import pandas as pd
import os
import logging
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import SQLAlchemyError
import re

# Configure logging with date and time
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s]: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Path to SQLite DB relative to script location
script_dir = os.path.dirname(os.path.abspath(__file__))
pt_parse_db_path = os.path.join(script_dir, "..", "database", "pt_parse.db")
pt_parse_db_url = f"sqlite:///{pt_parse_db_path}"

gdcm_private_dict_url = "https://raw.githubusercontent.com/malaterre/GDCM/master/Source/DataDictionary/privatedicts.xml"

def convert(row):
    try:
        group = row['@group']
        ele = row['@element'].replace('x', '')
        owner = row['@owner']
        name = row['@name']
        vr = row['@vr']
        vm = row['@vm']

        if name == '?':
            name = '\\N'

        group_int = int(group, 16)
        ele_int = int(ele, 16)

        signature = f"({group},\"{owner}\",{ele})"
        
        return {
            "pt_signature": signature,
            "pt_short_signature": signature,
            "pt_owner": owner,
            "pt_group": group_int,
            "pt_element": ele_int,
            "pt_consensus_vr": vr,
            "pt_consensus_vm": vm,
            "pt_consensus_name": name.strip() if name else None
        }
    except Exception as e:
        logging.warning(f"Skipping malformed entry: {row} - {e}")
        return None

def get_new_tags_df(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Failed to download private tag XML: {e}")
        return pd.DataFrame()

    try:
        data = xmltodict.parse(response.content)
    except Exception as e:
        logging.error(f"Failed to parse XML: {e}")
        return pd.DataFrame()

    rows = []
    for row in data.get('dict', {}).get('entry', []):
        if 'xx' not in row.get('@element', ''):
            continue
        if 'x' in row.get('@group', ''):
            continue

        tag = convert(row)
        if tag:
            rows.append(tag)

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
    df = get_new_tags_df(gdcm_private_dict_url)
    if df.empty:
        logging.info("No new tags found or XML could not be parsed.")
        return

    try:
        engine = create_engine(pt_parse_db_url, future=True)
        table_name = "gdcm_pt"

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
                logging.info(f"Inserted {len(df_new)} private tag definitions.")

    except SQLAlchemyError as e:
        logging.error(f"Database operation failed: {e}")

if __name__ == "__main__":
    main()
