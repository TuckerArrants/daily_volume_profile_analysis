# Volume Profile Stats

A Streamlit dashboard for analyzing intraday price structure in futures markets using Volume Profile and Market Profile concepts pioneered by **J. Peter Steidlmayer**.

Note on Volume Profile Approximation
True volume profile requires tick or time-and-sales data to know exactly which prices traded what volume. This project uses OHLCV minute-bar data only. Volume for each bar is distributed evenly across its high-low range, treating all price levels within the bar as equally likely. This is a known approximation. POC and VA boundaries derived this way are consistent with tick-based profiles in most market conditions but will diverge on bars with wide ranges or unusual intrabar price action, but for this project, this approximation is sufficiently accurate. 

---

## What It Does

This tool computes and visualizes statistical distributions of price behavior relative to key volume profile levels across sessions. The goal is to move beyond anecdotal observation and build an empirical picture of how RTH price interacts with overnight and prior session structure.

### Core Analysis

**Value Area Interactions**
- RTH open position relative to Previous RTH Value Area (PRTH VA)
- RTH open position relative to ETH Value Area
- Touch rates for PRTH POC, VAH, VAL during RTH
- Touch rates for ETH POC, VAH, VAL during RTH

**Initial Balance**
- IB True Rate across Asia, London, and RTH sessions
- IB Color (directional bias) per session
- IB Break Direction per session
- Session IB model comparisons: PRTH→Asia, Asia→London, London→RTH

**Session Structure**
- HoD / LoD session bucket distributions
- HoD-LoD pair analysis
- PRTH→RTH model classification

**Extension Measurement**
- RTH extensions above and below ETH POC, normalized in ETH VA units
- RTH extensions normalized in Previous RTH VA units
- Distributions segmented by RTH open position filter

---

## Methodology

### Reference Points

| Level | Description |
|---|---|
| ETH POC | Overnight Point of Control — highest volume price. Primary fixed anchor. |
| ETH VAH / VAL | Overnight Value Area High and Low |
| PRTH VAH / VAL | Previous RTH session Value Area boundaries |
| ETH VA Midpoint | Geometric center of ETH VA — secondary reference |

### Unit of Measure

Extensions are expressed as VA units rather than price points or percentages:

```
Extension = (Price Level - Anchor) / VA Range
```

This normalizes for daily volatility regime. A reading of 1.0 means RTH traveled a distance equal to the full VA range beyond the anchor. A wide ETH VA day and a narrow ETH VA day become directly comparable.

### Filters

All charts respond to the following filters:

- **Instrument** — ES (default), extendable to other futures
- **Day of Week**
- **Date Range**
- **RTH Open Relative to PRTH VA** — above VAH, inside, below VAL
- **RTH Open Relative to ETH VA** — above VAH, inside, below VAL
- **HoD /LoD Session Bucket** — which session made the high of day / low of day (which is only known after the fact, so used for making assumptions and checking distributions)

---

## Background

J. Peter Steidlmayer developed Market Profile in the 1980s in collaboration with the Chicago Board of Trade (CBOT). His framework treats price as an auction process unfolding across time, with the Value Area — the range containing 70% of a session's volume — representing the zone of accepted value.

This project explores these value areas, extending the framework across session handoffs (ETH → RTH, Asia → London → RTH) and measuring extensions in volatility-normalized units rather than fixed price distances.

---

## References

- Steidlmayer, J. P. & Koy, K. (1986). *Markets and Market Logic.* Chicago: Porcupine Press.
- Dalton, J., Jones, E., & Dalton, R. (1990). *Mind Over Markets.* Chicago: Probus.
- Steidlmayer, J. P. (2003). *Steidlmayer on Markets: Trading with Market Profile.* Wiley.
