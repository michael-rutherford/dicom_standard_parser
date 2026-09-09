import os
import requests
import xmltodict
import sqlite3 as sql
import pandas as pd
import numpy as np
import copy
import collections

#########################################################
# Script variables
#########################################################

# SUPERSEDED by standard/parse_dicom_standard.py. Kept for reference only.
# Set to your local parsed-database folder if you ever need to run this.
data_folder = r''
db_conn = sql.connect(f'{data_folder}\\dicom_standard_parsed.db')

part_03_dict = None
part_04_dict = None
part_06_dict = None
part_15_dict = None

########################################################
# Import functions
#########################################################

def import_part_03():
    global part_03_dict
    part_03_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part03/part03.xml"
    part_03_xml_response = requests.get(part_03_xml_url)
    part_03_dict = xmltodict.parse(part_03_xml_response.content)

def import_part_04():
    global part_04_dict
    part_04_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part04/part04.xml"
    part_04_xml_response = requests.get(part_04_xml_url)
    part_04_dict = xmltodict.parse(part_04_xml_response.content)

def import_part_06():
    global part_06_dict
    part_06_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part06/part06.xml"
    part_06_xml_response = requests.get(part_06_xml_url)
    part_06_dict = xmltodict.parse(part_06_xml_response.content)

def import_part_15():
    global part_15_dict
    part_15_xml_url = "http://dicom.nema.org/medical/dicom/current/source/docbook/part15/part15.xml"
    part_15_xml_response = requests.get(part_15_xml_url)
    part_15_dict = xmltodict.parse(part_15_xml_response.content)

########################################################
# Script functions
#########################################################

def get_table(table_dict, location = None, table_name = None):

    table_header = None
    table_body = None

    chapter_name = location[0:1]
    chapter_rec = next(chapter for chapter in table_dict['book']['chapter'] if chapter['@xml:id'] == f'chapter_{chapter_name}')
    
    section_nums = filter(bool, location[2:].split('.'))
    section_name = f'sect_{chapter_name}'
    section_rec = chapter_rec

    for section_num in section_nums:
        section_name = f'{section_name}.{section_num}'

        if '@xml:id' in section_rec['section']:
            section_rec = section_rec['section']
        else:
            section_rec = next(section for section in section_rec['section'] if section['@xml:id'] == section_name)
            
    if table_name == 'E.3.10-1':
        section_rec = section_rec['note']['orderedlist']['listitem'][0]

    tables = section_rec['table']

    if 'tbody' in tables:
        tables = [tables]

    if table_name is not None:

        table = next(table for table in tables if table['@xml:id'] == f'table_{table_name}')
        table_header = table['thead']['tr']['th']
        table_body = table['tbody']['tr']

    else:

        for index, table in enumerate(tables):

            if table_header is None:
                table_header = table['thead']['tr']['th']

            if table_body is None:
                table_body = table['tbody']['tr']
            else:
                if isinstance(table['tbody']['tr'], dict):
                    table['tbody']['tr'] = [table['tbody']['tr']]
                if isinstance(table_body, dict):
                    table_body = [table_body]
                table_body = table_body + table['tbody']['tr']

    return table_header, table_body

