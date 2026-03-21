import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, time
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import os, io, base64, requests

st.set_page_config(layout='wide')

#############################################
### VA Extensions Functions
#############################################
def calculate_va_extensions(
    df: pd.DataFrame,
    va_high_col: str,
    va_low_col: str,
    poc_col: str,
    prefix: str,
    high_col: str = "rdr_high",
    low_col: str = "rdr_low",
) -> pd.DataFrame:
   
    p = f"{prefix}_"
    va_range = df[va_high_col] - df[va_low_col]

    df[f"{p}ext_above_poc_pts"] = (df[high_col] - df[poc_col]).clip(lower=0)
    df[f"{p}ext_below_poc_pts"] = (df[poc_col] - df[low_col]).clip(lower=0)
    df[f"{p}ext_above_vah_pts"] = (df[high_col] - df[va_high_col]).clip(lower=0) 
    df[f"{p}ext_below_val_pts"] = (df[va_low_col] - df[low_col]).clip(lower=0)

    df[f"{p}ext_above_poc_va"] = df[f"{p}ext_above_poc_pts"] / va_range
    df[f"{p}ext_below_poc_va"] = df[f"{p}ext_below_poc_pts"] / va_range
    df[f"{p}ext_above_vah_va"] = df[f"{p}ext_above_vah_pts"] / va_range
    df[f"{p}ext_below_val_va"] = df[f"{p}ext_below_val_pts"] / va_range

    return df
    
#############################################
### Functions
#############################################
@st.cache_data
def load_data_for_instrument(instrument: str) -> pd.DataFrame:
    owner  = "TuckerArrants"
    repo   = "daily_volume_profile_analysis"
    branch = "main"
    path   = f"{instrument}_Session_Data_Final_From_2008_V2_Cleaned.csv"
    url    = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"

    try:
        df = pd.read_csv(url)
    except Exception as e:
        st.error(f"Couldn't load {path}: {e}")
        return pd.DataFrame()

    df = calculate_va_extensions(
        df,
        va_high_col="prev_rth_vah",
        va_low_col="prev_rth_val",
        poc_col="prev_rth_poc",
        prefix="prth",
    )
    df = calculate_va_extensions(
        df,
        va_high_col="eth_vah",
        va_low_col="eth_val",
        poc_col="eth_poc",
        prefix="eth",
    )
    return df

def add_open_vs_flags(df):
    df = df.copy()
    base = df["open_1800"]
    for seg in ("adr","odr","rdr"):
        seg_open = df[f"{seg}_open"]
        # ← use the exact suffix your filters expect
        df[f"{seg}_open_to_1800_open"] = np.select(
            [seg_open > base, seg_open < base],
            ["Above","Below"],
            default="Neither",
        )
    return df

def extract_time(df, time_cols=None):
    df = df.copy()
    if time_cols is None:
        time_cols = ["prev_rdr_conf_time", "adr_conf_time", "odr_conf_time", "rdr_conf_time",
                     'pre_adr_high_time', 'pre_adr_low_time', 'adr_high_time','adr_low_time',
                     'adr_transition_high_time', 'adr_transition_low_time',
                     'odr_transition_high_time', 'odr_transition_low_time',
                     'odr_high_time', 'odr_low_time', 'rdr_high_time', 'rdr_low_time',
                     'rdr_dr_high_time', 'rdr_dr_low_time']

    for col in time_cols:
        # 1) coerce to datetime (NaT on failure)
        df[col] = pd.to_datetime(df[col], errors="coerce")
        # 2) extract HH:MM, empty string if missing
        df[f"{col}_hm"] = df[col].dt.strftime("%H:%M").fillna("")
    return df

def bucket_touch_times(df,
                            touch_col="prev_close_1555_rdr_touch",
                            conf_col="rdr_conf_time",
                            session=None):  # ← add this
    df = df.copy()
    df[touch_col] = pd.to_datetime(df[touch_col], errors="coerce")
    df[conf_col]  = pd.to_datetime(df[conf_col],  errors="coerce")

    # 2) infer session from conf_col name if not explicitly provided
    if session is None:
        for s in ("rdr", "odr", "adr"):
            if conf_col.startswith(f"{s}_"):
                session = s
                break
    if session is None:
        raise ValueError(f"Cannot infer session from '{conf_col}' — pass session= explicitly")

    threshold_map = {
        "rdr": 10 + 30/60,
        "odr": 4  +  0/60,
        "adr": 20 + 30/60,
    }
    threshold = threshold_map[session]

    def to_float_hour(ts):
        return ts.dt.hour + ts.dt.minute/60 + ts.dt.second/3600

    touch_hr = to_float_hour(df[touch_col])
    conf_hr  = to_float_hour(df[conf_col])

    if session == "adr":
        session_start = 19 + 30/60
        touch_hr = np.where(touch_hr < session_start, touch_hr + 24, touch_hr)
        conf_hr  = np.where(conf_hr  < session_start, conf_hr  + 24, conf_hr)

    conds = [
        touch_hr < threshold,
        touch_hr >= threshold,
    ]
    choices = ["box_formation", "after_box_formation"]

    df[f"{touch_col}_time_buckets_v2"] = np.select(conds, choices, default=None)
    return df
           
