import os
import sys
import xml.etree.ElementTree as ET
import requests
import pandas as pd
import sqlite3 as sql
import json
import re
import logging
from datetime import datetime
import multiprocessing
import concurrent.futures as futures
import hashlib

#########################################################
# Script variables
#########################################################

#sys.setrecursionlimit(3000)

namespaces = {
    'xml': 'http://www.w3.org/XML/1998/namespace',
    'doc': 'http://docbook.org/ns/docbook'
}

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# Paths come from config.json at the repo root -- see config.example.json.
# The DICOM edition parsed is set by the URLs in the import_part_* functions
# below; keep 'standard_db' in config.json in sync with the edition selected.
data_folder = config.data_folder()
log_folder = config.log_folder()
db_conn = sql.connect(config.standard_db_path())

part_03_root = None
part_04_root = None
part_05_root = None
part_06_root = None
part_15_root = None
part_16_root = None

########################################################
# Import functions
#########################################################

def import_part_03():
    global part_03_root
    part_03_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part03/part03.xml"
    #part_03_xml_url = "http://dicom.nema.org/medical/dicom/2023e/source/docbook/part03/part03.xml"
    #part_03_xml_url = "http://dicom.nema.org/medical/dicom/2024a/source/docbook/part03/part03.xml"
    #part_03_xml_url = "http://dicom.nema.org/medical/dicom/2025a/source/docbook/part03/part03.xml"
    part_03_xml_response = requests.get(part_03_xml_url)
    part_03_root = ET.fromstring(part_03_xml_response.content)

def import_part_04():
    global part_04_root
    part_04_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part04/part04.xml"
    #part_04_xml_url = "http://dicom.nema.org/medical/dicom/2023e/source/docbook/part04/part04.xml"
    #part_04_xml_url = "http://dicom.nema.org/medical/dicom/2024a/source/docbook/part04/part04.xml"
    #part_04_xml_url = "http://dicom.nema.org/medical/dicom/2025a/source/docbook/part04/part04.xml"
    part_04_xml_response = requests.get(part_04_xml_url)
    part_04_root = ET.fromstring(part_04_xml_response.content)
    
def import_part_05():
    global part_05_root
    part_05_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part05/part05.xml"
    #part_05_xml_url = "http://dicom.nema.org/medical/dicom/2023e/source/docbook/part05/part05.xml"
    #part_05_xml_url = "http://dicom.nema.org/medical/dicom/2024a/source/docbook/part05/part05.xml"
    #part_05_xml_url = "http://dicom.nema.org/medical/dicom/2025a/source/docbook/part05/part05.xml"
    part_05_xml_response = requests.get(part_05_xml_url)
    part_05_root = ET.fromstring(part_05_xml_response.content)

def import_part_06():
    global part_06_root
    part_06_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part06/part06.xml"
    #part_06_xml_url = "http://dicom.nema.org/medical/dicom/2023e/source/docbook/part06/part06.xml"
    #part_06_xml_url = "http://dicom.nema.org/medical/dicom/2024a/source/docbook/part06/part06.xml"
    #part_06_xml_url = "http://dicom.nema.org/medical/dicom/2025a/source/docbook/part06/part06.xml"
    part_06_xml_response = requests.get(part_06_xml_url)
    part_06_root = ET.fromstring(part_06_xml_response.content)

def import_part_15():
    global part_15_root
    part_15_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part15/part15.xml"
    #part_15_xml_url = "http://dicom.nema.org/medical/dicom/2023e/source/docbook/part15/part15.xml"
    #part_15_xml_url = "http://dicom.nema.org/medical/dicom/2024a/source/docbook/part15/part15.xml"
    #part_15_xml_url = "http://dicom.nema.org/medical/dicom/2025a/source/docbook/part15/part15.xml"
    part_15_xml_response = requests.get(part_15_xml_url)
    part_15_root = ET.fromstring(part_15_xml_response.content)

def import_part_16():
    global part_16_root
    part_16_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part16/part16.xml"
    part_16_xml_response = requests.get(part_16_xml_url)
    part_16_root = ET.fromstring(part_16_xml_response.content)    

#########################################################
# XML Data functions
#########################################################

def extract_text(elem):
    """
    Extracts and processes text from an XML element, handling specific tags differently.

    :param elem: The XML element to process.
    :return: A string containing the processed text.
    """
    text_pieces = [] 
    
    if elem is not None:
        # Directly append element text if present
        if elem.text:
            text_pieces.append(elem.text.strip())
    
        for child in elem:
            # Handle link tags
            if child.tag.endswith('}olink') or child.tag.endswith('}xref'):
                link_text = ''.join(child.itertext()).strip()
                target = child.attrib.get('targetptr', '') or child.attrib.get('linkend', '')
                text_pieces.append(f"{link_text} {target}" if target else link_text)
            elif child.tag.endswith('}variablelist'):
                continue  # Skip adding anything for 'variablelist'
            else:
                # Recursively extract text from child elements
                text_pieces.append(extract_text(child))
        
            # Append the tail text if present
            if child.tail:
                text_pieces.append(child.tail.strip())
    
    # Join all pieces with spaces, then normalize whitespace
    return_string = ' '.join(' '.join(filter(None, text_pieces)).split()).strip()
    # Remove zero-width space characters
    clean_string = re.sub(u'\u200B', '', return_string)
        
    return clean_string

def extract_list(root, elem, cell_text):
    """
    Extract variablelist entries from the current element and any referenced targets
    mentioned in cell_text (handles both <id> and bare ids like table_..., sect_..., note_...).
    Returns a JSON string map of code -> description, or None if none found.
    """
    code_list = {}

    def add_entry(code: str, desc: str):
        code = (code or '').strip()
        desc = (desc or '').strip()
        if not code:
            return
        if code in code_list:
            if desc and desc != code_list[code]:
                # merge distinct descriptions
                existing = code_list[code]
                if desc not in existing:
                    code_list[code] = f"{existing} | {desc}"
        else:
            code_list[code] = desc

    def extract_from(el) -> int:
        if el is None:
            return 0
        found = 0
        # Look for ANY variablelist under el (not just direct children)
        for vlist in el.findall(".//doc:variablelist", namespaces):
            for entry in vlist.findall("./doc:varlistentry", namespaces):
                term_el = entry.find("./doc:term", namespaces)
                listitem_el = entry.find("./doc:listitem", namespaces)

                code = extract_text(term_el)
                # Join all paragraph text inside listitem; fallback to entire listitem text
                if listitem_el is not None:
                    paras = listitem_el.findall(".//doc:para", namespaces)
                    if paras:
                        desc = " ".join(filter(None, (extract_text(p) for p in paras)))
                    else:
                        desc = extract_text(listitem_el)
                else:
                    desc = ""

                add_entry(code, desc)
                found += 1
        return found

    # 1) Extract from the current element (e.g., the <td>)
    local_count = extract_from(elem)

    # 2) Follow references in cell_text:
    #    - Angle-bracketed tokens like <table_...> or <sect_...>
    #    - Bare IDs appended by extract_text from xref/olink (e.g., table_..., sect_..., note_...)
    ids = set()
    if isinstance(cell_text, str) and cell_text:
        # <id> tokens
        ids.update(m.strip() for m in re.findall(r"<([^>]+)>", cell_text))
        # bare ids commonly used by docbook
        ids.update(m.strip() for m in re.findall(r"\b(?:table|sect|note)_[A-Za-z0-9_.\-]+\b", cell_text))

    ref_total = 0
    for sid in ids:
        target = root.find(f".//*[@xml:id='{sid}']", namespaces)
        if target is None:
            continue
        ref_total += extract_from(target)

    # # Debug visibility
    # try:
    #     import logging
    #     logging.getLogger(__name__).debug(
    #         f"extract_list: local={local_count}, refs={ref_total}, ids={sorted(ids) if ids else []}"
    #     )
    # except Exception:
    #     pass

    return json.dumps(code_list, ensure_ascii=False) if code_list else None

# def extract_list(root, elem, cell_text):
#     """
#     Extracts information from specified XML elements and compiles it into a dictionary,
#     then converts this dictionary into a JSON string. It specifically looks for elements
#     marked as 'variablelist' and extracts text and descriptions from them. Additionally,
#     it searches for patterns within a given cell text to find and process additional elements.

#     Parameters:
#     - root: The root XML element from which the search should begin.
#     - elem: The specific XML element from which to start extracting information.
#     - cell_text: A string containing text which may include identifiers to further XML elements to be processed.

#     Returns:
#     - A JSON string representation of the extracted information.
#     """
#     code_list = {}
    
#     def extract(elem, code_list):
#         """
#         Recursively extracts information from specified XML elements and compiles it into the provided dictionary.

#         Parameters:
#         - elem: The XML element from which to start extracting information.
#         - code_list: A dictionary where the extracted information is compiled.
#         """
#         for child in elem:
#             if child.tag.endswith('}variablelist'):
#                 title = extract_text(child.find(".//doc:title", namespaces))
#                 for entry in child.findall(".//doc:varlistentry", namespaces):
#                     code = extract_text(entry.find(".//doc:term", namespaces))
#                     desc = extract_text(entry.find(".//doc:listitem/doc:para", namespaces))
#                     code_list[code] = desc
    
#     # Initial extraction from the provided element
#     extract(elem, code_list)
                
#     # Pre-compile the regular expression for efficiency
#     pattern = re.compile(r"<([^>]+)>")
#     matches = pattern.findall(cell_text)
    