def get_table_data(header, body, table_dict = None, table_level = '', module = None, usage = None):

    # table header

    header_cols = []
    header_rowpans = []
    header_values = []

    for column in header:

        col_name = 'comment'

        if 'para' in column:
            parameter = column['para']

            if '#text' in parameter:
                col_name = parameter['#text'].lower().replace('.','').replace(' ','_')

            elif 'emphasis' in parameter:

                if '#text' in parameter['emphasis']:
                    col_name = parameter['emphasis']['#text'].lower().replace('.','').replace(' ','_')

        header_cols.append(col_name)
        header_rowpans.append(1)
        header_values.append(np.nan)

    # table body

    if table_dict:
        body_rows = table_dict
        iter = len(table_dict)
    else:
        body_rows = {}
        iter = 0

    for row_index, row in enumerate(body):

        body_rows[iter] = {}

        columns = row['td']

        if '@colspan' in columns:
            columns = [columns]

        if int(columns[0]['@colspan']) > 1: 
            if isinstance(row['td'], list):
                link_text = row['td'][0]['para']['emphasis']['#text']
                link_table = row['td'][0]['para']['emphasis']['xref']['@linkend']
            else:
                link_text = row['td']['para']['emphasis']['#text']
                link_table = row['td']['para']['emphasis']['xref']['@linkend']
                
            level_count = int(link_text.count('>'))
            level = '>' * level_count
            table = link_table.replace('table_','')
        else:

            col_adjust = 0

            for col_index, column in enumerate(header_cols):

                col_value = np.nan
                col_rowspan = 1

                if header_rowpans[col_index] > 1:

                    col_rowspan = header_rowpans[col_index] - 1
                    col_adjust += 1
                    col_value = header_values[col_index]

                else:

                    adjusted_index = col_index - col_adjust

                    if columns[adjusted_index]:

                        if '@rowspan' in columns[adjusted_index]:
                            col_rowspan = int(columns[adjusted_index]['@rowspan'])

                        if 'para' in columns[adjusted_index]: # and (columns[adjusted_index]['para'] != None):

                            #if columns[adjusted_index]['para'] == None:
                            #    a = 'a'

                            parameter = columns[adjusted_index]['para']

                            if parameter:
                                if '#text' in parameter:
                                    col_value = parameter['#text']
                                elif 'emphasis' in parameter:
                                    if '#text' in parameter['emphasis']:
                                        col_value = parameter['emphasis']['#text']
                                elif 'xref' in parameter:
                                    col_value = parameter['xref']['@linkend']
                                else:
                                    if isinstance(parameter, str):
                                        col_value = parameter
            
                header_values[col_index] = col_value
                body_rows[iter][column] = col_value
                header_rowpans[col_index] = col_rowspan

            iter += 1

    return body_rows

def format_table_data(data_df):

    work_df = data_df.copy()
    work_df['level'] = 0
    work_df['tag_full'] = ''
    work_df['type_root'] = ''
    work_df['type_parent'] = ''

    running_capture = []

    for index, row in work_df.iterrows():
        
        if not pd.isna(row.tag):
            # level
            # --------------------------
            level = int(row.attribute_name.count('>'))
            work_df.at[index,'level'] = level

            running_capture.insert(level, (row.tag, row.type))

            # full tag
            # --------------------------
            tag_full = ''

            for num in range(0, level + 1, 1):
                tag_full += running_capture[num][0]

            work_df.at[index,'tag_full'] = tag_full.replace('><','>|<')

            # type root and parent
            # --------------------------
            work_df.at[index,'type_root'] = running_capture[0][1]

            if not level == 0:
                work_df.at[index,'type_parent'] = running_capture[level-1][1]
            else:
                work_df.at[index,'type_parent'] = np.nan

    return work_df[~pd.isna(work_df.tag)]

def remove_dup_data(data_df):

    types = ['1','2','1C','2C','3']
    index_to_drop = []

    work_df = data_df.copy()

    for index, row in work_df.iterrows():

        print(row.tag)

        check_df = work_df[work_df.tag_full == row.tag_full]

        if not len(check_df) == 1:

            print('multiple entries found')

            index_to_keep = 0

            for type in types:

                type_df = check_df[check_df.type == type]

                if len(type_df) > 0:

                    index_to_keep = type_df.index[0]

                    print(f'best type: {type} on index: {str(index_to_keep)}')

                    for check_index in check_df.index:

                        if not check_index == index_to_keep:

                            index_to_drop.append(check_index)

                            print(f'index to drop: {check_index}')

                    break

    print('dropping indexes')
    work_df.drop(index_to_drop, inplace=True)

    return work_df

