# the great wall of imports
import os,io,base64,json,zipfile,tempfile,pickle,statistics,ee,folium
from pathlib import Path
from datetime import datetime,timezone
import streamlit as sl
import streamlit.components.v1 as components
from dotenv import load_dotenv

# setup & loading styles from assets directory
sl.set_page_config(page_title='ATLAS v2 Landslide Risk Viewer',layout='wide')
if Path('assets/style.css').exists():
    with open('assets/style.css') as f:sl.markdown(f'<style>{f.read()}</style>',unsafe_allow_html=True)

# the great wall of helper functions
def extract_zip(uploaded_bytes:bytes):
    # unzipping samples to  to temp dir and keep it alive
    td=tempfile.TemporaryDirectory()
    with zipfile.ZipFile(io.BytesIO(uploaded_bytes),'r') as zf:zf.extractall(td.name)
    if 'zip_tmpdirs' not in sl.session_state:
        sl.session_state.zip_tmpdirs=[]
    sl.session_state.zip_tmpdirs.append(td)
    return td.name

def load_risk(pkl_path:Path):
    # grab risk value from various pickle formats
    with open(pkl_path,'rb') as f:obj=pickle.load(f)
    
    # try direct number first, then list/tuple
    # this bit exists mostly because i originally used tuples for risk (lambda + risk) before switching to just risk values for viz
    if isinstance(obj,(int,float)):val=float(obj)
    elif isinstance(obj,(list,tuple)) and obj and isinstance(obj[0],(int,float)):val=float(obj[0])
    else:return None
    return val

def load_fc(json_path:Path):
    # load geojson as ee featurecollection (original format)
    with open(json_path,'r') as f:return ee.FeatureCollection(json.load(f))

def fc_to_geojson(fc:ee.FeatureCollection):
    # convert to fc to geojson dict
    info=fc.getInfo() # get info from ee fc
    if info.get('type')=='FeatureCollection':return info
    if 'features' in info:return {'type':'FeatureCollection','features':info['features']}
    if info.get('type')=='Feature':return {'type':'FeatureCollection','features':[info]}
    return {'type':'FeatureCollection','features':[]}

def get_bounds(geo:dict):
    # find min/max coords for map bounds
    coords=[(ft['geometry']['coordinates'][0],ft['geometry']['coordinates'][1]) for ft in geo.get('features',[]) if ft.get('geometry',{}).get('type')=='Point' and ft.get('geometry',{}).get('coordinates')]
    if not coords:return None
    xs,ys=zip(*coords)
    return [(min(ys),min(xs)),(max(ys),max(xs))]

def mean_coord(geo:dict):
    # average lat/lon of all points
    coords=[ft['geometry']['coordinates'] for ft in geo.get('features',[]) if ft.get('geometry',{}).get('type')=='Point' and ft.get('geometry',{}).get('coordinates')]
    if not coords:return None
    xs,ys=zip(*coords)
    return (statistics.fmean(ys),statistics.fmean(xs)) # lat,lon

