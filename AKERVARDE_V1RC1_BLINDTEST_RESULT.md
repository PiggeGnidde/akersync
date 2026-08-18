# ÅkerVärde v1.0-rc1 — 2018/2019 blind-backtest result

The candidate set and predictions were committed before purchase prices were inspected.

Primary sample: 12 price-blind selected pure-arable transactions from 2018-2019.

## Pre-registered metrics

- n = 12
- median APE = 13.38 %
- median observed/predicted ratio = 1.0226
- log-price R² = 0.1408
- frozen P10-P90 coverage = 8/12 = 66.7 %

## Interpretation

Typical-error performance is strong for this small historical external sample:
median APE is about 13.4% and median bias is almost exactly centered.

Tail calibration is weaker: 8/12 observations fall in the nominal 10-90 band.
With n=12 this is imprecise; under true 80% coverage, observing 8 or fewer in-band
cases has probability about 20.5%.

The conventional log-price R² is only about 0.14 because a few very large residuals
dominate the squared-error metric. No transaction is removed post hoc from the primary
result.

Largest residuals include:
- Vasagården 5:5: observed/predicted ratio ~0.184
- Vallkärratorn 5:75: observed/predicted ratio ~3.174
- Olastorp 2:4: observed/predicted ratio ~1.652
- Gluggstorp 3:1: observed/predicted ratio ~0.779

These may be investigated for source QA or transaction-specific circumstances, but any
exclusion must be justified independently of the residual and must not replace the
pre-registered all-12 result.

## Decision status

This is encouraging evidence for ÅkerVärde as an indicative Booli-style estimate, but the
sample is too small and tail failures are too material to call the external validation
finished. Keep v1.0-rc1 frozen; accumulate future independent lagfart/transaction data for
a larger prospective test.

Results CSV SHA256:
`65e29fed34f49eef5d9d4b9713b4994245facfae6d037c03c951d583ce51f0ab`