def get_module_table(table_dict, location, table_name):

    table_header, table_body = get_table(table_dict, location, table_name)
    tables_rows = get_table_data(table_header, table_body)
    table_df = pd.DataFrame.from_dict(tables_rows, orient='index')

    if 'comment' in table_df.columns:
        table_df['comment'] = table_df.apply(lambda row : row['usage'][4:], axis = 1)

    # TODO - FIX THIS - caused by rowspan > 1 in get_table_data
    if 'usage' in table_df.columns:
        table_df['usage'] = table_df.apply(lambda row : row['usage'][:1] if not pd.isnull(row['usage']) else 'C', axis = 1)

    return table_df

def process_module_table(module_df):

    table_rows = None
    table_level = ''

    #modules = module_df[module_df.usage == 'M']

    mod_dfs = []

    for index, row in module_df.iterrows():

        location = row.reference[5:]

        table_header, table_body = get_table(part_03_dict, location)

        #table_rows = get_table_data(table_header, table_body, table_rows, table_level)
        table_rows = get_table_data(table_header, table_body)
        
        mod_df = pd.DataFrame.from_dict(table_rows, orient='index')
        mod_df['module'] = row.module
        mod_df['usage'] = row.usage
        
        mod_dfs.append(mod_df)

    #table_df = pd.DataFrame.from_dict(table_rows, orient='index')
    table_df = pd.concat(mod_dfs)
    table_df.reset_index(drop=True, inplace=True)
    
    table_df.tag = '<' + table_df.tag + '>'
    #table_df.to_csv('test.csv')
    table_df = format_table_data(table_df)
    #table_df = remove_dup_data(table_df)
    table_df.sort_values(by='tag_full', ascending=True, inplace=True)
    table_df.reset_index(drop=True, inplace=True)
    #table_df = table_df[['tag','tag_full','level','type','type_root','type_parent','attribute_name','attribute_description']]
    table_df = table_df[['module','usage','tag','tag_full','level','type','type_root','type_parent','attribute_name','attribute_description']]

    return table_df

#########################################################
#########################################################
# Update DICOM items
#########################################################
#########################################################

def update_dicom_dictionary():
    #########################################################
    #########################################################
    # Update DICOM Data Dictionary
    #########################################################
    #########################################################

    print('Updating Dicom Dictionary')

    #-----------------------------------------------------------------------
    # From Dicom Standard
    #-----------------------------------------------------------------------

    # Part 06
    # Table 6-1
    # http://dicom.nema.org/medical/dicom/current/output/html/part06.html#table_6-1

    if not part_06_dict:
        import_part_06()

    location = '6'
    table_name = '6-1'
    table_output = 'dicom_dictionary'

    table_header, table_body = get_table(part_06_dict, location, table_name)
    table_rows = get_table_data(table_header, table_body)
    table_df = pd.DataFrame.from_dict(table_rows, orient='index')
    table_df.tag = '<' + table_df.tag + '>'
    table_df.to_sql(table_output, db_conn, if_exists='replace')

    #-----------------------------------------------------------------------
    # From innolitics
    #-----------------------------------------------------------------------

    #table_output = 'dicom_tags'

    #table_url = "https://raw.githubusercontent.com/innolitics/dicom-standard/master/standard/attributes.json"
    #table_response = requests.get(table_url)
    #if table_response.status_code == 200:
    #    table_dict = table_response.json()

    #table_df = pd.DataFrame.from_dict(table_dict)
    #table_df = table_df.rename(columns={'valueRepresentation':'vr','valueMultiplicity':'vm'})
    #table_df.tag = '<' + table_df.tag + '>'
    #table_df.to_sql(table_output, db_conn, if_exists='replace')