#     if matches:
#         for match in matches:
#             sect = root.find(f".//*[@xml:id='{match}']", namespaces)
#             if sect:
#                 extract(sect, code_list)

#     return json.dumps(code_list, ensure_ascii=False) if code_list else None

def extract_table_data(root, table_name=None, sect_name=None, loaded=False):
    """
    Extracts table data from an XML structure and converts it into a pandas DataFrame.

    Parameters:
    - root: The root element of the XML structure.
    - table_name: The ID of the table to extract. If specified, the function searches for this table.
    - sect_name: The ID of the section from which to extract the table. Used if table_name is not specified.
    - loaded: A boolean flag indicating if additional data should be dynamically loaded during the extraction.

    Returns:
    - A pandas DataFrame containing the extracted table data.
    """
    
    table_df = None  # Placeholder for the resulting DataFrame

    def get_table(table_name=None, sect_name=None):
        """
        Searches for and returns a table element within the XML structure.

        Parameters:
        - table_name: The ID of the table to search for.
        - sect_name: The ID of the section from which to search for a table.

        Returns:
        - The found table element, or None if no table is found.
        """
        if table_name:
            return root.find(f".//*[@xml:id='{table_name}']", namespaces)
        elif sect_name:
            return root.find(f".//*[@xml:id='{sect_name}']//doc:table", namespaces)
        else:
            return None

    def process_table(table_name=None, sect_name=None, loaded=False, level_text=''):
        """
        Extracts and organizes table data, including handling of nested tables and dynamic content loading.

        Parameters:
        - table_name: The ID of the table to extract.
        - sect_name: The ID of the section from which to extract the table.
        - loaded: Indicates if additional data should be loaded for certain cells.
        - level_text: Prefix text for nested table cells to denote nesting level.

        Returns:
        - Tuple containing lists of headers and rows extracted from the table.
        """
        table = get_table(table_name, sect_name)

        headers, rows, rowspan_tracker = [], [], {}
        
        if table is not None:
            # Extract headers
            for th in table.findall(".//doc:thead/doc:tr/doc:th", namespaces):
                headers.append(extract_text(th))

            # Iterate through each row to extract cell data
            for tr in table.findall(".//doc:tbody/doc:tr", namespaces):
                inner_table, ignore_row, cells, col_index = None, False, [], 0

                # Process each cell in the row
                for td in tr.findall(".//doc:td", namespaces):                
                    inner_table, ignore_row, cells, col_index, rowspan_tracker = \
                        process_cell(td, cells, col_index, rowspan_tracker, loaded, level_text)
                    if ignore_row:
                        break

                if not ignore_row:
                    rows.append(cells)
                
                # Process any nested tables
                if inner_table:
                    inner_table_headers, inner_table_rows = \
                        process_table(table_name=inner_table[0], level_text=inner_table[1], loaded=loaded)
                    rows.extend(inner_table_rows)

        return headers, rows

    def process_cell(td, cells, col_index, rowspan_tracker, loaded, level_text):
        """
        Processes a single cell within a table row, handling 'rowspan', 'colspan',
        and conditionally loading additional data. Returns the updated cell text and column index.

        Parameters:
        - td: The table cell element to process.
        - cells: List of cells for the current row.
        - col_index: The current column index in the row.
        - rowspan_tracker: Dictionary tracking rowspans to correctly handle multi-row cells.
        - loaded: Flag indicating whether additional data loading is required for the cell.
        - level_text: Prefix text for nested table cells.

        Returns:
        - inner_table, ignore_row, cells, col_index,rowspan_tracker with updated inner table, 
        - ignore flag, cells, and column index.
        """
        # Handle rowspan logic
        if rowspan_tracker.get(col_index):
            cell_text, rows_left = rowspan_tracker[col_index]
            cells.append(cell_text)
            if rows_left > 1:
                rowspan_tracker[col_index] = (cell_text, rows_left - 1)
            else:
                del rowspan_tracker[col_index]
            col_index += 1

        inner_table = None
        ignore_row = False

        # Dynamically load data if conditions are met
        if loaded and col_index == 3:
            cell_text = extract_text(td)
            cells.append(cell_text)
            col_index += 1 
            cell_list = extract_list(root, td, cell_text)
            cells.append(cell_list)
            col_index += 1                          
        else:
            cell_text = extract_text(td)
            # Prepend level_text for nested tables
            if col_index == 0:
                cell_text = level_text + cell_text
            cells.append(cell_text)

            # Update rowspan tracker if applicable
            rowspan = int(td.attrib.get('rowspan', 1))
            if rowspan > 1:
                rowspan_tracker[col_index] = (cell_text, rowspan - 1)
                
            # Check for colspan to identify potential nested tables
            colspan = int(td.attrib.get('colspan', 1))
            if colspan > 1:
                # Check if the "Include" is a conditional include and ignore the row if it is
                cond_include = re.search(r'Include (.*?) if', cell_text)
                if not cond_include:
                    table_match = re.search(r"\<(table_[^>]+)\>", cell_text)
                    level_match = re.search(r"^(>+)", cell_text)
                    if table_match:
                        inner_table = (table_match.group(1), level_match.group(1) if level_match else '')
                ignore_row = True
            else:
                col_index += 1
                
        return inner_table, ignore_row, cells, col_index, rowspan_tracker
    
    # Main extraction logic
    headers, rows = process_table(table_name, sect_name, loaded=loaded)

    # Ensure there are headers for all columns
    headers = ['' for _ in rows[0]] if rows else []

    # Create and return the DataFrame
    table_df = pd.DataFrame(rows, columns=headers)
    return table_df