BUCKETS = [
    ("RTH-Globex",  "16:00", "16:55"),
    ("Globex","18:00", "19:25"),
    ("Asia",   "19:30", "01:55"),  # crosses midnight
    ("Asia-London",  "02:00", "02:55"),
    #("ODRB",  "03:00", "03:55"),
    ("London",   "03:00", "08:25"),
    ("London-RTH",  "08:30", "09:25"),
    ("RTH (1st hr)",  "09:30", "10:25"),
    ("RTH",   "10:30", "15:55"),
]

def _hhmm_to_minutes(x) -> float:
    """Accepts 'HH:MM', datetime.time, Timestamp-like, or NaN -> minutes since midnight (float)."""
    if pd.isna(x):
        return np.nan

    # If it's a datetime.time
    if hasattr(x, "hour") and hasattr(x, "minute"):
        return x.hour * 60 + x.minute

    s = str(x).strip()
    if not s:
        return np.nan

    # Be forgiving if it comes in as 'HH:MM:SS'
    parts = s.split(":")
    if len(parts) < 2:
        return np.nan

    try:
        hh = int(parts[0])
        mm = int(parts[1])
        return hh * 60 + mm
    except ValueError:
        return np.nan

def bucket_hm_series(hm: pd.Series, default="NO") -> pd.Series:
    mins = hm.map(_hhmm_to_minutes)

    out = pd.Series(default, index=hm.index, dtype="object")

    for label, start, end in BUCKETS:
        s = _hhmm_to_minutes(start)
        e = _hhmm_to_minutes(end)

        if s <= e:
            mask = mins.between(s, e, inclusive="both")
        else:
            # crosses midnight (e.g., 19:30 -> 01:55)
            mask = (mins >= s) | (mins <= e)

        out.loc[mask] = label

    out.loc[mins.isna()] = np.nan
    return out

def get_rth_open_pos(df):
    df['rdr_to_prdr_open'] = 'inside'
    df.loc[df['rdr_open'] > df['prev_rdr_high'], 'rdr_to_prdr_open'] = 'above'
    df.loc[df['rdr_open'] < df['prev_rdr_low'],  'rdr_to_prdr_open'] = 'below'
    return df

def get_rth_open_pos_to_prth_va(df):
    df['rdr_open_to_prth_va'] = 'inside'
    df.loc[df['rdr_open'] > df['prev_rth_vah'], 'rdr_open_to_prth_va'] = 'above'
    df.loc[df['rdr_open'] < df['prev_rth_val'],  'rdr_open_to_prth_va'] = 'below'
    return df

def get_rth_open_pos_to_eth_va(df):
    df['rdr_open_to_eth_va'] = 'inside'
    df.loc[df['rdr_open'] > df['eth_vah'], 'rdr_open_to_eth_va'] = 'above'
    df.loc[df['rdr_open'] < df['eth_val'],  'rdr_open_to_eth_va'] = 'below'
    return df 

def get_prth_to_rth_model(df):
    df['prth_to_rth_model'] = 'inside'

    df.loc[
        (df['rdr_high'] > df['prev_rdr_high']) &
        (df['rdr_low']  < df['prev_rdr_low']),
        'prth_to_rth_model'
    ] = 'outside'

    df.loc[
        (df['rdr_low'] >= df['prev_rdr_high']),
        'prth_to_rth_model'
    ] = 'upside_gap'

    df.loc[
        (df['rdr_high'] <= df['prev_rdr_low']),
        'prth_to_rth_model'
    ] = 'downside_gap'

    df.loc[
        (df['rdr_high'] > df['prev_rdr_high']) &
        (df['rdr_low']  >= df['prev_rdr_low']) &
        (df['rdr_low']  <  df['prev_rdr_high']),
        'prth_to_rth_model'
    ] = 'upside'

    df.loc[
        (df['rdr_low']  < df['prev_rdr_low']) &
        (df['rdr_high'] <= df['prev_rdr_high']) &
        (df['rdr_high'] >  df['prev_rdr_low']),
        'prth_to_rth_model'
    ] = 'downside'

    return df