def update_sop_classes():
    #########################################################
    #########################################################
    # Update SOP Classes
    #########################################################
    #########################################################

    print('Updating SOP Classes')

    #-----------------------------------------------------------------------
    # From Dicom Standard
    #-----------------------------------------------------------------------

    # Part 04
    # Table B.5-1
    # https://dicom.nema.org/medical/dicom/current/output/chtml/part04/sect_B.5.html#table_B.5-1

    if not part_04_dict:
        import_part_04()

    location = 'B.5'
    table_name = 'B.5-1'
    table_output = 'dicom_sop_classes'

    table_header, table_body = get_table(part_04_dict, location, table_name)
    table_rows = get_table_data(table_header, table_body)
    table_df = pd.DataFrame.from_dict(table_rows, orient='index')
    table_df = table_df[['sop_class_name','sop_class_uid']]
    table_df.sop_class_uid = '<' + table_df.sop_class_uid + '>'
    table_df.to_sql(table_output, db_conn, if_exists='replace')

    #-----------------------------------------------------------------------
    # From innolitics
    #-----------------------------------------------------------------------

    #table_output = 'dicom_sop_classes'

    #table_url = "https://raw.githubusercontent.com/innolitics/dicom-standard/master/standard/sops.json"
    #table_response = requests.get(table_url)
    #if table_response.status_code == 200:
    #    table_dict = table_response.json()

    #table_df = pd.DataFrame.from_dict(table_dict)
    #table_df = table_df.rename(columns={'name':'sop_class_name','id':'sop_class_uid'})
    #table_df.sop_class_uid = '<' + table_df.sop_class_uid + '>'
    #table_df.to_sql(table_output, db_conn, if_exists='replace')

def update_deid_profiles():
    #########################################################
    #########################################################
    # Update DICOM Deidentification Profiles
    #########################################################
    #########################################################

    print('Updating Deid Profiles')

    #-----------------------------------------------------------------------
    # From Dicom Standard
    #-----------------------------------------------------------------------

    # Part 15
    # Table E.1-1a
    # http://dicom.nema.org/medical/dicom/current/output/html/part15.html#table_E.1-1a
    # Table E.1-1
    # http://dicom.nema.org/medical/dicom/current/output/html/part15.html#table_E.1-1

    if not part_15_dict:
        import_part_15()

    location = 'E.1.1'
    table_name = 'E.1-1'
    table_output = 'dicom_deid_profiles'

    table_header, table_body = get_table(part_15_dict, location, table_name)
    table_rows = get_table_data(table_header, table_body)
    table_df = pd.DataFrame.from_dict(table_rows, orient='index')
    table_df.tag = '<' + table_df.tag + '>'
    table_df.to_sql(table_output, db_conn, if_exists='replace')

    #-----------------------------------------------------------------------
    # From innolitics
    #-----------------------------------------------------------------------

    #table_output = 'dicom_deid_profiles2'

    #table_url = "https://raw.githubusercontent.com/innolitics/dicom-standard/master/standard/confidentiality_profile_attributes.json"
    #table_response = requests.get(table_url)
    #if table_response.status_code == 200:
    #    table_dict = table_response.json()

    #table_df = pd.DataFrame.from_dict(table_dict)
    #table_df = table_df.rename(columns={'name':'attribute_name',
    #                                    'stdCompIOD':'std_comp_iod',
    #                                    'basicProfile':'basic_prof',
    #                                    'rtnSafePrivOpt':'rtn_safe_priv_opt',
    #                                    'rtnUIDsOpt':'rtn_uids_opt',
    #                                    'rtnDevIdOpt':'rtn_dev_id_opt',
    #                                    'rtnInstIdOpt':'rtn_inst_id_opt',
    #                                    'rtnPatCharsOpt':'rtn_pat_chars_opt',
    #                                    'rtnLongFullDatesOpt':'rtn_long_full_dates_opt',
    #                                    'rtnLongModifDatesOpt':'rtn_long_modif_dates_opt',
    #                                    'cleanDescOpt':'clean_desc_opt',
    #                                    'cleanStructContOpt':'clean_struct_cont_opt',
    #                                    'cleanGraphOpt':'clean_graph_opt'})

    #table_df = table_df[['id','attribute_name','tag','std_comp_iod','basic_prof','rtn_safe_priv_opt','rtn_uids_opt','rtn_dev_id_opt',
    #                     'rtn_inst_id_opt','rtn_pat_chars_opt','rtn_long_full_dates_opt','rtn_long_modif_dates_opt','clean_desc_opt',
    #                     'clean_struct_cont_opt','clean_graph_opt']]
    #table_df.tag = '<' + table_df.tag + '>'
    #table_df.to_sql(table_output, db_conn, if_exists='replace')

