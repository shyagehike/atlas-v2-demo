import numpy as np, pandas as pd, math

def gfld_filter(dataframe:pd.DataFrame):
    # set all empty or unknown values for date, lon, lat, and precision to nan values for removal
    dF=dataframe.copy()
    dF['Date']=dF['Date'].replace(' ',np.nan).replace('',np.nan).replace('unknown',np.nan).replace('Unknown',np.nan)
    dF['Longitude']=[float(val) for val in dF['Longitude'].replace(' ',np.nan).replace('',np.nan).replace('unknown',np.nan).replace('Unknown',np.nan)]
    dF['Latitude']=[float(val) for val in dF['Latitude'].replace(' ',np.nan).replace('',np.nan).replace('unknown',np.nan).replace('Unknown',np.nan)]
    dF['Precision']=[float(val) for val in dF['Precision'].replace(' ',np.nan).replace('',np.nan).replace('unknown',np.nan).replace('Unknown',np.nan)]

    # remove all nan values from all relevant subsets
    [dF.dropna(how='any',subset=subset,inplace=True) for subset in ['Date','Longitude','Latitude','Precision']]
    dF=dF.drop_duplicates(subset='Source 1')
    
    # make sure filtered landslides are rain-triggered, return
    return dF[dF['Trigger'].isin(['rainfall'])].reset_index(drop=True)

def gfld_clean(dataframe:pd.DataFrame):
    # cleans dataset, dropping all non-relevant columns
    dF=dataframe.copy()
    return dF.drop([col for col in list(dF.columns) if col not in ['Date','Longitude','Latitude','Precision']],axis=1)

def gfld_precision_to_radius(dataframe:pd.DataFrame):
    dF=dataframe.copy()
    # essentially converting precision from an area to a radius (heuristically assuming the uncertainty area is circular)
    dF['Precision']=(dF['Precision']/math.pi)**(1/2)
    return dF

def gfld_time_column(dataframe:pd.DataFrame):
    # add time start & end columns, standardize to utc
    dF=dataframe.copy()
    dF.insert(0,'time_start',[1000*date.tz_localize('UTC').timestamp() for date in dF['Date']])
    dF.insert(1,'time_end',dF['time_start']+(24*60*60*1000)) # time_start=time_end+(1 day) (in ms)
    dF.drop(['Date'],axis=1,inplace=True)
    return dF

def gfld_rename(dataframe:pd.DataFrame):
    # rename columns for later concatenation
    dF=dataframe.copy()
    dF.rename(columns={'Precision':'spatial_uncertainty','Latitude':'latitude_center','Longitude':'longitude_center'},inplace=True)
    return dF

# function wrapper
def process_gfld(dataframe:pd.DataFrame): return gfld_rename(gfld_time_column(gfld_precision_to_radius(gfld_clean(gfld_filter(dataframe)))))