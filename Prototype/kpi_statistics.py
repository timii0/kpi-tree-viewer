import teradatasql
import pandas as pd
import getpass as gp
import os
from pathlib import Path

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)


TD_HOST = os.getenv('TD_HOST', 'dwprod')
TD_USER = os.getenv('TD_USER') or input('Teradata username (TD_USER): ').strip()
TD_PASS = os.getenv('TD_PASS') or gp.getpass('Teradata password (TD_PASS): ')
TD_LOGMECH = os.getenv('TD_LOGMECH', 'LDAP')
 

def td_connect():
    return teradatasql.connect(host=TD_HOST, user=TD_USER, password=TD_PASS, logmech=TD_LOGMECH)




with td_connect() as conn:

    df = pd.read_sql(
        """
        select
            Yr_Nb,
            Mo_Nb,
            'sys' as sys,
            ML_DC_Cd as ml_dc_1,
            Ownr_Crr_Cd as ml_dc_2,
            Dom_Intl_Cd as dom_int,
            Schd_Orig_Stn_Cd as station,
            schd_fleet as fleet,
            Frst_Flt_Ct as frst_flt_ind,
            pax_vendor as vendor,
            D0_Ct as num,
            DOT_OA_Sub_Op_Ct as den
        from 
            zods_kpi.flp_dtl_m
        where 
            data_cut = 'STANDARD'
            and DOT_OA_Sub_Op_Ct = 1
            and flt_orig_dt between '2026-06-29' and '2026-06-30'

        """,
        conn
    )

print(df.head())