import numpy as np, pandas as pd, h3

# calculate haversine distance in meters using latitudes & longitudes
def haversine_dist(lat1:float,lon1:float,lat2:float,lon2:float):
    R=6371008.8 # average earth radius in meters
    lat1=np.radians(lat1)
    lon1=np.radians(lon1)
    lat2=np.radians(lat2)
    lon2=np.radians(lon2)
    dlat=lat2-lat1
    dlon=lon2-lon1
    a=np.sin(dlat/2.0)**2+np.cos(lat1)*np.cos(lat2)*np.sin(dlon/2.0)**2
    return 2*R*np.arcsin(np.sqrt(a))

def deduplicate(coolr:pd.DataFrame,gfld:pd.DataFrame):
    # keep originals & create index columns
    cool=coolr.copy().reset_index().rename(columns={"index":"coolr_id"})
    gfl=gfld.copy().reset_index().rename(columns={"index":"gfld_id"})

    # converting timestamps to utc datetimes
    for df in (cool,gfl):
        for col in ("time_start","time_end"):
            if not pd.api.types.is_datetime64_any_dtype(df[col]): df[col]=pd.to_datetime(df[col],unit="ms",utc=True,errors="coerce")

    # define radius (spatial uncertainty is already radius)
    cool["_rad_m"]=cool["spatial_uncertainty"].astype(float)
    gfl["_rad_m"]=gfl["spatial_uncertainty"].astype(float)

    # gfld still uses its start day as the key
    gfl["date"]=gfl["time_start"].dt.normalize()

    # coolr may have windows up to 1 day; include both start-day and end-day if different
    cool["day_start"]=cool["time_start"].dt.normalize()
    cool["day_end"]=cool["time_end"].dt.normalize()
    cool_keys=pd.concat([cool.assign(date=cool["day_start"]),cool.loc[cool["day_end"].ne(cool["day_start"])].assign(date=cool["day_end"]),],ignore_index=True)

    # check candidate pairs where gfld and coolr got temporal overlap, drop duplicates
    cand=cool_keys.merge(gfl,on="date",suffixes=("_coolr","_gfld"),how="inner")
    cand=cand.drop_duplicates(subset=["coolr_id","gfld_id"])

    # check for true interval overlap (all elements in the intersection of coolr start & end, gfld start & end)
    cand=cand[(cand["time_start_coolr"]<=cand["time_end_gfld"])&(cand["time_start_gfld"]<=cand["time_end_coolr"])].copy()
    if cand.empty:return coolr.copy(),gfld.copy(),pd.DataFrame(columns=["coolr_id","gfld_id","date","distance_m","coolr_rad_m","gfld_rad_m","time_start_coolr","time_end_coolr","time_start_gfld","time_end_gfld"])

    # check for spatial overlap: where potential duplicate centers overlap within the region of spatial uncertainty
    # ie. they could be describing the same event according to spatial uncertainty value
    # this filters out events that coincidentally happened on the same day in totally different locations
    cand["distance_m"]=haversine_dist(cand["latitude_center_coolr"],cand["longitude_center_coolr"],cand["latitude_center_gfld"],cand["longitude_center_gfld"])
    cand["threshold_m"]=cand["_rad_m_coolr"]+cand["_rad_m_gfld"]
    cand=cand[cand["distance_m"]<=cand["threshold_m"]].copy()
    if cand.empty:return coolr.copy(),gfld.copy(),pd.DataFrame(columns=["coolr_id","gfld_id","date","distance_m","coolr_rad_m","gfld_rad_m","time_start_coolr","time_end_coolr","time_start_gfld","time_end_gfld"])
    cand.sort_values(by=["coolr_id","distance_m","_rad_m_gfld","time_start_gfld"],ascending=[True,True,True,True],inplace=True)
    best=cand.groupby("coolr_id",as_index=False).first()

    # lower coolr's spatial uncertainty where gfld's is smaller
    cool_updated=coolr.copy()
    mask_smaller=best["_rad_m_gfld"]<best["_rad_m_coolr"]
    if mask_smaller.any():
        new_vals=(best.loc[mask_smaller,["coolr_id","spatial_uncertainty_gfld"]].set_index("coolr_id")["spatial_uncertainty_gfld"])
        cool_updated.loc[new_vals.index,"spatial_uncertainty"]=new_vals.values

    # drop duplicate gfld rows
    gfld_deduped=gfld.drop(index=best["gfld_id"].unique())

    # table of matches for auditing
    matches=best[["coolr_id","gfld_id","date","distance_m","_rad_m_coolr","_rad_m_gfld","time_start_coolr","time_end_coolr","time_start_gfld","time_end_gfld"]].rename(columns={"_rad_m_coolr":"coolr_rad_m","_rad_m_gfld":"gfld_rad_m"})

    return cool_updated,gfld_deduped,matches