def extract_table_data_with_includes(root, table_name=None, sect_name=None, loaded=False):
    """
    Like extract_table_data, but:
      - does NOT inline nested tables
      - extracts 'Include ... <table_x-y> [if ...]' rows and keeps them as placeholder attributes
    Returns: attributes_df, includes_df (includes_df kept for backward compatibility but unused)
    """
    def get_table(table_name=None, sect_name=None):
        if table_name:
            return root.find(f".//*[@xml:id='{table_name}']", namespaces)
        elif sect_name:
            return root.find(f".//*[@xml:id='{sect_name}']//doc:table", namespaces)
        else:
            return None

    def level_from(cell_text):
        m = re.match(r"^(>+)", cell_text.strip()) if cell_text else None
        return len(m.group(1)) if m else 0

    def parse_include(cell_text):
        # accept both <table_...> and bare table_... tokens
        tbl = re.search(r"(?:<)?(table_[A-Za-z0-9_.\-]+)(?:>)?", cell_text or '')
        # capture full condition phrase including "Required if ..." when present
        condm = re.search(
            r'(\bRequired\s+if\b[^.]*|\bShall(?:\s+not)?\s+be\s+present\s+if\b[^.]*|\bMay(?:\s+also)?\s+be\s+present\s+if\b[^.]*|\bif\b[^.]*)(?:\.\s*|$)',
            cell_text or '',
            flags=re.IGNORECASE | re.DOTALL
        )
        cond = condm.group(1).strip() if condm else None
        return (tbl.group(1) if tbl else None), cond

    def split_include_title_and_desc(full_text: str):
        """
        Split an include row into:
          - title: from 'Include' through the table id token (no leading '>' kept here)
          - tail: any text after the table id (goes to desc)
        """
        if not isinstance(full_text, str):
            return full_text, None
        m = re.search(r'(?i)\binclude\b.*?(?:<)?(table_[A-Za-z0-9_.\-]+)(?:>)?', full_text)
        if not m:
            return full_text.strip(), None
        title = full_text[m.start():m.end()].strip()  # start at 'Include'
        tail = full_text[m.end():].strip() or None
        return title, tail

    def parse_condition_from_desc(desc_text: str):
        if not isinstance(desc_text, str) or not desc_text:
            return None
        m = re.search(
            r'(\bRequired\s+if\b[^.]*|\bShall(?:\s+not)?\s+be\s+present\s+if\b[^.]*|\bMay(?:\s+also)?\s+be\s+present\s+if\b[^.]*|\bif\b[^.]*)(?:\.\s*|$)',
            desc_text,
            flags=re.IGNORECASE | re.DOTALL
        )
        return m.group(1).strip() if m else None

    FG_MACRO_TABLES = [
        "table_C.7.6.16-7",
        "table_C.7.6.16-3",
        "table_C.7.6.16-4",
        "table_C.7.6.16-5",
        "table_C.7.6.16-2",
        "table_C.8.12.6.1-1",
        "table_C.8.20-3",
    ]

    table = get_table(table_name, sect_name)
    headers = []
    attr_rows = []
    include_rows = []  # compatibility only
    rowspan_tracker = {}
    expected_cols = 0

    if table is not None:
        for th in table.findall(".//doc:thead/doc:tr/doc:th", namespaces):
            headers.append(extract_text(th))
        expected_cols = len(headers) or 0

        for tr in table.findall(".//doc:tbody/doc:tr", namespaces):
            # carry rowspans
            logical_cols = []
            col_index = 0
            while rowspan_tracker.get(col_index):
                cell_text, rows_left = rowspan_tracker[col_index]
                logical_cols.append(cell_text)
                if rows_left > 1:
                    rowspan_tracker[col_index] = (cell_text, rows_left - 1)
                else:
                    del rowspan_tracker[col_index]
                col_index += 1

            tds = tr.findall(".//doc:td", namespaces)
            if not tds:
                continue

            current_texts = [extract_text(td) for td in tds]
            td_colspans = [int(td.attrib.get('colspan', 1)) for td in tds]
            row_span_sum = sum(td_colspans)
            first_colspan = td_colspans[0] if td_colspans else 1

            if expected_cols == 0:
                expected_cols = max(expected_cols, row_span_sum, len(tds))

            row_text_all = " ".join([t for t in logical_cols + current_texts if t])
            first_cell_text = logical_cols[0] if logical_cols else (current_texts[0] if current_texts else "")
            has_include = re.search(r"\bInclude\b", row_text_all, re.IGNORECASE) and re.search(r"(table_[A-Za-z0-9_.\-]+)", row_text_all)
            is_full_row_like = (len(tds) == 1) or (first_colspan >= expected_cols) or (row_span_sum >= expected_cols)

            # explicit level/prefix from first cell only
            prefix = re.match(r'^(>*)', first_cell_text or '').group(1) if first_cell_text else ''
            # special FG macros
            if re.search(r'\bInclude\s+one\s+or\s+more\s+Functional\s+Group\s+Macros\b', row_text_all, flags=re.IGNORECASE) and (is_full_row_like or re.search(r"\bInclude\b", first_cell_text or "", re.IGNORECASE)):
                cond_special = parse_condition_from_desc(row_text_all)
                for tbl_id in FG_MACRO_TABLES:
                    include_title = f"Include {tbl_id}"
                    include_tag_name = f"{prefix}{include_title}"
                    attr_rows.append([include_tag_name, None, None, None, None])
                    include_rows.append({
                        "level": level_from(include_tag_name),
                        "include_text": include_tag_name,
                        "macro_table_id": tbl_id,
                        "condition": cond_special
                    })
                # maintain rowspan continuity
                base_idx = len(logical_cols)
                for i, td in enumerate(tds):
                    text = current_texts[i]
                    rowspan = int(td.attrib.get('rowspan', 1))
                    if rowspan > 1:
                        rowspan_tracker[base_idx + i] = (text, rowspan - 1)
                continue

            if has_include and (is_full_row_like or re.search(r"\bInclude\b", first_cell_text or "", re.IGNORECASE)):
                macro_table_id, _ = parse_include(row_text_all)
                include_title, include_desc = split_include_title_and_desc(row_text_all.strip())
                # only add prefix once
                include_tag_name = include_title if include_title.startswith('>') else f"{prefix}{include_title}"
                attr_rows.append([include_tag_name, None, None, include_desc, None])
                include_rows.append({
                    "level": level_from(include_tag_name),
                    "include_text": include_tag_name,
                    "macro_table_id": macro_table_id,
                    "condition": parse_condition_from_desc(include_desc or '')
                })
                # maintain rowspans
                base_idx = len(logical_cols)
                for i, td in enumerate(tds):
                    text = current_texts[i]
                    rowspan = int(td.attrib.get('rowspan', 1))
                    if rowspan > 1:
                        rowspan_tracker[base_idx + i] = (text, rowspan - 1)
                continue

            # normal attribute row
            row_values = list(logical_cols)
            col_idx = len(logical_cols)
            for td, text in zip(tds, current_texts):
                row_values.append(text)
                rowspan = int(td.attrib.get('rowspan', 1))
                if rowspan > 1:
                    rowspan_tracker[col_idx] = (text, rowspan - 1)
                if loaded and col_idx == 3:
                    row_values.append(extract_list(root, td, text))
                col_idx += 1

            if any((v or '').strip() for v in row_values):
                attr_rows.append(row_values)

    def normalize_attr_row(r):
        r = (r + ["", "", "", "", ""])[:5]
        return r

    attr_rows = [normalize_attr_row(r) for r in attr_rows]
    if attr_rows:
        attrs_df = pd.DataFrame(attr_rows, columns=['tag_name','tag','type','desc','list'])
    else:
        attrs_df = pd.DataFrame(columns=['tag_name','tag','type','desc','list'])

    if not attrs_df.empty:
        attrs_df['level'] = attrs_df['tag_name'].apply(lambda s: level_from(s) if isinstance(s, str) else 0)

        inc_mask = attrs_df['tag_name'].str.contains(r'\bInclude\b', case=False, na=False)

        if 'macro_table_id' not in attrs_df.columns: attrs_df['macro_table_id'] = None
        if 'condition' not in attrs_df.columns: attrs_df['condition'] = None

        if inc_mask.any():
            attrs_df.loc[inc_mask, ['tag','type','list']] = None
            attrs_df.loc[inc_mask, 'condition'] = attrs_df.loc[inc_mask, 'desc'].apply(parse_condition_from_desc)

            def parse_macro(s):
                mid, cnd = parse_include(s or '')
                return pd.Series({'macro_table_id': mid, 'condition': cnd})
            parsed_inc = attrs_df.loc[inc_mask, 'tag_name'].apply(parse_macro)
            attrs_df.loc[inc_mask, 'macro_table_id'] = parsed_inc['macro_table_id'].values
            fill_idx = attrs_df.loc[inc_mask & attrs_df['condition'].isna()].index
            if len(fill_idx) > 0:
                attrs_df.loc[fill_idx, 'condition'] = parsed_inc.loc[fill_idx, 'condition']

        non_inc_mask = ~inc_mask
        attrs_df.loc[non_inc_mask, 'condition'] = attrs_df.loc[non_inc_mask, 'desc'].apply(parse_condition_from_desc)

    includes_df = pd.DataFrame(include_rows, columns=['level','include_text','macro_table_id','condition']) if include_rows else pd.DataFrame(columns=['level','include_text','macro_table_id','condition'])

    return attrs_df, includes_df

#########################################################
#########################################################
# Update DICOM Tables
#########################################################
#########################################################

def update_elements():
    #########################################################
    #########################################################
    # Update DICOM Elements
    #########################################################
    #########################################################

    logging.info('Updating Dicom Elements')

    # Part 06
    # Table 6-1
    # http://dicom.nema.org/medical/dicom/current/output/html/part06.html#table_6-1

    if not part_06_root:
        import_part_06()

    table_name = 'table_6-1'
    table_output = 'dicom_element'

    table_df = extract_table_data(part_06_root, table_name=table_name)
    table_df.columns = ['tag','name','keyword','vr','vm','comments']

    table_df['name'] = table_df['name'].str.replace(r',', '', regex=True)
    table_df['is_retired'] = table_df['comments'].str.contains(r"RET", na=False).astype('bool')

    table_df.loc[table_df['comments'].str.contains(r"RET", na=False), 'comments'] = ''
    table_df.loc[table_df['comments'].str.contains(r"See Note <note_6_1>", na=False), 'comments'] = 'See Note'    
    table_df.loc[table_df['vr'].str.contains(r"See Note <note_6_2>", na=False), 'vr'] = 'See Note'
    table_df = table_df[table_df['name'] != '']    

    table_df = table_df[['tag','name','keyword','vr','vm','is_retired','comments']]

    table_df.to_sql(table_output, db_conn, if_exists='replace', index=False,
                    dtype={'is_retired': 'BOOLEAN'})

def update_sop_classes():
    #########################################################
    #########################################################
    # Update SOP Classes
    #########################################################
    #########################################################

    logging.info('Updating SOP Classes')

    # Part 04
    # Table B.5-1
    # https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_B.5.html#table_B.5-1

    if not part_04_root:
        import_part_04()

    table_name = 'table_B.5-1'
    table_output = 'dicom_sop_class'

    table_df = extract_table_data(part_04_root, table_name=table_name)
    table_df = table_df.rename(columns={'iod_spec': 'iod_sect_id'})
    table_df.columns = ['sop_class_name','sop_class_uid','iod_sect_id','specialization']
    #table_df['parsed'] = False

    table_df.to_sql(table_output, db_conn, if_exists='replace', index=False)

def update_deid_profiles():
    #########################################################
    #########################################################
    # Update DICOM Deidentification Profiles
    #########################################################
    #########################################################

    logging.info('Updating Deid Profiles')

    # Part 15
    # Table E.1-1a
    # http://dicom.nema.org/medical/dicom/current/output/html/part15.html#table_E.1-1a

    if not part_15_root:
        import_part_15()

    table_name = 'table_E.1-1a'
    table_output = 'dicom_deid_action_code'

    table_df = extract_table_data(part_15_root, table_name=table_name)
    table_df.columns = ['code','action']
    table_df.to_sql(table_output, db_conn, if_exists='replace', index=False)

    # Table E.1-1
    # http://dicom.nema.org/medical/dicom/current/output/html/part15.html#table_E.1-1

    location = 'E.1.1'
    table_name = 'table_E.1-1'
    table_output = 'dicom_deid_profile'

    table_df = extract_table_data(part_15_root, table_name=table_name)

    table_df.columns = ['name','tag','retd','in_std_comp_iod','basic_prof','rtn_safe_priv_opt',
                        'rtn_uids_opt','rtn_dev_id_opt','rtn_inst_id_opt','rtn_pat_chars_opt',
                        'rtn_long_full_dates_opt','rtn_long_modif_dates_opt','clean_desc_opt',
                        'clean_struct_cont_opt','clean_graph_opt']
    table_df.to_sql(table_output, db_conn, if_exists='replace', index=False)