def extract_date(geo:dict):
    # hunt for date in feature properties
    keys_guess=('timestamp','time','date','time_start') # this also exists because of some inconsistencies in earlier versions. old inferences should still pass well through this
    
    def _fmt(v):
        # handle ee dates,epochs,strings
        if isinstance(v,dict) and v.get('type')=='Date' and isinstance(v.get('value'),(int,float)):
            return datetime.fromtimestamp(v['value']/1000,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        if isinstance(v,(int,float)):
            # milliseconds or seconds since epoch
            ts=v/1000 if v>10_000_000_000 else v
            if ts>10_000_000: return datetime.fromtimestamp(ts,timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        if isinstance(v,str):return v
        return '—'
    
    # check first few features
    for ft in geo.get('features',[])[:12]:
        props=ft.get('properties',{}) or {}
        # try known keys first
        for k in keys_guess:
            if k in props:return _fmt(props[k])
        # then any value that looks like a date
        for v in props.values():
            if _fmt(v)!='—':return _fmt(v)
    return '—'

def img_to_uri(path:Path):
    # convert images to data uris
    if not path.exists():return None
    ext=path.suffix.lower().lstrip('.')
    mime='image/png' if ext=='png' else ('image/jpeg' if ext in ('jpg','jpeg') else f'image/{ext}')
    b64=base64.b64encode(path.read_bytes()).decode('ascii')
    return f'data:{mime};base64,{b64}'

# constructing sidebar
with sl.sidebar:
    # intwari logo
    logo_uri=img_to_uri(Path('assets/intwari_logo.png'))
    if logo_uri:sl.markdown(f'<img class="sidebar-logo" alt="Intwari Technologies" src="{logo_uri}">',unsafe_allow_html=True)
    sl.header('Data Source') # data upload interface
    upzip=sl.file_uploader('Upload a .zip (optional)',type=['zip'],help="Zip with subfolders containing 'tuple.pkl' and 'featurecollection.json'")
    root_dir=sl.text_input('Or local folder',value='database/outputs/examples',help="Folder with subfolders containing 'tuple.pkl' and 'featurecollection.json'")
    sl.caption('If both are provided, the uploaded .zip takes precedence.')
    sl.markdown('<a class="link-chip" href="https://github.com/shyagehike/atlas-v2" target="_blank">GitHub</a>''<a class="link-chip" href="https://intwari.org" target="_blank">Website</a>',unsafe_allow_html=True)

# constructing header
hdr=sl.container()
with hdr:
    sl.markdown('<div class="panel-anchor"></div>',unsafe_allow_html=True)
    logo_col,title_col=sl.columns([2,6]) # this is unintuitive but essentially im breaking up the container into columns to size the logo & text properly because it just wouldnt work otherwise
    with logo_col:
        atlas_uri=img_to_uri(Path('assets/atlas_logo.png')) # atlas logo
        if atlas_uri:sl.markdown(f'<img src="{atlas_uri}" style="max-width:100%;height:auto;">',unsafe_allow_html=True)
    with title_col:sl.markdown('<h1 style="margin:20;padding:10;">Landslide Risk Viewer</h1>',unsafe_allow_html=True)

# auth & initializing earth engine
load_dotenv()
project=os.getenv('projectkey')
ee.Authenticate()
ee.Initialize(project=project)

# workspace determination, if unable just stop streamlit
workspace=None
if upzip is not None:
    # use uploaded zip
    if 'zip_workspace' not in sl.session_state:sl.session_state.zip_workspace=extract_zip(upzip.read())
    workspace=sl.session_state.zip_workspace
elif root_dir.strip():workspace=root_dir.strip()
if not workspace:
    sl.markdown('<div class="footer">© shyagehike, Intwari — All rights reserved.</div>',unsafe_allow_html=True)
    sl.stop()

# finding loaded runs
root=Path(workspace)
runs=[]
if root.exists():
    # find all dirs with required files
    runs=sorted([p for p in root.rglob('*') if p.is_dir() and (p/'tuple.pkl').exists() and (p/'featurecollection.json').exists()])
if not runs:
    sl.warning("No valid subfolders found. Each run must contain 'tuple.pkl' and 'featurecollection.json'.")
    sl.markdown('<div class="footer">© Intwari — All rights reserved.</div>',unsafe_allow_html=True)
    sl.stop()

# constructing selector
sel_panel=sl.container()
with sel_panel:
    sl.markdown('<div class="panel-anchor"></div>',unsafe_allow_html=True)
    sl.markdown('### Select Run',unsafe_allow_html=True)
    labels=[str(p.relative_to(root)) if root in p.parents else str(p) for p in runs]
    choice=sl.selectbox('Run/Subfolder',options=labels,index=0)
sel=runs[labels.index(choice)]

# loading data & formatting display values
risk=load_risk(sel/'tuple.pkl')
fc=load_fc(sel/'featurecollection.json')
geo=fc_to_geojson(fc)
n_pts=len(geo.get('features',[]))
avg=mean_coord(geo)
date_val=extract_date(geo)
coord_str='—' if not avg else f'{avg[0]:.5f}, {avg[1]:.5f}'
risk_str='—' if risk is None else f'{round(risk*100,1)}%'

# main panel w/ metrics & map
main_panel=sl.container()
with main_panel:
    sl.markdown('<div class="panel-anchor"></div>',unsafe_allow_html=True)
    left,right=sl.columns([1,3],gap='large')
    with left:
        # metrics stack
        sl.markdown(f'''
        <div class="metric risk">
          <div class="label">Current Landslide Risk</div>
          <div class="value">{risk_str}</div>
        </div>
        <div class="metric count">
          <div class="label">Subsamples</div>
          <div class="value">{n_pts:d}</div>
        </div>
        <div class="spacer-sm"></div>
        <div class="metric coords">
          <div class="label">Coordinates</div>
          <div class="value">{coord_str}</div>
        </div>
        <div class="metric date">
          <div class="label">Date</div>
          <div class="value">{date_val}</div>
        </div>
        ''',unsafe_allow_html=True)
    with right:
        # setup map w/ folium
        fmap=folium.Map(location=[0,0],zoom_start=2,control_scale=True,tiles='CartoDB dark_matter')
        # add subsample points if we have any
        if n_pts>0:
            for ft in geo['features']:
                g=ft.get('geometry',{})
                if g.get('type')=='Point' and g.get('coordinates'):
                    x,y=g['coordinates']
                    folium.CircleMarker([y,x],radius=3,color='#1a4e9a',fill=True,fill_opacity=0.9).add_to(fmap)
            # zoom to bounds
            bounds=get_bounds(geo)
            if bounds:fmap.fit_bounds(bounds,padding=(20,20))
        # add to map & render
        folium.LayerControl().add_to(fmap)
        components.html(fmap.get_root().render(),height=650,scrolling=False)

# technical details readout at bottom + footer w/ copyright notice
details_panel=sl.container()
with details_panel:
    sl.markdown('<div class="panel-anchor"></div>',unsafe_allow_html=True)
    sl.markdown('### Details')
    sl.write('**Folder:**',f'`{sel}`')
    
    # show first feature props as sample
    if n_pts>0:
        props=geo['features'][0].get('properties',{}) or {}
        if props:
            sl.markdown('#### First Subsample Properties (Sample)')
            # just show first 12 keys
            sl.json({k:props[k] for k in list(props.keys())[:12]})
sl.markdown('<div class="footer">© shyagehike, Intwari Technologies — All rights reserved.</div>',unsafe_allow_html=True)