def set_regions(dataframe:pd.DataFrame,res_region:int=2,res_fold:int=1,min_events_per_region:int=13,max_neighbor_k:int=3):
    # set regions & folds for CV blocking (not to be fed into the model!!!)
    dF=dataframe.copy()
    fold_regions={}
    mapping={}

    # assign region_id (finer) and fold_id (coarser)
    dF["region_id"]=[h3.latlng_to_cell(float(lat),float(lon),res_region)for lat,lon in zip(dF["latitude_center"],dF["longitude_center"])]
    dF["fold_id"]=[h3.cell_to_parent(c,res_fold) for c in dF["region_id"]]

    # get counts per (fold, region)
    grp=dF.groupby(["fold_id","region_id"]).size().rename("cnt").reset_index()
    counts={(r.fold_id,r.region_id): int(r.cnt) for r in grp.itertuples(index=False)}
    for r in grp.itertuples(index=False):fold_regions.setdefault(r.fold_id,set()).add(r.region_id)

    # find small regions and build replacement mapping
    small=[(r.fold_id,r.region_id) for r in grp.itertuples(index=False) if r.cnt<min_events_per_region]

    for fold,region in small:
        replacement=None
        # search outward in H3 rings & join to meet minimum events per region
        for k in range(1,max_neighbor_k+1):
            for nb in h3.grid_disk(region,k):
                if nb==region or nb not in fold_regions.get(fold,()): continue
                if counts.get((fold,nb),0)>=min_events_per_region:
                    replacement=nb
                    break
            if replacement==None:break
        if replacement==None:replacement=f"{fold}-OTHER"
        mapping[(fold,region)]=replacement

    if mapping:dF["region_id"]=dF.apply(lambda r:mapping.get((r["fold_id"],r["region_id"]),r["region_id"]),axis=1)
    return dF

def add_index(dataframe:pd.DataFrame):
    # self explanatory no?
    dF=dataframe.copy()
    dF.insert(0,'event_id',range(0,len(dF)))
    return dF

# also, the concatenate function deduplicates matching data using the above functions
def concatenate(coolr:pd.DataFrame,gfld:pd.DataFrame,tsmin:float=None,tsmax:float=None,keys:bool=True):
    # also now time to assign regions for blocked CV
    coolr,gfld,matches=deduplicate(coolr,gfld)
    dF=pd.concat([coolr,gfld]).reset_index(drop=True)
    s=pd.to_numeric(dF['spatial_uncertainty'],errors='coerce')
    mask=s.le(np.nanpercentile(s.to_numpy(),90))&s.notna() # mask out highest 10% of points by uncertainty because there are genuinely some outliers that skew the dataset by an unreasonable amount (see figures somewhere)
    dF['spatial_uncertainty']=dF['spatial_uncertainty']/1000 # converting spatial uncertainty radii from m to km for stability and whatever
    if keys:dF['key']=np.ones(len(dF)) # optional key encoding (1=positive, 0=background)
    dF=dF[mask].reset_index(drop=True)
    if tsmin!=None:dF=dF[dF['time_start']>=tsmin] # filter out everything below min timestamp
    if tsmax!=None:dF=dF[dF['time_end']<=tsmax] # filter out everything above max timestamp
    return dF,matches
    # matches only contains points dropped due to being duplicates, not due to high uncertainty or other filters