def update_safe_private():
    #########################################################
    #########################################################
    # Update Safe Private
    #########################################################
    #########################################################

    logging.info('Updating Safe Private Elements')

    # Part 15
    # Table E.3.10-1
    # https://dicom.nema.org/medical/dicom/current/output/html/part15.html#table_E.3.10-1

    if not part_15_root:
        import_part_15()

    table_name = 'table_E.3.10-1'
    table_output = 'dicom_safe_private'

    table_df = extract_table_data(part_15_root, table_name=table_name)
    table_df.columns = ['tag','private_creator','vr','vm','meaning']
    
    def format_tag(tag_str):
        inside_parentheses = tag_str[tag_str.find("(")+1:tag_str.find(")")]
        group, element = inside_parentheses.split(',')
        creator = tag_str[tag_str.find(")")+1:].strip()
        group = group.strip().upper()
        element = element.replace('xx', '').strip().upper()
        return f"({group.upper()},\"{creator}\",{element.upper()})"

    table_df['pt_tag'] = table_df['tag'] + table_df['private_creator']
    table_df['pt_tag'] = table_df['pt_tag'].apply(format_tag)
    table_df = table_df[['pt_tag', 'tag', 'private_creator', 'vr', 'vm', 'meaning']]

    table_df.to_sql(table_output, db_conn, if_exists='replace', index=False)

def update_class_modules():
    
    #########################################################
    #########################################################
    # Update Class Modules
    #########################################################
    #########################################################

    logging.info('Updating Class Modules')
    
    if not part_03_root:
        import_part_03()

    # select all records from the sop_classes table
    sop_classes = pd.read_sql_query("SELECT * FROM dicom_sop_class", db_conn)
    
    sop_class_iod_module_list = []
    
    # iterate through the sop_classes table
    for index, row in sop_classes.iterrows():
        logging.info(f'Processing {row.sop_class_uid}')
        sect_name = row.iod_spec.strip('<>')
        table_df = extract_table_data(part_03_root, sect_name=sect_name)
        table_df.columns = ['ie','module','reference','usage']
        
        # ------------------------------------
        # ! fix for multi-line usage value. This is a temporary fix
        table_df['usage'] = table_df['usage'].str.replace(r'C Required', 'C - Required', regex=True)
        # ------------------------------------

        table_df['condition'] = table_df['usage'].str.split(' - ', expand=True).get(1)
        table_df['usage'] = table_df['usage'].str.replace(r' - .+$', '', regex=True)

        table_df.insert(0, 'sop_class_uid', row.sop_class_uid)
        
        sop_class_iod_module_list.append(table_df)
        #break

    sop_class_iod_module_df = pd.concat(sop_class_iod_module_list, ignore_index=True)
    sop_class_iod_module_df.to_sql("dicom_class_iod_modules", db_conn, if_exists='replace')

    return None

# --------------------------------------------------------

def format_table_data(data_df):
    work_df = data_df.copy()
    work_df['level'] = 0
    work_df['tag_full'] = ''
    work_df['type_root'] = None
    work_df['type_parent'] = None

    running_capture = []

    for index, row in work_df.iterrows():
        tag = row.tag
        tag_name = row.tag_name if isinstance(row.tag_name, str) else ''
        if pd.isna(tag) or tag is None or tag == '':
            continue

        level = int(tag_name.count('>'))
        work_df.at[index, 'level'] = level

        while len(running_capture) < level:
            running_capture.append(None)
        if len(running_capture) == level:
            running_capture.append((tag, row.type))
        else:
            running_capture[level] = (tag, row.type)
            del running_capture[level + 1:]

        # Build tag_full without angle brackets; join path with '|'
        parts = [t[0] for t in running_capture[: level + 1] if t and isinstance(t[0], str)]
        work_df.at[index, 'tag_full'] = '|'.join(parts)

        # Root/parent types (unchanged)
        root_type = None
        for t in running_capture:
            if t and t[1]:
                root_type = t[1]
                break
        work_df.at[index, 'type_root'] = root_type if root_type is not None else row.type

        parent_type = None
        for j in range(level - 1, -1, -1):
            if j < len(running_capture) and running_capture[j] and running_capture[j][1]:
                parent_type = running_capture[j][1]
                break
        work_df.at[index, 'type_parent'] = parent_type

    return work_df[~pd.isna(work_df.tag)]

def process_sop_class(root, sop_class_row, sop_class_modules_df):
        
    sop_class_module_req_list = []        
        
    for module_index, module_row in sop_class_modules_df.iterrows():
    
        sect_name = module_row.reference.strip('<>')
        table_df = extract_table_data(root, sect_name=sect_name, loaded=True)
        table_df.columns = ['tag_name','tag','type','desc','list']
        
        table_df.insert(0, 'usage', module_row.usage)
        table_df.insert(0, 'module', module_row.module)
        table_df.insert(0, 'ie', module_row.ie)
        table_df.insert(0, 'sop_class_uid', module_row.sop_class_uid)
    
        table_df.tag = '<' + table_df.tag + '>'   
        table_df = format_table_data(table_df)
        
        sop_class_module_req_list.append(table_df)

    sop_class_module_req_df = pd.concat(sop_class_module_req_list, ignore_index=True)
    sop_class_module_req_df = sop_class_module_req_df[['sop_class_uid', 'ie', 'module', 'usage', 'tag', 'tag_full', 'level', 'type', 'type_root', 'type_parent', 'tag_name', 'desc', 'list']]  
        
    return sop_class_row, sop_class_module_req_df

def update_class_requirements(multi=True, cpu=30):

    #########################################################
    #########################################################
    # Update Class Requirements
    #########################################################
    #########################################################    
    
    logging.info('Updating Class Requirements')

    if not part_03_root:
        import_part_03()

    db_conn.execute(f"DROP TABLE IF EXISTS 'dicom_class_iod_requirement'")
    db_conn.execute(f"UPDATE dicom_sop_class SET parsed = 0")
    db_conn.commit()

    sop_classes_df = pd.read_sql_query("SELECT * FROM dicom_sop_class", db_conn)
    
    if multi:
        with futures.ProcessPoolExecutor(max_workers=cpu) as executor:
            
            futures_list = []
            
            for class_index, class_row in sop_classes_df.iterrows():
                logging.info(f'Adding {class_row.sop_class_uid} to Queue')
                sop_class_modules_df = pd.read_sql_query(f"SELECT * FROM dicom_class_iod_modules where sop_class_uid = '{class_row.sop_class_uid}'", db_conn)
                futures_list.append(executor.submit(process_sop_class, part_03_root, class_row, sop_class_modules_df))
                
            for future in futures.as_completed(futures_list):
                # try:
                return_row, sop_class_module_req_df = future.result()
                logging.info(f'Finalizing {return_row.sop_class_uid}')
                sop_class_module_req_df.to_sql("dicom_class_iod_requirement", db_conn, if_exists='append')        
                db_conn.execute(f"UPDATE dicom_sop_class SET parsed = 1 where sop_class_uid = '{return_row.sop_class_uid}'")
                db_conn.commit()
                # except Exception as e:
                #     logging.error(e)
    else:
        for class_index, class_row in sop_classes_df.iterrows():
            # try:
            sop_class_modules_df = pd.read_sql_query(f"SELECT * FROM dicom_class_iod_modules where sop_class_uid = '{class_row.sop_class_uid}'", db_conn)
            return_row, sop_class_module_req_df = process_sop_class(part_03_root, class_row, sop_class_modules_df)
            sop_class_module_req_df.to_sql("dicom_class_iod_requirement", db_conn, if_exists='append')        
            db_conn.execute(f"UPDATE dicom_sop_class SET parsed = 1 where sop_class_uid = '{return_row.sop_class_uid}'")
            db_conn.commit()
            # except Exception as e:
            #     logging.error(e)            

    return None

def update_conditional_requirements():
    logging.info('Updating Conditional Requirements')

    conditional_patterns = [
        #r"(?:Only a single Item|Zero or one Item|One or more Items|Multiple Items|Zero or more Items|Multiple Items)\s(?:may|shall|are) (?:permitted|be included|used).+?[\.!?]",
        # r"Required[^.]*?if[^.<>]*(?:<[^>]*>[^.<>]*?)*\.(?:\s*May(?: also)? be present .+?\.)?",
        # r"(?:The number of Items).+?[\.!?]",
        # r"(?:Shall (?:not be included|be present) if)[^.<>]*(?:<[^>]*>[^.<>]*?)*\.",
        # r"(?:The Attribute is absent)[^.]*?(?:e\.g\.).+?[\.!?]",
        # r"(If[^.]*?\bis present.+?\.)"
        #r"(?:only a single item|only one item|zero or one item|zero or more items|one or more items|multiple items).+?[\.!?]"

        r"(?:(?<=^)|(?<=[.!?]\s))\b(?:only a single item|only one item|zero or one item|zero or more items|one or more items|multiple items)\b.+?[.!?]"
    ]
    
    combined_pattern = r"|".join(conditional_patterns)
    compiled_combined_pattern = re.compile(combined_pattern, re.IGNORECASE | re.DOTALL)
            
    def extract_info(desc):
        all_conditions = []
    
        # Finding all matches for the combined pattern
        for match in compiled_combined_pattern.finditer(desc):
            condition = match.group(0)
            if condition not in all_conditions: 
                all_conditions.append(condition)
    
        description = desc
        #description = ' '.join(filter(None, (description.replace(condition, "").strip() for condition in all_conditions)))
        for condition in all_conditions:
            description = description.replace(condition, "").strip()
            

        return description, json.dumps(all_conditions)    

    out_conn = sql.connect(f'{data_folder}\\blobs.db')
    
    blobs_df = pd.read_sql_query("select * from conditional_text", out_conn, index_col="index")
    
    blobs_df['description'], blobs_df['condition_text'] = zip(*blobs_df['desc'].apply(extract_info))
    
    blobs_df.to_sql("conditional_text", out_conn, if_exists='replace')
    
    return None

