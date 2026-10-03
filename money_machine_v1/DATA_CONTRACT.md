# MONEY MACHINE V1 DATA CONTRACT

## 1. Candidate
Source: MONEY_MAKER_01
Input: closed candles
Output: verified MONEY_MAKER_01 candidate
Required: money_maker, symbol, timeframe, signal, setup, signal_time, entry_time, entry, planned_horizon_bars, planned_exit_time, reference_exit, features, research_cost_round_trip

## 2. AI Judge
Input: Candidate
Output: decision, quality, reasons
decision: PASS or WAIT
quality: HIGH, MEDIUM, or LOW
reasons: maximum 5 items
AI cannot place orders, size positions, or override Risk

## 3. Risk Authority
Input: candidate signal + market features + capital state
Output: allowed, reason, risk_amount, position_size
Risk can reject every candidate

## 4. Paper Engine
Input: Risk-approved trade only
Output: paper trade result
No live execution

## 5. Safety
Existing files are read-only references.
money_machine_v1 contains the new system.
WAIT is valid.
No guessing.
