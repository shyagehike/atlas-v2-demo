import numpy as np, pandas as pd, json
from scipy.stats import skew,kurtosis

# check for finite values only
def _finite(x):
    a=np.asarray(x,dtype=float)
    return a[np.isfinite(a)]

# assess severity of non-normality (skew & kurtosis)
def _severity(abs_skew,excess_kurt):
    s_sk=1-np.exp(-(abs_skew/3.0)**2)
    s_ku=1-np.exp(-(max(excess_kurt,0.0)/10.0))
    return 0.6*s_sk+0.4*s_ku

# forward/inverse normalization steps
def _apply_steps_forward(y,steps):
    y=np.asarray(pd.to_numeric(y,errors='coerce'),float)
    for st in steps:
        k=st['kind']
        if k=='identity':pass
        elif k=='log1p':
            y=np.log1p(np.clip(y,0,None))
        elif k=='add_eps':
            y=y+float(st['eps'])
        elif k=='power':
            y=np.power(np.clip(y,0,None),float(st['p']))
        elif k=='clip_to':
            y=np.clip(y,float(st['lo_v']),float(st['hi_v']))
        elif k=='minmax01':
            a,b=float(st['a']),float(st['b'])
            y=(y-a)/(b-a)
        elif k=='divide':
            d=float(st['denom'])
            y=y/(d if d>0 else 1)
        elif k=='arcsinh_scale':
            pre_div=float(st['pre_div'])
            scale=float(st['scale'])
            y=np.arcsinh(y/(scale*pre_div))
        elif k=='robust_z':
            med=float(st['med']); sc=float(st['scale'])
            sc=sc if sc !=0 else 1
            y=(y-med)/sc
        elif k=='tanh_div':
            div=float(st['div'])
            y=np.tanh(y/max(div,1e-9))
    return y # skip step if no neat category
def _apply_steps_inverse(y,steps): # APPROXIMATE INVERSE (some steps are lossy like clipping)
    y=np.asarray(pd.to_numeric(y,errors='coerce'),float)
    for st in reversed(steps):
        k=st['kind']
        if k=='identity':pass
        elif k=='tanh_div':
            div=float(st['div'])
            y=np.clip(y,-0.999999,0.999999)
            y=np.arctanh(y)*max(div,1e-9)
        elif k=='robust_z':
            med=float(st['med']); sc=float(st['scale'])
            sc=sc if sc !=0 else 1
            y=y*sc+med
        elif k=='arcsinh_scale':
            pre_div=float(st['pre_div'])
            scale=float(st['scale'])
            y=np.sinh(y)*(scale*pre_div)
        elif k=='divide':
            d=float(st['denom'])
            y=y*(d if d>0 else 1)
        elif k=='minmax01':
            a,b=float(st['a']),float(st['b'])
            y=y*(b-a)+a
        elif k=='clip_to':
            y=y # non-invertible so just dont do anything
        elif k=='power':
            p=float(st['p'])
            p_inv=(1/p) if p !=0 else 1
            y=np.power(np.clip(y,0,None),p_inv)
        elif k=='add_eps':
            y=y-float(st['eps'])
        elif k=='log1p':
            y=np.expm1(np.clip(y,0,None))
    return y # other non-invertible steps are skipped too