def output_conditional_blobs():
    
    logging.info('Outputting Conditional Blobs')
    
    blob_query = """
        select distinct desc 
        from dicom_class_iod_requirement
        where type in ('1C','2C')
        order by desc
    """

    blobs_df = pd.read_sql_query(blob_query, db_conn)
    
    out_conn = sql.connect(f'{data_folder}\\blobs.db')

    blobs_df.to_sql("conditional_text", out_conn, if_exists='replace')
    
    out_conn.close()
    
    return None

# --------------------------------------------------------

def update_modules():
    """
    Normalize IODs and Modules:
      - dicom_module
      - dicom_iod_module (keyed by iod_sect_id + module_sect_id)
    """
    logging.info('Normalizing IODs and Modules')

    if not part_03_root:
        import_part_03()

    # Ensure SOP Classes table exists
    sop_classes = pd.read_sql_query("SELECT * FROM dicom_sop_class", db_conn)

    # Build iod_modules and modules (dedupe by IOD+Module)
    iod_module_rows = []
    modules_rows = {}

    for _, row in sop_classes.iterrows():
        sect_name = row.iod_sect_id or ''
        if not sect_name:
            continue

        iod_mod_df = extract_table_data(part_03_root, sect_name=sect_name)
        if iod_mod_df.empty:
            continue

        iod_mod_df.columns = ['ie','module','reference','usage']

        iod_mod_df['usage'] = iod_mod_df['usage'].str.replace(r'C Required', 'C - Required', regex=True)
        iod_mod_df['condition'] = iod_mod_df['usage'].str.split(' - ', expand=True).get(1)
        iod_mod_df['usage'] = iod_mod_df['usage'].str.replace(r' - .+$', '', regex=True)

        for _, mrow in iod_mod_df.iterrows():
            module_sect_id = mrow.reference or ''
            if not module_sect_id:
                continue
            iod_module_rows.append({
                'iod_sect_id': sect_name, 
                'ie': mrow.ie,
                'module_name': mrow.module,
                'module_sect_id': module_sect_id,
                'usage': mrow.usage,
                'condition': mrow.condition
            })
            modules_rows.setdefault(module_sect_id, {'module_sect_id': module_sect_id, 'module_name': mrow.module})

    if iod_module_rows:
        iod_modules_df = pd.DataFrame(iod_module_rows)
        iod_modules_df.drop_duplicates(subset=['iod_sect_id','module_sect_id'], inplace=True)
        iod_modules_df.to_sql('dicom_iod_module', db_conn, if_exists='replace', index=False)
    else:
        iod_modules_df = pd.DataFrame(columns=['iod_sect_id','ie','module_name','module_sect_id','usage','condition'])
        iod_modules_df.to_sql('dicom_iod_module', db_conn, if_exists='replace', index=False)

    # sort by module_sect_id

    pd.DataFrame(modules_rows.values()).to_sql('dicom_module', db_conn, if_exists='replace', index=False)

def update_module_attributes():
    """
    For each unique Module (section id), parse its attribute table:
      - dicom_module_attribute (now includes level, macro_table_id, condition)
    """
    logging.info('Extracting Module attributes (with includes embedded)')

    if not part_03_root:
        import_part_03()

    modules_df = pd.read_sql_query("SELECT * FROM dicom_module", db_conn)
    module_attr_frames = []

    for _, m in modules_df.iterrows():
        sect_name = m.module_sect_id
        attrs_df, _inc_df = extract_table_data_with_includes(part_03_root, sect_name=sect_name, loaded=True)

        if not attrs_df.empty:
            attrs_df = attrs_df.copy()
            attrs_df.insert(0, 'module_sect_id', sect_name)
            module_attr_frames.append(attrs_df)

    # write attributes with new columns
    if module_attr_frames:
        out_df = pd.concat(module_attr_frames, ignore_index=True)
        # ensure columns exist even if empty in some modules
        for col in ['level','macro_table_id','condition']:
            if col not in out_df.columns:
                out_df[col] = None
        out_df.to_sql('dicom_module_attribute', db_conn, if_exists='replace', index=False)
    else:
        pd.DataFrame(columns=['module_sect_id','tag_name','tag','type','desc','list','level','macro_table_id','condition']).to_sql('dicom_module_attribute', db_conn, if_exists='replace', index=False)

# --------------------------------------------------------

def extract_macro_table(macro_table_id):
    """
    Parse a Macro table and return:
      - macro_name
      - macro_attrs_df: attributes with include rows embedded
        Columns: tag_name, tag, type, desc, list, level, included_macro_table_id, condition
    """
    if not part_03_root:
        import_part_03()

    table = part_03_root.find(f".//*[@xml:id='{macro_table_id}']", namespaces)

    def clean_title(t: str) -> str:
        if not t:
            return ""
        # remove "Table ... ." prefix (up to the first period)
        t = re.sub(r'^\s*Table[^.]*\.\s*', '', t).strip()
        # normalize whitespace and strip quotes
        t = ' '.join(t.split()).strip('“”"\'')
        return t

    def get_table_title(el) -> str:
        if el is None:
            return ""
        # Prefer a title inside caption; otherwise use the whole caption text
        cap = el.find("./doc:caption", namespaces)
        raw = ""
        if cap is not None:
            t_el = cap.find("./doc:title", namespaces)
            raw = extract_text(t_el) if t_el is not None else extract_text(cap)
        else:
            # Fallback to a direct table title
            t_el = el.find("./doc:title", namespaces)
            raw = extract_text(t_el) if t_el is not None else ""

        name = clean_title(raw)
        # Guard against bogus titles like "Enumerated Values" or empty strings
        if not name or re.match(r'(?i)^(enumerated values?|note|notes):?\s*$', name):
            name = ""
        return name

    macro_name = macro_table_id
    if table is not None:
        name = get_table_title(table)
        macro_name = name or macro_table_id

    attrs_df, _ = extract_table_data_with_includes(part_03_root, table_name=macro_table_id, loaded=True)
    if attrs_df is None or attrs_df.empty:
        empty_cols = ['tag_name','tag','type','desc','list','level','included_macro_table_id','condition']
        return macro_name, pd.DataFrame(columns=empty_cols)

    attrs_df = attrs_df.copy()

    if 'macro_table_id' in attrs_df.columns:
        attrs_df.rename(columns={'macro_table_id': 'included_macro_table_id'}, inplace=True)
    else:
        attrs_df['included_macro_table_id'] = None

    for col in ['tag_name','tag','type','desc','list','level','included_macro_table_id','condition']:
        if col not in attrs_df.columns:
            attrs_df[col] = None

    return macro_name, attrs_df

def update_macros():
    """
    Discover Macros referenced by Modules (and recursively by other Macros),
    store:
      - dicom_macro
      - dicom_macro_attribute (include rows embedded; no dicom_macro_includes)
    """
    logging.info('Extracting Macros')

    if not part_03_root:
        import_part_03()

    # Seed from module attributes' include references
    inc_df = pd.read_sql_query(
        "SELECT DISTINCT macro_table_id FROM dicom_module_attribute WHERE macro_table_id IS NOT NULL",
        db_conn
    )
    pending = set(inc_df['macro_table_id'].dropna().tolist())
    seen = set()

    macros_rows = []
    macro_attr_frames = []

    while pending:
        macro_table_id = pending.pop()
        if not macro_table_id or macro_table_id in seen:
            continue
        seen.add(macro_table_id)

        macro_name, attrs_df = extract_macro_table(macro_table_id)

        # Record the macro
        macros_rows.append({'macro_table_id': macro_table_id, 'macro_name': macro_name})

        # Attributes for this macro
        if not attrs_df.empty:
            df = attrs_df.copy()
            # Parent macro id column (analogous to module_sect_id in module attrs)
            df.insert(0, 'macro_table_id', macro_table_id)
            # Ensure uniform schema
            for col in ['tag_name','tag','type','desc','list','level','included_macro_table_id','condition']:
                if col not in df.columns:
                    df[col] = None
            macro_attr_frames.append(df)

            # Queue nested includes found inside this macro
            nested = set(df['included_macro_table_id'].dropna().unique().tolist())
            for t in nested:
                if t not in seen:
                    pending.add(t)

    # Write outputs
    pd.DataFrame(macros_rows).to_sql('dicom_macro', db_conn, if_exists='replace', index=False)

    if macro_attr_frames:
        out_cols = ['macro_table_id','tag_name','tag','type','desc','list','level','included_macro_table_id','condition']
        pd.concat(macro_attr_frames, ignore_index=True)[out_cols] \
            .to_sql('dicom_macro_attribute', db_conn, if_exists='replace', index=False)
    else:
        pd.DataFrame(columns=['macro_table_id','tag_name','tag','type','desc','list','level','included_macro_table_id','condition']) \
            .to_sql('dicom_macro_attribute', db_conn, if_exists='replace', index=False)

# --------------------------------------------------------