def plot_va_extensions(df: pd.DataFrame) -> None:
    """
    Plot 4 ECDF distributions of VA extensions with 20/50/80 percentile markers.
    Rows: PRTH / ETH
    Cols: Upside (above POC) / Downside (below POC)
    """
    configs = [
        {
            "column": "prth_ext_above_poc_va",
            "title": "PRTH — Upside Extension",
            "row": 1, "col": 1,
            "color": "#4C72B0",
        },
        {
            "column": "prth_ext_below_poc_va",
            "title": "PRTH — Downside Extension",
            "row": 1, "col": 2,
            "color": "#4C72B0",
        },
        {
            "column": "eth_ext_above_poc_va",
            "title": "ETH — Upside Extension",
            "row": 2, "col": 1,
            "color": "#DD8452",
        },
        {
            "column": "eth_ext_below_poc_va",
            "title": "ETH — Downside Extension",
            "row": 2, "col": 2,
            "color": "#DD8452",
        },
    ]

    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=[c["title"] for c in configs],
        vertical_spacing=0.14,
        horizontal_spacing=0.10,
    )

    percentiles = [0.20, 0.50, 0.80]
    pct_colors = ["#888888", "#333333", "#888888"]
    pct_dash   = ["dot", "solid", "dot"]

    for cfg in configs:
        series = df[cfg["column"]].fillna(0).sort_values()
        n = len(series)

        if n == 0:
            continue

        ecdf_y = np.arange(1, n + 1) / n

        fig.add_trace(
            go.Scatter(
                x=series.values,
                y=ecdf_y,
                mode="lines",
                line=dict(color=cfg["color"], width=2),
                showlegend=False,
                hovertemplate="Extension: %{x:.2f} VA units<br>Percentile: %{y:.0%}<extra></extra>",
            ),
            row=cfg["row"], col=cfg["col"],
        )

        for pct, color, dash in zip(percentiles, pct_colors, pct_dash):
            val = float(np.quantile(series, pct))

            fig.add_trace(
                go.Scatter(
                    x=[val, val],
                    y=[0, pct],
                    mode="lines",
                    line=dict(color=color, width=1, dash=dash),
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=cfg["row"], col=cfg["col"],
            )

            fig.add_trace(
                go.Scatter(
                    x=[0, val],
                    y=[pct, pct],
                    mode="lines",
                    line=dict(color=color, width=1, dash=dash),
                    showlegend=False,
                    hoverinfo="skip",
                ),
                row=cfg["row"], col=cfg["col"],
            )

            fig.add_annotation(
                x=val + 0.05,
                y=pct,
                text=f"{val:.2f}",
                showarrow=False,
                font=dict(size=11, color=color),
                xanchor="left",
                yanchor="bottom" if pct == 0.20 else "middle",
                row=cfg["row"], col=cfg["col"],
            )

    fig.update_layout(
        height=700,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=60, b=40, l=50, r=30),
    )

    fig.update_xaxes(
        title_text="VA Units",
        gridcolor="rgba(255,255,255,0.06)",
        zerolinecolor="rgba(255,255,255,0.15)",
        range=[0, 5],
    )

    fig.update_yaxes(
        title_text="Cumulative %",
        tickformat=".0%",
        gridcolor="rgba(255,255,255,0.06)",
        zerolinecolor="rgba(255,255,255,0.15)",
        range=[0, 1],
    )

    st.plotly_chart(fig, use_container_width=True)

#########################################
### Data Loading and Processing
#########################################
segments = {
    "Globex-Asia":        (   0,  90),
    "Asia":            (  90, 480),
    "Asia-London": ( 480, 540),
    "London":            ( 540, 870),
    "London-RTH": ( 870, 930),
    "RTH":            ( 930,1380),
}

# Sidebar
instrument_options = ["ES", "NQ"]
selected_instrument = st.sidebar.selectbox("Instrument", instrument_options)

df = load_data_for_instrument(selected_instrument)

df['date'] = pd.to_datetime(df['session_date']).dt.date
df = extract_time(df)
df = add_open_vs_flags(df)

df = bucket_touch_times(df, touch_col='prev_rth_poc_rdr_touch', conf_col='rdr_conf_time')
df = bucket_touch_times(df, touch_col='prev_rth_vah_rdr_touch', conf_col='rdr_conf_time')
df = bucket_touch_times(df, touch_col='prev_rth_val_rdr_touch', conf_col='rdr_conf_time')

