import numpy as np, pandas as pd, datetime as dt

def coolr_filter(dataframe:pd.DataFrame):
    # set all empty or unknown values for date, lon, lat, and location accuracy to nan values for removal (time uncertainty is acceptable)
    dF=dataframe.copy()
    dF['event_date']=dF['event_date'].replace(' ',np.nan).replace('',np.nan).replace('unknown',np.nan).replace('Unknown',np.nan)
    dF['longitude']=[float(val) for val in dF['longitude'].replace(' ',np.nan).replace('',np.nan).replace('unknown',np.nan).replace('Unknown',np.nan)]
    dF['latitude']=[float(val) for val in dF['latitude'].replace(' ',np.nan).replace('',np.nan).replace('unknown',np.nan).replace('Unknown',np.nan)]
    dF['location_accuracy']=dF['location_accuracy'].replace(' ',np.nan).replace('',np.nan).replace('unknown',np.nan).replace('Unknown',np.nan)

    # remove all nan values from all relevant subsets
    [dF.dropna(how='any',subset=subset,inplace=True) for subset in ['event_date','longitude','latitude','location_accuracy']]
    dF=dF.drop_duplicates(subset='source_link')
    
    # return only meteorologically related landslides
    return dF[dF['landslide_trigger'].isin(['Downpour','Heavy Rain','Heavy Rainfall','Rain','Rainfall','continuous_rain','rain','downpour'])].reset_index(drop=True)

def coolr_clean(dataframe:pd.DataFrame):
    # remove all columns that arent those shown below
    dF=dataframe.copy()
    return dF.drop([col for col in list(dF.columns) if col not in ['event_time','event_date','longitude','latitude','location_accuracy']],axis=1)

def coolr_loc_map(dataframe:pd.DataFrame):
    dF=dataframe.copy()
    mappings={
        'exact':0,
        'Known within 1 km':500, # 500 is honestly a bit arbitrary, doesnt really matter all that much since spatial uncertainty is going to be normalized later
        '1km':1000,
        '5km':5000,
        '10km':10000,
        '25km':25000,
        '50km':50000,
        '100km':100000,
        '250km':250000
    }
    dF['location_accuracy']=dF['location_accuracy'].map(mappings)
    return dF

def coolr_time_column(dataframe:pd.DataFrame):
    dF=dataframe.copy()
    mask_unknown=~dF['event_time'].astype(str).str.contains(r'^\s*\d{1,2}:\d{2}\s*[APap]M\s*$',na=False) # masking to flag non-time strings (ie. unknown/nan)
    dF.loc[mask_unknown,'event_time']='12:00 AM' # set it to a default of 12:00AM (safe, wont interfere)
    dates=[datestring.split(' ')[0] for datestring in dF['event_date']]
    dF['event_time']=dF['event_time'].str.replace(r'^(\d):',r'0\1:',regex=True)
    times=[
    f"{(int(t.split()[0].split(':')[0])%12+(12 if 'PM' in t.upper() else 0)):02d}"
    f":{t.split()[0].split(':')[1].zfill(2)}"
    for t in dF['event_time']]

    dF.insert(0,'time_start',[1000*dt.datetime.combine(dt.datetime.strptime(date.split(' ')[0],'%m/%d/%Y'),dt.time.fromisoformat(time)).replace(tzinfo=dt.timezone.utc).timestamp() for date,time in zip(dates,times)])
    dF.insert(1,'time_end',dF['time_start']+mask_unknown.astype('int64')*(24*60*60*1000)) # time_start=time_end because exact times are specified. for gfld (and some coolr points w/ unknown time), the timedelta between start and end would be a day since only date is specified, not time
    dF.drop(['event_time','event_date'],axis=1,inplace=True)
    
    return dF

def coolr_rename(dataframe:pd.DataFrame):
    dF=dataframe.copy()
    dF.rename(columns={'location_accuracy':'spatial_uncertainty','latitude':'latitude_center','longitude':'longitude_center'},inplace=True)
    return dF

# just a wrapper
def process_coolr(dataframe:pd.DataFrame): return coolr_rename(coolr_time_column(coolr_loc_map(coolr_clean(coolr_filter(dataframe)))))