def update_uids():
    """
    Parse PS3.6 (Part 06) UID Registry tables and write to dicom_uid.
    We detect tables by presence of a 'UID Value' column and then map flexible headers.
    Output columns: uid, name, type, retired, part, source_table
    """
    logging.info('Updating DICOM UID Registry')

    if not part_06_root:
        import_part_06()

    rows = []

    def norm_hdr(h: str) -> str:
        h = (h or '').strip().lower()
        # normalize common variants
        h = h.replace('uid value', 'uid').replace('uid name', 'name').replace('uid type', 'type')
        h = h.replace('definition', 'name')  # some tables use "Definition" for name
        h = h.replace('status', 'retired')
        return h

    def extract_headers(table_el):
        headers = []
        for th in table_el.findall(".//doc:thead/doc:tr/doc:th", namespaces):
            headers.append(extract_text(th))
        return headers

    uid_table_count = 0

    # Walk all tables in Part 06 and pick ones with a UID column
    for tbl in part_06_root.findall(".//doc:table", namespaces):
        headers = extract_headers(tbl)
        if not headers:
            continue

        hdr_norm = [norm_hdr(h) for h in headers]
        if 'uid' not in hdr_norm:
            # not a UID registry table
            continue

        uid_table_count += 1
        table_id = tbl.attrib.get(f'{{{namespaces["xml"]}}}id') or tbl.attrib.get('id') or None

        # Build index map
        idx = {k: i for i, k in enumerate(hdr_norm)}

        # iterate rows
        for tr in tbl.findall(".//doc:tbody/doc:tr", namespaces):
            tds = tr.findall("./doc:td", namespaces)
            if not tds:
                continue

            cells = [extract_text(td) for td in tds]

            def get_val(key, default=''):
                i = idx.get(key, None)
                return cells[i] if i is not None and i < len(cells) else default

            uid_raw = get_val('uid')
            name_raw = get_val('name')
            type_raw = get_val('type')
            retired_raw = get_val('retired') or get_val('retired?') or get_val('retirement') or ''
            part_raw = get_val('part')

            # normalize UID (extract dotted number if extra text present)
            m = re.search(r'(?<![\d.])((?:\d+\.)+\d+)(?![\d.])', uid_raw or '')
            uid = m.group(1) if m else (uid_raw or '').strip()

            # skip rows that don't look like valid UIDs
            if not uid or not re.match(r'^\d+(?:\.\d+)+$', uid):
                continue

            # normalize name
            name = (name_raw or '').strip('“”"\' ').strip()

            # normalize type
            utype = (type_raw or '').strip()

            # normalize retired to boolean
            retired_txt = (retired_raw or '').strip()
            retired = bool(re.search(r'\b(retired|yes|true|y)\b', retired_txt, flags=re.IGNORECASE))

            rows.append({
                'uid': uid,
                'name': name,
                'type': utype,
                'retired': retired,
                'part': (part_raw or '').strip(),
                'source_table': table_id
            })

    if not rows:
        logging.warning('No UID tables found in Part 06.')
        df = pd.DataFrame(columns=['uid','name','type','retired','part','source_table'])
        df.to_sql('dicom_uid', db_conn, if_exists='replace', index=False)
        return

    uids_df = pd.DataFrame(rows)

    # Deduplicate UIDs; prefer non-retired over retired
    uids_df.sort_values(by=['uid','retired'], ascending=[True, True], inplace=True)
    uids_df = uids_df.drop_duplicates(subset=['uid'], keep='first')

    # Final write
    uids_df.to_sql('dicom_uid', db_conn, if_exists='replace', index=False,
                   dtype={'retired': 'BOOLEAN'})

    logging.info(f'Parsed {uid_table_count} UID tables, wrote {len(uids_df)} unique UIDs.')

def update_charsets():
    """
    Parse PS3.5 Specific Character Set values and write to dicom_charset.
    Strategy:
      1) Parse canonical table(s): table_6.1.2-1 (and optional -2 if present).
      2) Fallback: scan other tables (Annex H/I) and variablelists for extra tokens.
    Output: charset_value, name, notes, source_table
    """
    logging.info('Updating Specific Character Sets')

    if not part_05_root:
        import_part_05()

    rows = []

    VALUE_TOKEN_RE = re.compile(
        r'\b(?:ISO(?:_IR| 2022 IR)\s*\d+|ISO[_ -]?8859(?:-\d+)?|ISO[_ -]?10646|UTF-8|GB18030|GB2312|GBK|BIG5|'
        r'Shift[_ ]?JIS|EUC[- ]?JP|JIS\s?X\s?\d{4}|TIS-620|KS\s?X\s?1001|CNS\s?11643)\b',
        re.IGNORECASE
    )

    def normalize_value(v: str) -> str:
        v = re.sub(r'(?i)^\s*Value\s*\d+\s*:\s*', '', v or '').strip()  # drop "Value n:"
        return ' '.join(v.split())

    def parse_charset_table(tbl) -> int:
        hdrs = [extract_text(th) for th in tbl.findall(".//doc:thead/doc:tr/doc:th", namespaces)]
        norm = [h.strip().lower() for h in hdrs]
        val_idx = name_idx = notes_idx = escape_idx = None
        for i, h in enumerate(norm):
            if re.search(r'\b(defined\s*term|specific\s+character\s+set|value)\b', h):
                val_idx = i
            elif re.search(r'\b(character\s+repertoire|definition|description|name)\b', h):
                if name_idx is None:
                    name_idx = i
            if re.search(r'\bnotes?\b', h):
                notes_idx = i
            if 'escape' in h:
                escape_idx = i
        if val_idx is None:
            return 0

        table_id = tbl.attrib.get(f'{{{namespaces["xml"]}}}id') or tbl.attrib.get('id')
        added = 0
        for tr in tbl.findall(".//doc:tbody/doc:tr", namespaces):
            tds = tr.findall("./doc:td", namespaces)
            if not tds or val_idx >= len(tds):
                continue

            def cell(i):
                return extract_text(tds[i]) if (i is not None and i < len(tds)) else ''

            value = normalize_value(cell(val_idx) or '')
            if not VALUE_TOKEN_RE.search(value):
                continue
            name = (cell(name_idx) or '').strip() if name_idx is not None else ''
            notes = (cell(notes_idx) or '').strip() if notes_idx is not None else ''
            esc = (cell(escape_idx) or '').strip() if escape_idx is not None else ''
            if esc:
                notes = (notes + (' ' if notes else '') + f"Escape: {esc}").strip()

            rows.append({'charset_value': value, 'name': name, 'notes': notes, 'source_table': table_id})
            added += 1
        return added

    # 1) Canonical tables (most important)
    canonical_ids = ['table_6.1.2-1', 'table_6.1.2-2']
    total_added = 0
    for tid in canonical_ids:
        tbl = part_05_root.find(f".//*[@xml:id='{tid}']", namespaces)
        if tbl is not None:
            added = parse_charset_table(tbl)
            logging.debug(f"Parsed canonical charset table {tid} -> {added} rows")
            total_added += added

    # 2) Fallbacks: Annex examples and variablelists
    if total_added == 0:
        # variablelists
        for vlist in part_05_root.findall(".//doc:variablelist", namespaces):
            for entry in vlist.findall("./doc:varlistentry", namespaces):
                term_el = entry.find("./doc:term", namespaces)
                listitem_el = entry.find("./doc:listitem", namespaces)
                term = extract_text(term_el)
                if not term or not VALUE_TOKEN_RE.search(term):
                    continue
                value = normalize_value(term)
                desc = extract_text(listitem_el)
                # keep a short name if possible
                name = ''
                if desc:
                    m = re.match(r'^([^.;:]{1,120})', desc)
                    name = (m.group(1) if m else desc).strip()
                rows.append({'charset_value': value, 'name': name, 'notes': desc or '', 'source_table': None})

        # tables with tokens (Annex H/I)
        for tbl in part_05_root.findall(".//doc:table", namespaces):
            hdrs = [extract_text(th) for th in tbl.findall(".//doc:thead/doc:tr/doc:th", namespaces)]
            if not hdrs:
                continue
            added = parse_charset_table(tbl)
            if added:
                t_id = tbl.attrib.get(f'{{{namespaces["xml"]}}}id') or tbl.attrib.get('id')
                logging.debug(f"Parsed fallback charset table {t_id} -> {added} rows")
                total_added += added

    if not rows and total_added == 0:
        logging.warning('No Specific Character Set entries found in Part 05.')
        pd.DataFrame(columns=['charset_value','name','notes','source_table']).to_sql('dicom_charset', db_conn, if_exists='replace', index=False)
        return

    df = pd.DataFrame(rows)
    # Deduplicate by value: prefer rows with a name, then longer notes
    df['has_name'] = df['name'].fillna('').str.len() > 0
    df['notes_len'] = df['notes'].fillna('').str.len()
    df.sort_values(by=['charset_value','has_name','notes_len'], ascending=[True, False, False], inplace=True)
    df = df.drop_duplicates(subset=['charset_value'], keep='first')
    df = df[['charset_value','name','notes','source_table']]

    df.to_sql('dicom_charset', db_conn, if_exists='replace', index=False)
    logging.info(f'Wrote {len(df)} Specific Character Set rows from PS3.5.')