df = bucket_touch_times(df, touch_col='eth_val_touch',  conf_col='rdr_conf_time', session='rdr')
df = bucket_touch_times(df, touch_col='eth_vah_touch',  conf_col='rdr_conf_time', session='rdr')
df = bucket_touch_times(df, touch_col='eth_poc_touch',  conf_col='rdr_conf_time', session='rdr')

df = bucket_touch_times(df, touch_col='open_1800_rdr_touch', conf_col='rdr_conf_time')

df = get_rth_open_pos(df)
df = get_prth_to_rth_model(df)
df = get_rth_open_pos_to_prth_va(df)
df = get_rth_open_pos_to_eth_va(df)

rename_map = {'pre_adr' : 'Globex-Asia',
              'adr' : 'Asia',
              'adr_transition' : 'Asia-London',
              'odr' : 'London',
              'odr_transition' : 'London-RTH',
              'rdr' : 'RTH',
              'untouched' : 'Untouched',
              'uxp' : 'Upside',
              'ux' : 'Upside',
              'u' : 'Upside',
              'dxp' : 'Downside',
              'dx' : 'Downside',
              'd' : 'Downside',
              'rx' : 'Engulfing',
              'rc' : 'Inside',
              'none' : 'None',
              'long' : 'Long',
              'short' : 'Short',   
              'box_formation' : 'IB Formation',
              'after_box_formation' : 'After IB',
              'above' : 'Above',
              'below' : 'Below',
              'inside' : 'Inside',
              'upside' : 'Upside',
              'downside' : 'Downside',
              'upside_gap' : 'Upside Gap',
              'downside_gap' : 'Downside Gap',
              'outside' : 'Outside'
} 
categorical_cols = [
    "prev_rdr_to_adr_model", "adr_to_odr_model", "odr_to_rdr_model",
    "rdr_to_prdr_open", "rdr_open_to_prth_va", "rdr_open_to_eth_va",
    "prth_to_rth_model",
    "prev_rdr_box_color", "adr_box_color", "odr_box_color", "rdr_box_color",
    "prev_rdr_conf_direction", "adr_conf_direction", "odr_conf_direction", "rdr_conf_direction",
    "prev_rdr_conf_valid", "adr_conf_valid", "odr_conf_valid", "rdr_conf_valid",
    "prev_rth_poc_rdr_touch_time_buckets_v2", "prev_rth_vah_rdr_touch_time_buckets_v2",
    "prev_rth_val_rdr_touch_time_buckets_v2", "eth_poc_touch_time_buckets_v2",
    "eth_vah_touch_time_buckets_v2", "eth_val_touch_time_buckets_v2",
    "open_1800_rdr_touch_time_buckets_v2",
]

for col in categorical_cols:
    if col in df.columns:
        df[col] = df[col].replace(rename_map)


# 1) Make sure 'date' is a datetime column
if "date" in df.columns:
    df["date"] = pd.to_datetime(df["session_date"])
else:
    st.sidebar.warning("No 'date' column found in your data!")

#########################################
### Sidebar
#########################################
day_options = ['All'] + ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
selected_day = st.sidebar.selectbox("Day of Week", day_options, key="selected_day")

min_date = df["date"].min().date()
max_date = df["date"].max().date()

if "date_range" not in st.session_state:
    st.session_state["date_range"] = (min_date, max_date)

start_date, end_date = st.sidebar.date_input(
    "Select date range:",
    min_value=min_date,
    max_value=max_date,
    key="date_range"
)

st.sidebar.markdown("### RTH Open Position") 
rdr_to_prdr_open = st.sidebar.selectbox("RTH Open Relative to PRTH",
                                             ["All"] + sorted(df["rdr_to_prdr_open"].dropna().unique()),
                                             key="rdr_to_prdr_open_filter")

st.sidebar.markdown("### RTH Open To PRTH Value Area") 
rdr_open_to_prth_va = st.sidebar.selectbox("RTH Open To PRTH Value Area",
                                             ["All"] + sorted(df["rdr_open_to_prth_va"].dropna().unique()),
                                             key="rdr_open_to_prth_va_filter")


st.sidebar.markdown("### RTH Open To ETH Value Area") 
rdr_open_to_eth_va = st.sidebar.selectbox("RTH Open To ETH Value Area",
                                             ["All"] + sorted(df["rdr_open_to_eth_va"].dropna().unique()),
                                             key="rdr_open_to_eth_va_filter")