def update_safe_private():
    #########################################################
    #########################################################
    # Update Safe Private
    #########################################################
    #########################################################

    print('Updating Safe Private Elements')

    #-----------------------------------------------------------------------
    # From Dicom Standard
    #-----------------------------------------------------------------------

    # Part 15
    # Table E.3.10-1
    # https://dicom.nema.org/medical/dicom/current/output/html/part15.html#table_E.3.10-1

    if not part_15_dict:
        import_part_15()

    location = 'E.3.10'
    table_name = 'E.3.10-1'
    table_output = 'dicom_safe_private'

    table_header, table_body = get_table(part_15_dict, location, table_name)
    table_rows = get_table_data(table_header, table_body)
    table_df = pd.DataFrame.from_dict(table_rows, orient='index')
    
    def format_tag(tag_str):
        inside_parentheses = tag_str[tag_str.find("(")+1:tag_str.find(")")]
        group, element = inside_parentheses.split(',')
        creator = tag_str[tag_str.find(")")+1:].strip()
        group = group.strip().upper()
        element = element.replace('xx', '').strip().upper()
        return f"<({group.upper()},\"{creator}\",{element.upper()})>"

    table_df['pt_tag'] = table_df['data_element'] + table_df['private_creator']
    table_df['pt_tag'] = table_df['pt_tag'].apply(format_tag)
    table_df = table_df[['pt_tag', 'data_element', 'private_creator', 'vr', 'vm', 'meaning']]

    #table_df = table_df[['sop_class_name','sop_class_uid']]
    #table_df.sop_class_uid = '<' + table_df.sop_class_uid + '>'
    table_df.to_sql(table_output, db_conn, if_exists='replace')
    



#########################################################
#########################################################
# Modality Specific Requirements
#########################################################
#########################################################

def update_cr():

    ##---------------------------------------------------------------
    ## CR
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.2.3.html#table_A.2-1
    ##---------------------------------------------------------------
    
    if not part_03_dict:
        import_part_03()

    location = 'A.2.3'
    table_name = 'A.2-1'
    module_output = 'dicom_std_cr_req_modules'
    req_output = 'dicom_std_cr_req'

    print('Extracting CR IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing CR IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')
    