def update_templates_and_context_groups():
    """
    PS3.16 Templates (TIDs) and Context Groups (CIDs)
    Extracts TID/CID, name, and the section xml:id where they’re defined.
    Outputs:
      - dicom_template(tid, name, sect_id)
      - dicom_context_group(cid, name, sect_id)
    """
    logging.info('Updating Templates (TIDs) and Context Groups (CIDs)')

    if not part_16_root:
        import_part_16()

    # Build a parent map so we can walk up to find the nearest element that has an xml:id
    parent_map = {}
    for p in part_16_root.iter():
        for c in list(p):
            parent_map[c] = p

    def nearest_id(el):
        cur = el
        while cur is not None:
            sid = cur.attrib.get(f'{{{namespaces["xml"]}}}id') or cur.attrib.get('id')
            if sid:
                return sid
            cur = parent_map.get(cur)
        return None

    tid_rows, cid_rows = [], []

    tid_re = re.compile(r'^\s*TID\s+(\d+)\s*[:\-–]?\s*(.*)$', re.IGNORECASE)
    cid_re = re.compile(r'^\s*CID\s+(\d+)\s*[:\-–]?\s*(.*)$', re.IGNORECASE)

    # Look at every title in the document (sections, tables, figures, etc.)
    titles = part_16_root.findall(".//doc:title", namespaces)
    logging.debug(f"Found {len(titles)} titles in PS3.16; scanning for TIDs/CIDs")
    for t in titles:
        txt = extract_text(t) or ""
        if not txt:
            continue

        m_tid = tid_re.match(txt)
        if m_tid:
            tid = m_tid.group(1)
            name = (m_tid.group(2) or '').strip().strip('“”"\'')
            sid = nearest_id(t)  # nearest ancestor id (usually its section)
            tid_rows.append({'tid': tid, 'name': name, 'sect_id': sid})
            continue

        m_cid = cid_re.match(txt)
        if m_cid:
            cid = m_cid.group(1)
            name = (m_cid.group(2) or '').strip().strip('“”"\'')
            sid = nearest_id(t)
            cid_rows.append({'cid': cid, 'name': name, 'sect_id': sid})
            continue

    # De‑dup and write
    tids_df = pd.DataFrame(tid_rows, columns=['tid','name','sect_id'])
    if not tids_df.empty:
        tids_df.drop_duplicates(subset=['tid'], inplace=True)
    tids_df.to_sql('dicom_template', db_conn, if_exists='replace', index=False)

    cids_df = pd.DataFrame(cid_rows, columns=['cid','name','sect_id'])
    if not cids_df.empty:
        cids_df.drop_duplicates(subset=['cid'], inplace=True)
    cids_df.to_sql('dicom_context_group', db_conn, if_exists='replace', index=False)

    logging.info(f'Wrote {len(tids_df)} TIDs and {len(cids_df)} CIDs.')

def update_class_iod_requirements_from_tables():
    """
    Rebuild dicom_class_iod_requirement by joining the normalized tables
    and flattening macro includes recursively.

    Requires:
      - dicom_sop_class(sop_class_uid, iod_sect_id, ...)
      - dicom_iod_module(iod_sect_id, ie, module_name, module_sect_id, usage, condition)
      - dicom_module_attribute(module_sect_id, tag_name, tag, type, desc, list, level, macro_table_id)
      - dicom_macro_attribute(macro_table_id, tag_name, tag, type, desc, list, level, included_macro_table_id)

    Produces (same schema as before):
      sop_class_uid, ie, module, usage, tag, tag_full, level, type,
      type_root, type_parent, tag_name, desc, list
    """
    logging.info('Rebuilding dicom_class_iod_requirement from normalized tables')

    # Ensure inputs exist
    def table_exists(name):
        return pd.read_sql_query(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", db_conn, params=(name,)
        ).shape[0] == 1

    required = [
        'dicom_sop_class', 'dicom_iod_module', 'dicom_module_attribute',
        'dicom_macro', 'dicom_macro_attribute'
    ]
    missing = [t for t in required if not table_exists(t)]
    if missing:
        logging.error(f"Missing input tables: {', '.join(missing)}. Run update_sop_classes(), update_modules(), update_module_attributes(), update_macros() first.")
        # Create empty output to keep downstream stable
        empty_cols = ['sop_class_uid','ie','module','usage','tag','tag_full','level','type','type_root','type_parent','tag_name','desc','list']
        pd.DataFrame(columns=empty_cols).to_sql('dicom_class_iod_requirement', db_conn, if_exists='replace', index=False)
        return

    # Cache readers (preserve original row order via rowid)
    def read_module_attrs(module_sect_id):
        q = """
            SELECT rowid AS _rowid_, tag_name, tag, type, desc, list, level, macro_table_id
            FROM dicom_module_attribute
            WHERE module_sect_id = ?
            ORDER BY _rowid_
        """
        return pd.read_sql_query(q, db_conn, params=(module_sect_id,))

    def read_macro_attrs(macro_id):
        q = """
            SELECT rowid AS _rowid_, tag_name, tag, type, desc, list, level, included_macro_table_id
            FROM dicom_macro_attribute
            WHERE macro_table_id = ?
            ORDER BY _rowid_
        """
        return pd.read_sql_query(q, db_conn, params=(macro_id,))

    def strip_level_prefix(s: str) -> str:
        return re.sub(r'^>+', '', s or '')

    def safe_int(x) -> int:
        try:
            if x is None or x == '':
                return 0
            return int(float(x))
        except Exception:
            return 0

    # Expand a macro to a relative list of attribute rows (cached + cycle-safe)
    macro_rel_cache = {}

    def expand_macro_relative(macro_id: str, visiting=None, depth: int = 0):
        # memoized
        if macro_id in macro_rel_cache:
            return macro_rel_cache[macro_id]

        # init visiting set
        if visiting is None:
            visiting = set()
        # depth guard
        if depth > 100:
            logging.warning(f"Macro expansion depth exceeded for {macro_id}; truncating.")
            return []
        # cycle guard
        if macro_id in visiting:
            logging.warning(f"Detected macro include cycle at {macro_id}; skipping nested expansion.")
            return []

        visiting.add(macro_id)

        df = read_macro_attrs(macro_id)
        if df is None or df.empty:
            visiting.discard(macro_id)
            macro_rel_cache[macro_id] = []
            return []

        out_rows = []
        for _, r in df.iterrows():
            included = r.get('included_macro_table_id')
            has_tag = isinstance(r.get('tag'), str) and len(r.get('tag')) > 0

            if included:
                if included == macro_id:
                    logging.warning(f"{macro_id} includes itself; skipping.")
                    continue

                child_rows = expand_macro_relative(included, visiting=visiting, depth=depth + 1)
                base_off = safe_int(r.get('level')) + 1
                for cr in child_rows:
                    out_rows.append({
                        'rel_level': base_off + safe_int(cr.get('rel_level')),
                        'tag_name_base': cr.get('tag_name_base'),
                        'tag': cr.get('tag'),
                        'type': cr.get('type'),
                        'desc': cr.get('desc'),
                        'list': cr.get('list'),
                    })
            elif has_tag:
                out_rows.append({
                    'rel_level': safe_int(r.get('level')),
                    'tag_name_base': strip_level_prefix(r.get('tag_name')),
                    'tag': r.get('tag'),
                    'type': r.get('type'),
                    'desc': r.get('desc'),
                    'list': r.get('list'),
                })
            # ignore other rows

        visiting.discard(macro_id)
        macro_rel_cache[macro_id] = out_rows
        return out_rows

    # Load SOPs and join to IOD Modules
    sop_df = pd.read_sql_query("SELECT sop_class_uid, iod_sect_id FROM dicom_sop_class", db_conn)
    iod_mod_df = pd.read_sql_query("""
        SELECT iod_sect_id, ie, module_name, module_sect_id, usage, condition
        FROM dicom_iod_module
        ORDER BY iod_sect_id, module_sect_id
    """, db_conn)

    merged = sop_df.merge(iod_mod_df, on='iod_sect_id', how='inner')
    logging.info(f"Building requirements for {merged['sop_class_uid'].nunique()} SOP Classes, {len(merged)} IOD-Module rows")

    # Start fresh
    db_conn.execute("DROP TABLE IF EXISTS dicom_class_iod_requirement")
    db_conn.commit()

    append_batches = []

    for _, row in merged.iterrows():
        sop_uid = row.sop_class_uid
        module_name = row.module_name
        module_sect_id = row.module_sect_id
        ie = row.ie
        usage = row.usage

        mdf = read_module_attrs(module_sect_id)
        if mdf.empty:
            continue

        flat_rows = []  # will be in table order, includes expanded in place

        for _, mr in mdf.iterrows():
            included_macro = mr.get('macro_table_id')
            rel_level = int(mr.get('level') or 0)

            if included_macro:
                for cr in expand_macro_relative(included_macro):
                    abs_level = safe_int(rel_level) + 1 + safe_int(cr['rel_level'])
                    flat_rows.append({
                        'tag_name': '>' * abs_level + (cr.get('tag_name_base') or ''),
                        'tag': cr.get('tag'),
                        'type': cr.get('type'),
                        'desc': cr.get('desc'),
                        'list': cr.get('list'),
                    })
            else:
                if isinstance(mr.get('tag'), str) and mr.get('tag') != '':
                    abs_level = rel_level
                    flat_rows.append({
                        'tag_name': '>' * abs_level + strip_level_prefix(mr.get('tag_name')),
                        'tag': mr.get('tag'),
                        'type': mr.get('type'),
                        'desc': mr.get('desc'),
                        'list': mr.get('list'),
                    })

        if not flat_rows:
            continue

        attrs_df = pd.DataFrame(flat_rows, columns=['tag_name','tag','type','desc','list'])

        # Recompute the derived columns the same way as before
        formatted_df = format_table_data(attrs_df)
        # Add SOP + module metadata
        formatted_df.insert(0, 'usage', usage)
        formatted_df.insert(0, 'module', module_name)
        formatted_df.insert(0, 'ie', ie)
        formatted_df.insert(0, 'sop_class_uid', sop_uid)

        # Arrange columns like the legacy output
        formatted_df = formatted_df[['sop_class_uid','ie','module','usage',
                                     'tag','tag_full','level','type','type_root','type_parent',
                                     'tag_name','desc','list']]

        append_batches.append(formatted_df)

        # Write in batches to keep memory down
        if sum(len(b) for b in append_batches) >= 200000:
            pd.concat(append_batches, ignore_index=True).to_sql("dicom_class_iod_requirement", db_conn, if_exists='append', index=False)
            append_batches = []

    if append_batches:
        pd.concat(append_batches, ignore_index=True).to_sql("dicom_class_iod_requirement", db_conn, if_exists='append', index=False)

    logging.info("dicom_class_iod_requirement rebuilt.")

