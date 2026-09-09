import os
import sys
import requests
import xmltodict
import sqlite3 as sql
import pandas as pd
import numpy as np
import copy
import collections

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

#########################################################
# Script variables
#########################################################

# NOTE: this script still uses the pre-2024 plural table names
# (dicom_sop_classes, dicom_deid_profiles, ...). It only works against an
# older parsed database, not one produced by the current parse_dicom_standard.py.
data_folder = config.data_folder()
db_conn = sql.connect(config.standard_db_path())

def extract_to_excel():

    print('Extracting to Excel')

    out_path = config.excel_export_path()
    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
    
        dd_df = pd.read_sql_query("SELECT * FROM dicom_dictionary", db_conn)
        dd_df.to_excel(writer, sheet_name='dicom_dictionary', index=False)
        
        class_df = pd.read_sql_query("SELECT * FROM dicom_sop_classes", db_conn)
        class_df.to_excel(writer, sheet_name='dicom_sop_classes', index=False)
        
        deid_df = pd.read_sql_query("SELECT * FROM dicom_deid_profiles", db_conn)
        deid_df.to_excel(writer, sheet_name='dicom_deid_profiles', index=False)




        cr_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.1>'", db_conn)
        cr_mod_df.to_excel(writer, sheet_name='cr_mod', index=False)
        
        cr_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.1>'", db_conn)
        cr_req_df.to_excel(writer, sheet_name='cr_req', index=False)
    

        ct_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.2>'", db_conn)
        ct_mod_df.to_excel(writer, sheet_name='ct_mod', index=False)
        
        ct_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.2>'", db_conn)
        ct_req_df.to_excel(writer, sheet_name='ct_req', index=False)
        

        dx_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.1.1>'", db_conn)
        dx_mod_df.to_excel(writer, sheet_name='dx_mod', index=False)

        dx_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.1.1>'", db_conn)
        dx_req_df.to_excel(writer, sheet_name='dx_req', index=False)


        mg_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.1.2>'", db_conn)
        mg_mod_df.to_excel(writer, sheet_name='mg_mod', index=False)

        mg_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.1.2>'", db_conn)
        mg_req_df.to_excel(writer, sheet_name='mg_req', index=False)


        mr_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.4>'", db_conn)
        mr_mod_df.to_excel(writer, sheet_name='mr_mod', index=False)

        mr_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.4>'", db_conn)
        mr_req_df.to_excel(writer, sheet_name='mr_req', index=False)


        nm_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.20>'", db_conn)
        nm_mod_df.to_excel(writer, sheet_name='nm_mod', index=False)

        nm_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.20>'", db_conn)
        nm_req_df.to_excel(writer, sheet_name='nm_req', index=False)


        pt_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.128>'", db_conn)
        pt_mod_df.to_excel(writer, sheet_name='pt_mod', index=False)

        pt_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.128>'", db_conn)
        pt_req_df.to_excel(writer, sheet_name='pt_req', index=False)


        rtdose_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.481.2>'", db_conn)
        rtdose_mod_df.to_excel(writer, sheet_name='rtdose_mod', index=False)

        rtdose_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.481.2>'", db_conn)
        rtdose_req_df.to_excel(writer, sheet_name='rtdose_req', index=False)


        rtplan_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.481.5>'", db_conn)
        rtplan_mod_df.to_excel(writer, sheet_name='rtplan_mod', index=False)

        rtplan_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.481.5>'", db_conn)
        rtplan_req_df.to_excel(writer, sheet_name='rtplan_req', index=False)


        rtstruct_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.481.3>'", db_conn)
        rtstruct_mod_df.to_excel(writer, sheet_name='rtstruct_mod', index=False)

        rtstruct_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.481.3>'", db_conn)
        rtstruct_req_df.to_excel(writer, sheet_name='rtstruct_req', index=False)


        rtimage_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.481.1>'", db_conn)
        rtimage_mod_df.to_excel(writer, sheet_name='rtimage_mod', index=False)

        rtimage_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.481.1>'", db_conn)
        rtimage_req_df.to_excel(writer, sheet_name='rtimage_req', index=False)


        sr_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.88.11>'", db_conn)
        sr_mod_df.to_excel(writer, sheet_name='sr_mod', index=False)

        sr_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.88.11>'", db_conn)
        sr_req_df.to_excel(writer, sheet_name='sr_req', index=False)


        seg_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.66.4>'", db_conn)
        seg_mod_df.to_excel(writer, sheet_name='seg_mod', index=False)

        seg_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.66.4>'", db_conn)
        seg_req_df.to_excel(writer, sheet_name='seg_req', index=False)


        us_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.6.1>'", db_conn)
        us_mod_df.to_excel(writer, sheet_name='us_mod', index=False)

        us_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.6.1>'", db_conn)
        us_req_df.to_excel(writer, sheet_name='us_req', index=False)


        wsl_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.77.1.6>'", db_conn)
        wsl_mod_df.to_excel(writer, sheet_name='wsl_mod', index=False)

        wsl_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.77.1.6>'", db_conn)
        wsl_req_df.to_excel(writer, sheet_name='wsl_req', index=False)


        xa_mod_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_modules where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.12.1>'", db_conn)
        xa_mod_df.to_excel(writer, sheet_name='xa_mod', index=False)

        xa_req_df = pd.read_sql_query("SELECT * FROM dicom_class_iod_requirements where sop_class_uid = '<1.2.840.10008.5.1.4.1.1.12.1>'", db_conn)
        xa_req_df.to_excel(writer, sheet_name='xa_req', index=False)



#########################################################
#########################################################
# RUN
#########################################################
#########################################################

def main():
    extract_to_excel()


if __name__ == "__main__":
    main()


