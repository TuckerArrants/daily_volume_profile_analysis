# Volume Profile Stats — ETH VA & Previous RTH VA Extensions

## Overview

This repository analyzes intraday price behavior relative to two key volume profile structures:

- **ETH Value Area** (Electronic Trading Hours)
- **Previous RTH Value Area** (Regular Trading Hours)

Inspired by the work of **J. Peter Steidlmayer**, the originator of Market Profile theory, this project extends his foundational ideas — particularly the 80% rule and the significance of value area boundaries — into a quantitative framework for measuring RTH price extensions.

## Background

J. Peter Steidlmayer developed Market Profile in the 1980s in collaboration with the Chicago Board of Trade (CBOT). His core insight was that markets auction in both time and price, and that the Value Area — the range containing 70% of a session's volume — represents the zone of market-accepted value.

This project builds on that foundation by measuring how far RTH price extends beyond fixed reference points, normalized by VA range size rather than raw price or percentage.

## Methodology

### Reference Points

- **ETH POC** — Point of Control from the overnight session. The primary fixed anchor for measuring RTH extensions. Volume-derived, represents the price at which the most overnight business was conducted.
- **ETH VAH / VAL** — Overnight Value Area High and Low.
- **Previous RTH VAH / VAL** — Prior full-session Value Area boundaries.

### Unit of Measure

Extensions are expressed in VA units rather than price points or percentages:
```
Extension = (RTH Price Level - Anchor) / VA Range
```

This normalizes for volatility regime. A move of 1.0 VA units means RTH traveled a distance equal to the full VA range beyond the anchor point.

### Filters

- Current RTH open relative to ETH value area
- Current RTH open relative to previous RTH value area
- Direction of first hour of Asia, London, and RTH session - aka the "initial balance" or IB
- Direction of the first breakout of the IB
- Relative position of each trading sessions IB to the previous one

## Instruments

Currently built for futures markets where volume profile structure is most reliable. Initial focus on ES and NQ continuous contracts.

## Data Requirements

- Minute-bar OHLCV data with volume
- ETH session: 18:00–09:30 ET
- RTH session: 09:30–16:15 ET

## References

- Steidlmayer, J. P. & Koy, K. (1986). *Markets and Market Logic.*
- Dalton, J., Jones, E., & Dalton, R. (1990). *Mind Over Markets.*
- Steidlmayer, J. P. (2003). *Steidlmayer on Markets.*