#########################################
### Resets
#########################################
default_filters = {
    "selected_day":                       "All",
    "date_range":                 (min_date, max_date),

    "prdr_to_adr_model_filter" : [],
    "adr_to_rdr_model_filter" : [],
    "adr_to_odr_model_filter" : [],
    "odr_to_rdr_model_filter" : [],
    
    "prdr_conf_direction_filter" : "All",
    "adr_conf_direction_filter" : "All",
    "odr_conf_direction_filter" : "All",
    "rdr_conf_direction_filter" : "All",
    
    "prdr_conf_valid_filter" : "All",
    "adr_conf_valid_filter" : "All",
    "odr_conf_valid_filter" : "All",
    "rdr_conf_valid_filter" : "All",

    "prev_rdr_box_color_filter" : "All",
    "adr_box_color_filter" : "All",
    "odr_box_color_filter" : "All",
    "rdr_box_color_filter" : "All",

    "rdr_to_prdr_open_filter" : "All",
    "rdr_open_to_prth_va_filter"  :  "All",
    "rdr_open_to_eth_va_filter"     : "All",

    "prdr_box_color_filter" : "All",
    "adr_box_color_filter" : "All",
    "odr_box_color_filter" : "All",
    "rdr_box_color_filter" : "All",
}

# 2) Reset button with callback
def reset_all_filters():
    for key, default in default_filters.items():
        # only touch keys that actually exist
        if key in st.session_state:
            st.session_state[key] = default

st.sidebar.button("Reset all filters", on_click=reset_all_filters)

if isinstance(start_date, tuple):
    # sometimes date_input returns a single date if you pass a single default
    start_date, end_date = start_date

st.markdown("### Dropdown Filters")

segment_order = list(segments.keys())    
segment_order_with_no = segment_order + ["Untouched"]

#########################################
### Model Filters
#########################################
with st.expander("Models", expanded=False):
    row7_cols = st.columns([1, 1, 1])
    with row7_cols[0]:
        prev_rdr_to_adr_model_filter = st.multiselect(
            "PRTH-Asia IB Model",
            options=["UXP", "UX", "U", "DXP", "DX", "D", "RC", "RX"],
            key="prdr_to_adr_model_filter",
        )
        
    with row7_cols[1]:
        adr_to_odr_model_filter = st.multiselect(
            "Asia-London IB Model",
            options=["UXP", "UX", "U", "DXP", "DX", "D", "RC", "RX"],
            key="adr_to_odr_model_filter", 
        )
        
    with row7_cols[2]:
        odr_to_rdr_model_filter = st.multiselect(
            "London-RTH IB Model",
            options=["UXP", "UX", "U", "DXP", "DX", "D", "RC", "RX"],
            key="odr_to_rdr_model_filter",
        )
        
#########################################
### IB Break Direction Filter
#########################################
with st.expander("IB Break Direction", expanded=False):
    row8_cols = st.columns([1, 1, 1, 1])
    with row8_cols[0]:
        prdr_conf_direction_filter = st.selectbox(
            "PRTH IB Break Direction",
            options=["All"] + sorted(df["prev_rdr_conf_direction"].dropna().unique()),
            key="prdr_conf_direction_filter",
        )
    with row8_cols[1]:
        adr_conf_direction_filter = st.selectbox(
            "Asia Break Direction",
            options=["All"] + sorted(df["adr_conf_direction"].dropna().unique()),
            key="adr_conf_direction_filter",
        )
    with row8_cols[2]:
        odr_conf_direction_filter = st.selectbox(
            "London Break Direction",
            options=["All"] + sorted(df["odr_conf_direction"].dropna().unique()),
            key="odr_conf_direction_filter", 
        )
    with row8_cols[3]:
        rdr_conf_direction_filter = st.selectbox(
            "RTH Break Direction",
            options=["All"] + sorted(df["rdr_conf_direction"].dropna().unique()),
            key="rdr_conf_direction_filter",
        )
        
#########################################
### True / False Filters
#########################################
with st.expander("IB Break True/False", expanded=False):
    row9_cols = st.columns([1, 1, 1, 1])
    with row9_cols[0]:
        prdr_conf_valid_filter = st.selectbox(
            "PRTH IB Break Valid",
            options=["All"] + sorted(df["prev_rdr_conf_valid"].dropna().unique(), reverse=True),
            key="prdr_conf_valid_filter",
        )
    with row9_cols[1]:
        adr_conf_valid_filter = st.selectbox(
            "Asia IB Break Valid",
            options=["All"] + sorted(df["adr_conf_valid"].dropna().unique(), reverse=True),
            key="adr_conf_valid_filter",
        )
    with row9_cols[2]:
        odr_conf_valid_filter = st.selectbox(
            "London IB Break Valid",
            options=["All"] + sorted(df["odr_conf_valid"].dropna().unique(), reverse=True),
            key="odr_conf_valid_filter",
        )
    with row9_cols[3]:
        rdr_conf_valid_filter = st.selectbox(
            "RTH IB Break Valid",
            options=["All"] + sorted(df["rdr_conf_valid"].dropna().unique(), reverse=True),
            key="rdr_conf_valid_filter",
        )
        
