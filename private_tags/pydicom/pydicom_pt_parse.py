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

pydicom_private_dict_url = "https://raw.githubusercontent.com/pydicom/pydicom/refs/heads/main/src/pydicom/_private_dict.py"

def parse_pydicom_dict_text(text):
    # Extract dictionary text via regex
    match = re.search(r"private_dictionaries\s*:\s*dict\[.*?\]\s*=\s*({.*?})\s*\Z", text, re.DOTALL)
    if not match:
        raise ValueError("Could not locate private_dictionaries assignment.")

    dict_text = match.group(1)

    # Replace long string literals that may break parsing, if needed
    try:
        private_dict = ast.literal_eval(dict_text)
    except Exception as e:
        raise ValueError(f"Failed to evaluate dictionary: {e}")

    return private_dict

def parse_tag(tag_str):

    group_str = tag_str[:4]
    element_str = tag_str[6:]

    if "xx" in [group_str, element_str]:
        return None, None
    try:
        group = int(group_str, 16)
        element = int(element_str, 16)        
        return group, element
    except ValueError:
        return None, None

# def split_camel_case_string(text):
#     return ' '.join(re.findall(r'(?:[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+)', text))

def get_pydicom_private_tags(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.error(f"Failed to fetch pydicom private dict: {e}")
        return pd.DataFrame()

    try:
        private_dict = parse_pydicom_dict_text(response.text)
    except Exception as e:
        logging.error(f"Failed to parse AST: {e}")
        return pd.DataFrame()

    rows = []
    for owner, tagmap in private_dict.items():
        if "^" in owner:
            continue

        for tag_str, (vr, vm, name, retired) in tagmap.items():
            group, element = parse_tag(tag_str)
            if None in [group, element]:
                logging.warning(f"Skipping malformed tag: {tag_str}")
                continue
            signature = f"({group:04x},\"{owner}\",{element:02x})"
            
            row = {
                "pt_signature": signature,
                "pt_short_signature": signature,
                "pt_owner": owner,
                "pt_group": group,
                "pt_element": element,
                "pt_consensus_vr": vr,
                "pt_consensus_vm": vm,
                "pt_consensus_name": name.strip() if name else None,
            }
            rows.append(row)
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
    df = get_pydicom_private_tags(pydicom_private_dict_url)
    if df.empty:
        logging.info("No tags extracted from pydicom private dict.")
        return

    try:
        engine = create_engine(pt_parse_db_url, future=True)
        table_name = "pydicom_pt"

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
                logging.info(f"Inserted {len(df_new)} pydicom private tag definitions.")

    except SQLAlchemyError as e:
        logging.error(f"Database operation failed: {e}")

if __name__ == "__main__":
    main()