def update_ct():
    ##---------------------------------------------------------------
    ## CT
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.3.3.html#table_A.3-1
    ##---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.3.3'
    table_name = 'A.3-1'
    module_output = 'dicom_std_ct_req_modules'
    req_output = 'dicom_std_ct_req'

    print('Extracting CT IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)    
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing CT IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_dx():
    ##---------------------------------------------------------------
    ## DX
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.26.3.html#table_A.26-1
    ##---------------------------------------------------------------
    
    if not part_03_dict:
        import_part_03()

    location = 'A.26.3'
    table_name = 'A.26-1'
    module_output = 'dicom_std_dx_req_modules'
    req_output = 'dicom_std_dx_req'

    print('Extracting DX IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing DX IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_mg():
    #---------------------------------------------------------------
    # MG
    # http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.27.3.html#table_A.27-1
    #---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.27.3'
    table_name = 'A.27-1'
    module_output = 'dicom_std_mg_req_modules'
    req_output = 'dicom_std_mg_req'

    print('Extracting MG IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing MG IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_mr():
    ##---------------------------------------------------------------
    ## MR
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.4.3.html#table_A.4-1
    ##---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.4.3'
    table_name = 'A.4-1'
    module_output = 'dicom_std_mr_req_modules'
    req_output = 'dicom_std_mr_req'

    print('Extracting MR IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing MR IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')
    
def update_nm():
    #---------------------------------------------------------------
    # NM
    # http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.5.4.html#table_A.5-1
    #---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.5.4'
    table_name = 'A.5-1'
    module_output = 'dicom_std_nm_req_modules'
    req_output = 'dicom_std_nm_req'

    print('Extracting NM IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing NM IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')
    
def update_pt():
    ##---------------------------------------------------------------
    ## PT
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.21.3.html#table_A.21.3-1
    ##---------------------------------------------------------------
    
    if not part_03_dict:
        import_part_03()

    location = 'A.21.3'
    table_name = 'A.21.3-1'
    module_output = 'dicom_std_pt_req_modules'
    req_output = 'dicom_std_pt_req'

    print('Extracting PT IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing PT IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_rtdose():
    ##---------------------------------------------------------------
    ## RTDOSE
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.18.3.html#table_A.18.3-1
    ##---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.18.3'
    table_name = 'A.18.3-1'
    module_output = 'dicom_std_rtdose_req_modules'
    req_output = 'dicom_std_rtdose_req'

    print('Extracting RTDose IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing RTDose IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_rtstruct():
    ##---------------------------------------------------------------
    ## RTSTRUCT
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.19.3.html#table_A.19.3-1

    if not part_03_dict:
        import_part_03()

    location = 'A.19.3'
    table_name = 'A.19.3-1'
    module_output = 'dicom_std_rtstruct_req_modules'
    req_output = 'dicom_std_rtstruct_req'

    print('Extracting RTStruct IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing RTStruct IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_rtplan():
    ##---------------------------------------------------------------
    ## RTPLAN
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.20.3.html#table_A.20.3-1
    ##---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.20.3'
    table_name = 'A.20.3-1'
    module_output = 'dicom_std_rtplan_req_modules'
    req_output = 'dicom_std_rtplan_req'

    print('Extracting RTPlan IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing RTPlan IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

# def update_rtimage():
#     ##---------------------------------------------------------------
#     ## RTPLAN
#     ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.20.3.html#table_A.20.3-1
#     ##---------------------------------------------------------------

#     if not part_03_dict:
#         import_part_03()

#     location = 'A.20.3'
#     table_name = 'A.20.3-1'
#     module_output = 'dicom_std_rtimage_req_modules'
#     req_output = 'dicom_std_rtimage_req'

#     print('Extracting RTImage IOD Modules')
#     req_module_df = get_module_table(part_03_dict, location, table_name)
#     req_module_df.to_sql(module_output, db_conn, if_exists='replace')

#     print('Processing RTImage IOD Modules')
#     req_df = process_module_table(req_module_df)
#     req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_sr():
    ##---------------------------------------------------------------
    ## SR
    ## BASIC
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.35.html#table_A.35.1-1
    ## ENHANCED
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.35.2.3.html#table_A.35.2-1
    ## COMPREHENSIVE
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.35.3.3.html#table_A.35.3-1
    ##---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.35.3.3'
    table_name = 'A.35.3-1'
    module_output = 'dicom_std_sr_req_modules'
    req_output = 'dicom_std_sr_req'

    print('Extracting SR IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing SR IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_seg():
    ##---------------------------------------------------------------
    ## SEG
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.51.3.html#table_A.51-1
    ##---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.51.3'
    table_name = 'A.51-1'
    module_output = 'dicom_std_seg_req_modules'
    req_output = 'dicom_std_seg_req'

    print('Extracting SEG IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing SEG IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def update_us():
    ##---------------------------------------------------------------
    ## US
    ## http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.6.4.html#table_A.6-1
    ##---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.6.4'
    table_name = 'A.6-1'
    module_output = 'dicom_std_us_req_modules'
    req_output = 'dicom_std_us_req'

    print('Extracting US IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing US IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')
    
def update_wsl():
    ##---------------------------------------------------------------
    ## WSL
    ## https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.32.8.3.html#table_A.32.8-1
    ##---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.32.8.3'
    table_name = 'A.32.8-1'
    module_output = 'dicom_std_wsl_req_modules'
    req_output = 'dicom_std_wsl_req'

    print('Extracting WSL IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing WSL IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')
    
def update_xa():
    #---------------------------------------------------------------
    # xa
    # http://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_A.14.3.html#table_A.14-1
    #---------------------------------------------------------------

    if not part_03_dict:
        import_part_03()

    location = 'A.14.3'
    table_name = 'A.14-1'
    module_output = 'dicom_std_xa_req_modules'
    req_output = 'dicom_std_xa_req'

    print('Extracting XA IOD Modules')
    req_module_df = get_module_table(part_03_dict, location, table_name)
    req_module_df.to_sql(module_output, db_conn, if_exists='replace')

    print('Processing XA IOD Modules')
    req_df = process_module_table(req_module_df)
    req_df.to_sql(req_output, db_conn, if_exists='replace')

def extract_to_excel():

    print('Extracting to Excel')
    
    out_path = os.path.join(data_folder, "dicom_standard_parsed_v2.xlsx")
    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
    
        dd_df = pd.read_sql_query("SELECT * FROM dicom_dictionary", db_conn)
        dd_df.to_excel(writer, sheet_name='dicom_dictionary', index=False)
        
        class_df = pd.read_sql_query("SELECT * FROM dicom_sop_classes", db_conn)
        class_df.to_excel(writer, sheet_name='dicom_sop_classes', index=False)
        
        deid_df = pd.read_sql_query("SELECT * FROM dicom_deid_profiles", db_conn)
        deid_df.to_excel(writer, sheet_name='dicom_deid_profiles', index=False)

        cr_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_cr_req_modules", db_conn)
        cr_mod_df.to_excel(writer, sheet_name='cr_mod', index=False)
        
        cr_req_df = pd.read_sql_query("SELECT * FROM dicom_std_cr_req", db_conn)
        cr_req_df.to_excel(writer, sheet_name='cr_req', index=False)
    
        ct_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_ct_req_modules", db_conn)
        ct_mod_df.to_excel(writer, sheet_name='ct_mod', index=False)
        
        ct_req_df = pd.read_sql_query("SELECT * FROM dicom_std_ct_req", db_conn)
        ct_req_df.to_excel(writer, sheet_name='ct_req', index=False)
        
        dx_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_dx_req_modules", db_conn)
        dx_mod_df.to_excel(writer, sheet_name='dx_mod', index=False)

        dx_req_df = pd.read_sql_query("SELECT * FROM dicom_std_dx_req", db_conn)
        dx_req_df.to_excel(writer, sheet_name='dx_req', index=False)

        mg_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_mg_req_modules", db_conn)
        mg_mod_df.to_excel(writer, sheet_name='mg_mod', index=False)

        mg_req_df = pd.read_sql_query("SELECT * FROM dicom_std_mg_req", db_conn)
        mg_req_df.to_excel(writer, sheet_name='mg_req', index=False)

        mr_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_mr_req_modules", db_conn)
        mr_mod_df.to_excel(writer, sheet_name='mr_mod', index=False)

        mr_req_df = pd.read_sql_query("SELECT * FROM dicom_std_mr_req", db_conn)
        mr_req_df.to_excel(writer, sheet_name='mr_req', index=False)

        nm_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_nm_req_modules", db_conn)
        nm_mod_df.to_excel(writer, sheet_name='nm_mod', index=False)

        nm_req_df = pd.read_sql_query("SELECT * FROM dicom_std_nm_req", db_conn)
        nm_req_df.to_excel(writer, sheet_name='nm_req', index=False)

        pt_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_pt_req_modules", db_conn)
        pt_mod_df.to_excel(writer, sheet_name='pt_mod', index=False)

        pt_req_df = pd.read_sql_query("SELECT * FROM dicom_std_pt_req", db_conn)
        pt_req_df.to_excel(writer, sheet_name='pt_req', index=False)

        rtdose_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_rtdose_req_modules", db_conn)
        rtdose_mod_df.to_excel(writer, sheet_name='rtdose_mod', index=False)

        rtdose_req_df = pd.read_sql_query("SELECT * FROM dicom_std_rtdose_req", db_conn)
        rtdose_req_df.to_excel(writer, sheet_name='rtdose_req', index=False)

        rtplan_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_rtplan_req_modules", db_conn)
        rtplan_mod_df.to_excel(writer, sheet_name='rtplan_mod', index=False)

        rtplan_req_df = pd.read_sql_query("SELECT * FROM dicom_std_rtplan_req", db_conn)
        rtplan_req_df.to_excel(writer, sheet_name='rtplan_req', index=False)

        rtstruct_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_rtstruct_req_modules", db_conn)
        rtstruct_mod_df.to_excel(writer, sheet_name='rtstruct_mod', index=False)

        rtstruct_req_df = pd.read_sql_query("SELECT * FROM dicom_std_rtstruct_req", db_conn)
        rtstruct_req_df.to_excel(writer, sheet_name='rtstruct_req', index=False)

        # rtimage_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_rtimage_req_modules", db_conn)
        # rtimage_mod_df.to_excel(writer, sheet_name='rtimage_mod', index=False)

        # rtimage_req_df = pd.read_sql_query("SELECT * FROM dicom_std_rtimage_req", db_conn)
        # rtimage_req_df.to_excel(writer, sheet_name='rtimage_req', index=False)

        sr_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_sr_req_modules", db_conn)
        sr_mod_df.to_excel(writer, sheet_name='sr_mod', index=False)

        sr_req_df = pd.read_sql_query("SELECT * FROM dicom_std_sr_req", db_conn)
        sr_req_df.to_excel(writer, sheet_name='sr_req', index=False)

        # seg_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_seg_req_modules", db_conn)
        # seg_mod_df.to_excel(writer, sheet_name='seg_mod', index=False)

        # seg_req_df = pd.read_sql_query("SELECT * FROM dicom_std_seg_req", db_conn)
        # seg_req_df.to_excel(writer, sheet_name='seg_req', index=False)

        us_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_us_req_modules", db_conn)
        us_mod_df.to_excel(writer, sheet_name='us_mod', index=False)

        us_req_df = pd.read_sql_query("SELECT * FROM dicom_std_us_req", db_conn)
        us_req_df.to_excel(writer, sheet_name='us_req', index=False)

        # wsl_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_wsl_req_modules", db_conn)
        # wsl_mod_df.to_excel(writer, sheet_name='wsl_mod', index=False)

        # wsl_req_df = pd.read_sql_query("SELECT * FROM dicom_std_wsl_req", db_conn)
        # wsl_req_df.to_excel(writer, sheet_name='wsl_req', index=False)

        xa_mod_df = pd.read_sql_query("SELECT * FROM dicom_std_xa_req_modules", db_conn)
        xa_mod_df.to_excel(writer, sheet_name='xa_mod', index=False)

        xa_req_df = pd.read_sql_query("SELECT * FROM dicom_std_xa_req", db_conn)
        xa_req_df.to_excel(writer, sheet_name='xa_req', index=False)



#########################################################
#########################################################
# RUN
#########################################################
#########################################################

def main():

    # update_dicom_dictionary()
    # update_sop_classes()
    # update_deid_profiles()
    # update_safe_private()

    # update_cr()
    # update_ct()
    # update_dx()
    # update_mg()
    # update_mr()
    # update_nm() 
    # update_pt()
    # update_rtdose()
    # update_rtstruct()
    # update_rtplan()
    # #update_rtimage()
    # update_sr()
    # #update_seg()
    # update_us()
    # #update_wsl()
    # update_xa()

    extract_to_excel()
    return None

if __name__ == "__main__":

    main()