#########################################
### Box Color Filters
#########################################
with st.expander("Box Color", expanded=False):
    row10_cols = st.columns([1, 1, 1, 1])
    with row10_cols[0]:
        prdr_box_color_filter = st.selectbox(
            "PRTH IB Color",
            options=["All"] + sorted(df["prev_rdr_box_color"].dropna().unique(), reverse=True),
            key="prdr_box_color_filter",
        )
    with row10_cols[1]:
        adr_box_color_filter = st.selectbox(
            "Asia IB Color",
            options=["All"] + sorted(df["adr_box_color"].dropna().unique(), reverse=True),
            key="adr_box_color_filter",
        )
    with row10_cols[2]:
        odr_box_color_filter = st.selectbox(
            "London IB Color",
            options=["All"] + sorted(df["odr_box_color"].dropna().unique(), reverse=True),
            key="odr_box_color_filter",
        )
    with row10_cols[3]:
        rdr_box_color_filter = st.selectbox(
            "RTH IB Color",
            options=["All"] + sorted(df["rdr_box_color"].dropna().unique(), reverse=True),
            key="rdr_box_color_filter",
        )

#########################################
### Filter Mapping
#########################################   

# map each filter to its column
inclusion_map = {

    "prev_rdr_to_adr_model" : "prdr_to_adr_model_filter", 
    "adr_to_odr_model" : "adr_to_odr_model_filter",
    "odr_to_rdr_model" : "odr_to_rdr_model_filter",

    "rdr_to_prdr_open" : "rdr_to_prdr_open_filter",
    "rdr_open_to_prth_va"  : "rdr_open_to_prth_va_filter",
    "rdr_open_to_eth_va" : "rdr_open_to_eth_va_filter",
   
    "prev_rdr_box_color" : "prdr_box_color_filter",
    "adr_box_color" : "adr_box_color_filter",
    "odr_box_color" : "odr_box_color_filter",
    "rdr_box_color" : "rdr_box_color_filter",

    "prev_rdr_conf_direction" : "prdr_conf_direction_filter",
    "adr_conf_direction" : "adr_conf_direction_filter",
    "odr_conf_direction" : "odr_conf_direction_filter",
    "rdr_conf_direction" : "rdr_conf_direction_filter",

    "prev_rdr_conf_valid" : "prdr_conf_valid_filter",
    "adr_conf_valid" : "adr_conf_valid_filter",
    "odr_conf_valid" : "odr_conf_valid_filter",
    "rdr_conf_valid" : "rdr_conf_valid_filter",
}

# Apply filters
df_filtered = df.copy()

sel_day = st.session_state["selected_day"]
if sel_day != "All":
    df_filtered = df_filtered[df_filtered["day_of_week"]  == sel_day]

# — Date range —
start_date, end_date = st.session_state["date_range"]
df_filtered = df_filtered[
    (df_filtered["date"] >= pd.to_datetime(start_date)) &
    (df_filtered["date"] <= pd.to_datetime(end_date))
]

for col, state_key in inclusion_map.items():
    sel = st.session_state[state_key]
    if isinstance(sel, list):
        if sel:  # non-empty list means “only these”
            df_filtered = df_filtered[df_filtered[col].isin(sel)]
    else:
        if sel != "All":
            df_filtered = df_filtered[df_filtered[col] == sel]

  
###########################################################
### True Rates, Box Color, and Conf. Direction Graphs
###########################################################
# Box Color and Confirmation Direction
true_rate_cols   = ["adr_conf_valid", "odr_conf_valid", "rdr_conf_valid"]
true_rate_titles = ["Asia IB True Rate", "London IB True Rate", "RTH IB True Rate"]

box_color_cols   = ["adr_box_color", "odr_box_color", "rdr_box_color"]
box_color_titles = ["Asia IB Color", "London IB Color", "RTH IB Color"]

conf_direction_cols   = ["adr_conf_direction", "odr_conf_direction", "rdr_conf_direction"]
conf_direction_titles = [
    "Asia IB Break Direction",
    "London IB Break Direction",
    "RTH IB Break Direction",
]