def update_class_iod_requirements_tags():
    """
    Create dicom_class_iod_requirement_tag with two columns:
      - tag_full
      - tag  (one component from tag_full split on '|')
    """
    logging.info('Creating dicom_class_iod_requirement_tag')

    src = pd.read_sql_query(
        "SELECT DISTINCT tag_full FROM dicom_class_iod_requirement "
        "WHERE tag_full IS NOT NULL AND tag_full <> ''",
        db_conn
    )

    if src.empty:
        pd.DataFrame(columns=['tag_full','tag']).to_sql(
            'dicom_class_iod_requirement_tag', db_conn, if_exists='replace', index=False
        )
        logging.info('No tag_full values found.')
        return

    out = (
        src.assign(tag=src['tag_full'].str.split('|'))
           .explode('tag')
           .reset_index(drop=True)
    )
    out['tag'] = out['tag'].astype(str).str.strip()
    out = out[out['tag'] != '']

    out[['tag_full','tag']].drop_duplicates().to_sql(
        'dicom_class_iod_requirement_tag', db_conn, if_exists='replace', index=False
    )
    logging.info(f"Wrote {len(out.drop_duplicates())} rows to dicom_class_iod_requirement_tag.")

# --------------------------------------------------------

def create_indexes():
    cur = db_conn.cursor()
    def has_table(name: str) -> bool:
        return cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    # dicom_element
    if has_table('dicom_element'):
        db_conn.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_elements_tag ON dicom_element(tag);
        CREATE INDEX IF NOT EXISTS idx_elements_keyword ON dicom_element(keyword);
        """)

    # SOP classes and IOD/modules
    if has_table('dicom_sop_class'):
        db_conn.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_sop_uid ON dicom_sop_class(sop_class_uid);
        CREATE INDEX IF NOT EXISTS idx_sop_iod ON dicom_sop_class(iod_sect_id);
        """)
    if has_table('dicom_iod_module'):
        db_conn.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_iod_mod ON dicom_iod_module(iod_sect_id, module_sect_id);
        CREATE INDEX IF NOT EXISTS idx_iod_mod_module ON dicom_iod_module(module_sect_id);
        CREATE INDEX IF NOT EXISTS idx_iod_mod_iod ON dicom_iod_module(iod_sect_id);
        """)
    if has_table('dicom_module'):
        db_conn.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_modules_id ON dicom_module(module_sect_id);
        CREATE INDEX IF NOT EXISTS idx_modules_name ON dicom_module(module_name);
        """)

    # Module attributes (includes embedded)
    if has_table('dicom_module_attribute'):
        db_conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_mod_attrs_owner ON dicom_module_attribute(module_sect_id);
        CREATE INDEX IF NOT EXISTS idx_mod_attrs_owner_level ON dicom_module_attribute(module_sect_id, level);
        CREATE INDEX IF NOT EXISTS idx_mod_attrs_tag ON dicom_module_attribute(tag);
        CREATE INDEX IF NOT EXISTS idx_mod_attrs_macro ON dicom_module_attribute(macro_table_id);
        CREATE INDEX IF NOT EXISTS idx_mod_attrs_owner_tag ON dicom_module_attribute(module_sect_id, tag);
        """)

    # Macros and macro attributes (includes embedded)
    if has_table('dicom_macro'):
        db_conn.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_macros_id ON dicom_macro(macro_table_id);
        CREATE INDEX IF NOT EXISTS idx_macros_name ON dicom_macro(macro_name);
        """)
    if has_table('dicom_macro_attribute'):
        db_conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_macro_attrs_owner ON dicom_macro_attribute(macro_table_id);
        CREATE INDEX IF NOT EXISTS idx_macro_attrs_owner_level ON dicom_macro_attribute(macro_table_id, level);
        CREATE INDEX IF NOT EXISTS idx_macro_attrs_tag ON dicom_macro_attribute(tag);
        CREATE INDEX IF NOT EXISTS idx_macro_attrs_included ON dicom_macro_attribute(included_macro_table_id);
        CREATE INDEX IF NOT EXISTS idx_macro_attrs_owner_included ON dicom_macro_attribute(macro_table_id, included_macro_table_id);
        """)

    # # Class IOD requirements (flattened view, optional)
    # if has_table('dicom_class_iod_requirement'):
    #     db_conn.executescript("""
    #     CREATE INDEX IF NOT EXISTS idx_req_sop ON dicom_class_iod_requirement(sop_class_uid);
    #     CREATE INDEX IF NOT EXISTS idx_req_sop_mod ON dicom_class_iod_requirement(sop_class_uid, module);
    #     CREATE INDEX IF NOT EXISTS idx_req_tag ON dicom_class_iod_requirement(tag);
    #     CREATE INDEX IF NOT EXISTS idx_req_tag_full ON dicom_class_iod_requirement(tag_full);
    #     """)

    # Safe private (optional join to elements by parsed private tag)
    if has_table('dicom_safe_private'):
        db_conn.executescript("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_safe_private_pt ON dicom_safe_private(pt_tag);
        """)

    # De-id, templates, etc. (mostly lookup; indexing keys only)
    if has_table('dicom_deid_action_code'):
        db_conn.executescript("CREATE INDEX IF NOT EXISTS idx_deid_codes ON dicom_deid_action_code(code);")
    if has_table('dicom_deid_profile'):
        db_conn.executescript("CREATE INDEX IF NOT EXISTS idx_deid_profiles_name ON dicom_deid_profile(name);")
    # if has_table('dicom_template'):
    #     db_conn.executescript("CREATE INDEX IF NOT EXISTS idx_templates_tid ON dicom_template(tid);")
    # if has_table('dicom_context_group'):
    #     db_conn.executescript("CREATE INDEX IF NOT EXISTS idx_context_groups_cid ON dicom_context_group(cid);")

    # # Character sets
    # if has_table('dicom_charset'):
    #     db_conn.executescript("""
    #     CREATE UNIQUE INDEX IF NOT EXISTS ux_charsets_value ON dicom_charset(charset_value);
    #     CREATE INDEX IF NOT EXISTS idx_charsets_name ON dicom_charset(name);
    #     """)

    db_conn.commit()



#########################################################
#########################################################
# RUN
#########################################################
#########################################################

def initialize_logging(log_level = logging.INFO, 
                       log_directory = None, 
                       program_name = None) -> None:
    """
    Initialize logging with given log level, log directory, and program name.
    
    Args:
        log_level (int): Logging level, e.g., logging.INFO, logging.DEBUG.
        log_directory (str, optional): Directory to save log files. 
                                       If None, only console logging is enabled.
        program_name (str, optional): Name of the program to include in log filename.

    Raises:
        ValueError: If `log_level` is not a valid logging level.
    """

    # Validate log_level
    if not isinstance(log_level, int) or log_level not in range(0, 60):
        raise ValueError("Invalid log level provided")

    handlers = [logging.StreamHandler()]

    if log_directory:
        # Ensure log directory exists
        os.makedirs(log_directory, exist_ok=True)

        # Format log file name
        start_date = datetime.now().strftime("%Y%m%d%H%M%S")
        log_filename = f"{start_date}-{program_name}-execution.log" if program_name else f"{start_date}-execution.log"
        log_file_path = os.path.join(log_directory, log_filename)

        # Add FileHandler
        handlers.append(logging.FileHandler(log_file_path, 'a'))

    # Configure logging
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers
    )

def main():
    multiprocessing.set_start_method("spawn", True)
    initialize_logging(log_level = logging.DEBUG, 
                       log_directory = log_folder,
                       program_name = 'parse_standard')

    update_elements()
    update_sop_classes()
    update_deid_profiles()
    update_safe_private()

    update_modules()
    update_module_attributes()
    update_macros()
    update_uids()

    update_charsets()
    update_templates_and_context_groups()

    create_indexes()

    update_class_iod_requirements_from_tables()
    update_class_iod_requirements_tags()
    


    # Optional: keep legacy flattened outputs while you transition
    # update_class_modules()
    # update_class_requirements()
    # output_conditional_blobs()
    # update_conditional_requirements()

    db_conn.close()
    
    return None

if __name__ == "__main__":

    main()