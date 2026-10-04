# MONEY MACHINE V2

Research/development orchestration layer around the existing MONEY_MAKER_01.

## Locked boundaries

- Existing Core is not modified.
- Existing MONEY_MAKER_01 is not modified.
- Existing Risk Engine is not modified.
- Existing AI Judge is not modified.
- AI remains Quality Judge only.

## AI contract

AI may only return:

- decision: PASS / WAIT
- quality: HIGH / MEDIUM / LOW
- reasons: maximum 5

AI must NOT:

- create trading signals
- choose entry
- calculate position size
- set stop loss
- set Profit Lock
- decide exits
- calculate P/L
- manage Pot
- change Risk rules
- override Risk
- predict price
- create strategies
- add autonomous indicators
- modify system rules

## V2 flow

Market Data
    ->
MONEY_MAKER_01
    ->
Candidate
    ->
AI Quality Judge
    ->
PASS / WAIT
    ->
Risk Engine
    ->
Trade Manager
    ->
MFE / Peak / Giveback
    ->
Profit Lock
    ->
Net P/L
    ->
Pot

## Research rules

- BTCUSDT
- 5m
- 7D / 30D standard research windows
- Starting Pot: 1,500 THB
- Round-trip research cost: 0.1400%
- Real Risk
- Overlap blocked
- AI excluded from baseline research
- No live execution
- Profit Lock must pass research before deployment