# make one 6‐column container
plot_df = df_filtered.copy()

for col in true_rate_cols:
    plot_df[col] = plot_df[col].map({True: "True", False: "False"})

# color maps
box_color_map = {
    "Green":   "#2ecc71",
    "Red":     "#e74c3c",
    "Neutral": "#5d6d7e",
}
dir_color_map = {
    "Long":  "#2ecc71", 
    "Short": "#e74c3c",
    "None":  "#5d6d7e",
}

true_color_map = {
    "True":  "#2ecc71",
    "False": "#e74c3c",
}

# replace null/NaN with the string "None" for just those three cols
for col in conf_direction_cols:
    plot_df[col] = plot_df[col].fillna("None")
    
all_cols = st.columns(len(box_color_cols) + len(conf_direction_cols) + len(true_rate_cols))

# true rate donuts
for i, col in enumerate(true_rate_cols):
    fig = px.pie(
        plot_df,
        names=col,
        color=col,                        # tell px to color by that column
        color_discrete_map=true_color_map, # map labels → colors
        title=true_rate_titles[i],
        hole=0.5,
    )
    fig.update_traces(textinfo="percent+label", textposition="inside", showlegend=False)
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
    all_cols[i].plotly_chart(fig, use_container_width=True)

# box-color donuts
offset = len(true_rate_cols)
for i, col in enumerate(box_color_cols):
    fig = px.pie(
        plot_df,
        names=col,
        color=col,                        # tell px to color by that column
        color_discrete_map=box_color_map, # map labels → colors
        title=box_color_titles[i],
        hole=0.5,
    )
    fig.update_traces(textinfo="percent+label", textposition="inside", showlegend=False)
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
    all_cols[offset + i].plotly_chart(fig, use_container_width=True)

offset2 = len(box_color_cols) + len(true_rate_cols)
for j, col in enumerate(conf_direction_cols):
    fig = px.pie(
        plot_df,
        names=col,
        color=col,
        color_discrete_map=dir_color_map,
        title=conf_direction_titles[j],
        hole=0.5,
    )
    fig.update_traces(textinfo="percent+label", textposition="inside", showlegend=False)
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
    all_cols[offset2 + j].plotly_chart(fig, use_container_width=True)

#########################################################
### Touch Times
#########################################################

prth_vol_cols = ['prev_rth_poc_rdr_touch_time_buckets_v2', "prev_rth_vah_rdr_touch_time_buckets_v2", "prev_rth_val_rdr_touch_time_buckets_v2"]

prth_vol_titles = ["Prev. RTH POC Touch in RTH", "Prev. RTH VAH Touch in RTH", "Prev. RTH VAL Touch in RTH"]

eth_vol_cols = ['eth_poc_touch_time_buckets_v2', "eth_vah_touch_time_buckets_v2", "eth_val_touch_time_buckets_v2"]

eth_vol_titles = ["ETH POC Touch in RTH", "ETH VAH Touch in RTH", "ETH VAL Touch in RTH"]

open_1800_and_gap_row = st.columns(len(prth_vol_cols) + len(eth_vol_cols))

order = ["IB Formation", "After IB", "Untouched"]
for idx, col in enumerate(prth_vol_cols):
    # 1) drop any actual None/NaN values so they never even show up
    series = df_filtered[col].fillna("Untouched")

    # 2) normalized counts, *then* reindex into your three‐bucket order
    counts = (
        series
        .value_counts(normalize=True)
        .reindex(order, fill_value=0)
    )

    # 4) turn into percentages
    perc = counts * 100
    perc = perc[perc > 0]

    # now build the bar‐chart
    fig = px.bar(
        x=perc.index,
        y=perc.values,
        text=[f"{v:.1f}%" for v in perc.values],
        title=prth_vol_titles[idx],
        labels={"x": "", "y": ""},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        xaxis_tickangle=90,
        margin=dict(l=10,r=10,t=30,b=10),
        yaxis=dict(showticklabels=False))

    open_1800_and_gap_row[idx].plotly_chart(fig, use_container_width=True)

for idx, col in enumerate(eth_vol_cols):
    # 1) drop any actual None/NaN values so they never even show up
    series = df_filtered[col].fillna("Untouched")

    # 2) normalized counts, *then* reindex into your three‐bucket order
    counts = (
        series
        .value_counts(normalize=True)
        .reindex(order, fill_value=0)
    )

    # 4) turn into percentages
    perc = counts * 100
    perc = perc[perc > 0]

    # now build the bar‐chart
    fig = px.bar(
        x=perc.index,
        y=perc.values,
        text=[f"{v:.1f}%" for v in perc.values],
        title=eth_vol_titles[idx],
        labels={"x": "", "y": ""},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        xaxis_tickangle=90,
        margin=dict(l=10,r=10,t=30,b=10),
        yaxis=dict(showticklabels=False))

    open_1800_and_gap_row[idx +  len(prth_vol_cols)].plotly_chart(fig, use_container_width=True)