# fitting normalization for all columns in df
# meta columns are left as identity
def normalize(dF:pd.DataFrame,meta:list[str],exclude=None):
    dF=dF.copy()
    meta=set(meta or []) # meta columns (non-quantiative)
    exclude=set(exclude or []) # excluded columns (quantitative but not to be transformed)
    spec={'version':'v3_exact','columns':{}} # initialize spec dict

    # itrate through all columns
    for col in dF.columns:
        steps=[];post={'kind':'none'}
        # dropout checks (meta, all-nan, all-nonfinite, all-constant)
        if col in meta:
            spec['columns'][col]={'steps':[{'kind':'identity'}],'post':post,'meta':True}
            continue
        if col in exclude:
            spec['columns'][col]={'steps':[{'kind':'identity'}],'post':post,'meta':False}
            continue
        x=pd.to_numeric(dF[col],errors='coerce').astype(float)
        if x.isna().all():
            spec['columns'][col]={'steps':[{'kind':'identity'}],'post':post}
            continue
        xf=_finite(x)
        if xf.size==0 or np.nanstd(xf)==0:
            spec['columns'][col]={'steps':[{'kind':'identity'}],'post':post}
            continue
        
        # extract skew & kurtosis
        sk=float(skew(xf))
        ku=float(kurtosis(xf,fisher=True))
        kw=any(k in col.lower() for k in ('soil','precip','runoff')) # keywords that trigger heavy non-normality automatically
        heavy=((abs(sk) >=2 and ku >=5) or (abs(sk)<2 and ku>2.5)) or kw # conditions for heavy non-normality
        if heavy: # heavy non-normality detected, apply nrelevant ormalization
            s=float(_severity(abs(sk),ku))
            xmin=float(np.nanmin(xf))
            integerish=np.allclose(xf,np.round(xf),atol=1e-9) # integer-ish check
            zero_frac=float(np.mean(np.isclose(x,0.0,atol=0))) # fraction of zeros
            sparse=(xmin >=0) and integerish and (zero_frac >=0.8) # sparsity conditions
            if sparse: # sparse non-negative integerish data (usually counts)
                steps.append({'kind':'log1p'})
                pos=np.log1p(np.clip(xf,0,None))
                if pos.size>0 and np.any(pos>0):
                    q=99 if s<0.7 else 95
                    denom=float(np.nanpercentile(pos[pos>0],q))
                    if not np.isfinite(denom) or denom <=0:denom=float(np.nanmax(pos)) or 1 # fallback
                else:q,denom=100,1 # fallback
                steps.append({'kind':'divide','denom':denom})
                steps.append({'kind':'clip_to','lo_v':0.0,'hi_v':1})
            elif xmin >=0: # non-negative data processing
                p=max(0.12,1/(1+4.0*s))
                eps=max(1e-12,float(np.nanpercentile(xf,0.001)))
                very_severe=s >=0.75 or (abs(sk) >=3.0 and ku >=8.0)
                if very_severe:
                    steps.append({'kind':'log1p'}) # log1p transform
                    steps.append({'kind':'add_eps','eps':eps}) # add small eps to avoid exact zeros
                else:steps.append({'kind':'add_eps','eps':eps}) # add small eps to avoid exact zeros
                steps.append({'kind':'power','p':p}) # power transform
                y_tmp=np.power(np.clip(xf if not very_severe else (np.log1p(np.clip(xf,0,None))+eps),0,None),p)
                lo=0.002+0.048*s; hi=0.998-0.048*s # lo/hi percentiles based on severity
                lo_v,hi_v=np.nanpercentile(y_tmp,[lo*100,hi*100])
                if not np.isfinite(lo_v) or not np.isfinite(hi_v) or hi_v <=lo_v: # fallback
                    y_min,y_max=float(np.nanmin(y_tmp)),float(np.nanmax(y_tmp))
                    lo_v,hi_v=(y_min,y_max) if y_max>y_min else (y_min,y_min+1)
                steps.append({'kind':'clip_to','lo_v':float(lo_v),'hi_v':float(hi_v)})
                y_clip=np.clip(y_tmp,lo_v,hi_v)
                a,b=float(np.nanmin(y_clip)),float(np.nanmax(y_clip))
                if b <=a:b=a+1
                steps.append({'kind':'minmax01','a':a,'b':b})
            else: # non-heavy two-sided data processing
                pre_div=1+3.0*s # pre-division factor
                mad=float(np.nanmedian(np.abs(xf-float(np.nanmedian(xf))))) # mad calculation
                scale0=mad if mad>0 else (float(np.nanstd(xf)) or 1)
                z_base=np.arcsinh(xf/(scale0*pre_div))
                med1=float(np.nanmedian(z_base))
                q1,q3=np.nanpercentile(z_base,[25,75]) # for iqr calculation vvv
                iqr=float(q3-q1)
                scale1=(iqr/1.349) if iqr>0 else (float(np.nanstd(z_base)) or 1) # robust scale estimate
                lo_pct=0.5+4.5*s;hi_pct=99.5-4.5*s # lo/hi percentiles based on severity
                zt=(z_base-med1)/(scale1 if scale1 !=0 else 1)
                zl,zh=np.nanpercentile(zt,[lo_pct,hi_pct])
                if not np.isfinite(zl) or not np.isfinite(zh) or zh <=zl: # fallback
                    zl,zh=float(np.nanmin(zt)),float(np.nanmax(zt))
                    if zh <=zl:zh=zl+1
                div=3.0-2.5*s # tanh-divisor
                steps.append({'kind':'arcsinh_scale','pre_div':pre_div,'scale':scale0}) # arcsinh scaling
                steps.append({'kind':'robust_z','med':med1,'scale':scale1}) # robust-z scaling
                steps.append({'kind':'clip_to','lo_v':float(zl),'hi_v':float(zh)}) # clipping
                steps.append({'kind':'tanh_div','div':div}) # tanh-div scaling
        else: steps.append({'kind':'identity'}) # identity scaling (just dont do anything)

        # post-pass scaling to ensure everything is in [0,1] range if possible or [-1,1]
        y_now=_apply_steps_forward(x.values,steps) # apply current steps to see where we are
        xf2=_finite(y_now) # finite values only
        mu=float(np.nanmean(xf2)) if xf2.size>0 else 0
        sigma=float(np.nanstd(xf2)) if xf2.size>0 else 1 # sigma
        if not np.isfinite(sigma) or sigma==0:sigma=1
        if not np.isfinite(mu):mu=0
        post={'kind':'post_zscore','mu':mu,'sigma':sigma}
        spec['columns'][col]={'steps':steps,'post':post} # add to spec
    return spec

# applying & inverting normalization based on spec
def transform_spec(dF:pd.DataFrame,spec:dict):
    out=dF.copy()
    for col,cfg in spec['columns'].items():
        if col not in out.columns:continue
        if cfg.get('meta',False):continue
        y=_apply_steps_forward(out[col].values,cfg['steps'])
        post=cfg.get('post',{'kind':'none'})
        if post['kind']=='post_zscore':
            mu=float(post['mu']);sigma=float(post['sigma']) or 1
            y=(y-mu)/sigma
        out[col]=y
    return out
def inverse_transform_spec(dF:pd.DataFrame,spec:dict):
    out=dF.copy()
    for col,cfg in spec['columns'].items():
        if col not in out.columns:continue
        if cfg.get('meta',False):continue
        y=np.asarray(pd.to_numeric(out[col],errors='coerce'),float)
        post=cfg.get('post',{'kind':'none'})
        if post['kind']=='post_zscore':
            mu=float(post['mu']);sigma=float(post['sigma']) or 1
            y=y*sigma+mu
        out[col]=_apply_steps_inverse(y,cfg['steps'])
    return out

# saving/loading spec as json
def save_spec(spec:dict,path:str):
    with open(path,'w') as f:json.dump(spec,f,indent=2)
def load_spec(path:str):
    with open(path,'r') as f:return json.load(f)

# big wrapper type function
def transform_full(dF:pd.DataFrame,meta:list,exclude:dict,spec_path:str=None):
    spec=normalize(dF,meta,exclude)
    if spec_path!=None:save_spec(spec,spec_path)
    return transform_spec(dF,spec),spec