#########################################################
### Models Graphs
#########################################################
model_cols = [
    "prev_rdr_to_adr_model",
    "adr_to_odr_model",
    "odr_to_rdr_model"]

model_titles = [
    "PRTH-Asia IB Model",
    "Asia-London IB Model",
    "London-RTH IB Model"]

row1 = st.columns(len(model_cols))
for idx, col in enumerate(model_cols):
    # 1) drop any actual None/NaN values so they never even show up
    series = df_filtered[col].dropna() 

    # 2) get normalized counts
    counts = series.value_counts(normalize=True)

    # 3) if you still have the string "None" in your index, drop it
    counts = counts.drop("None", errors="ignore")

    # 4) turn into percentages
    perc = counts * 100
    perc = perc[perc > 0]

    # now build the bar‐chart
    fig = px.bar(
        x=perc.index,
        y=perc.values,
        text=[f"{v:.1f}%" for v in perc.values],
        title=model_titles[idx],
        labels={"x": "", "y": ""},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        xaxis_tickangle=0,
        margin=dict(l=10,r=10,t=30,b=10),
        yaxis=dict(showticklabels=False))

    row1[idx].plotly_chart(fig, use_container_width=True)

######################################
### VA extensions
######################################

st.subheader("Value Area Extension Distributions")
plot_va_extensions(df_filtered)
st.caption(
    "Extensions are normalized by the reference VA range. "
    "A value of 0 indicates RTH price did not trade beyond the POC in that direction. "
    "PRTH-normalized values tend to be smaller as the PRTH VA range is typically wider than ETH."
)


#########################################################
### RTH Open Position 
#########################################################
rth_open_cols = [
    "rdr_open_to_prth_va",
    "rdr_open_to_eth_va",]

rth_open_titles = [
    "RTH Open to PRTH VA Position",
    "RTH Open To ETH VA Position",
    ]

row1 = st.columns(len(rth_open_cols))
for idx, col in enumerate(rth_open_cols):
    # 1) drop any actual None/NaN values so they never even show up
    series = df_filtered[col].dropna() 

    # 2) get normalized counts
    counts = series.value_counts(normalize=True)

    # 3) if you still have the string "None" in your index, drop it
    counts = counts.drop("None", errors="ignore")

    # 4) turn into percentages
    perc = counts * 100
    perc = perc[perc > 0]

    # now build the bar‐chart
    fig = px.bar(
        x=perc.index,
        y=perc.values,
        text=[f"{v:.1f}%" for v in perc.values],
        title=rth_open_titles[idx],
        labels={"x": "", "y": ""},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        xaxis_tickangle=0,
        margin=dict(l=10,r=10,t=30,b=10),
        yaxis=dict(showticklabels=False))

    row1[idx].plotly_chart(fig, use_container_width=True)

#########################################################
### PRTH To RTH Models
#########################################################
rth_model_cols = [
    "prth_to_rth_model",]

rth_model_titles = [
    "PRTH-RTH Model"]

row1 = st.columns(len(rth_model_cols))
for idx, col in enumerate(rth_model_cols):
    # 1) drop any actual None/NaN values so they never even show up
    series = df_filtered[col].dropna() 

    # 2) get normalized counts
    counts = series.value_counts(normalize=True)

    # 3) if you still have the string "None" in your index, drop it
    counts = counts.drop("None", errors="ignore")

    # 4) turn into percentages
    perc = counts * 100
    perc = perc[perc > 0]

    # now build the bar‐chart
    fig = px.bar(
        x=perc.index,
        y=perc.values,
        text=[f"{v:.1f}%" for v in perc.values],
        title=rth_model_titles[idx],
        labels={"x": "", "y": ""},
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(
        xaxis_tickangle=0,
        margin=dict(l=10,r=10,t=30,b=10),
        yaxis=dict(showticklabels=False))

    row1[idx].plotly_chart(fig, use_container_width=True)



st.caption(f"Sample size: {len(df_filtered):,} rows")

session_date_df = df_filtered['session_date']
csv = session_date_df.to_csv(index=False).encode("utf-8")

st.download_button(
    label="Download filtered days",
    data=csv,
    file_name="filtered_dates.csv",
    mime="text/csv",
)
