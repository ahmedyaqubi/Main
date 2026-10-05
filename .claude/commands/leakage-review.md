Review the code changed on this branch (`git diff main...HEAD`) strictly for look-ahead bias and data leakage.

Check: any use of data with timestamp > prediction time T; `available_at` missing or not enforced;
end-of-day values (OI, close, EOD chains) used intraday; rolling windows that include the current
unfinished bar; normalization/scalers fit on data beyond the training window; labels computed from
data that leaks into features; option selection using later quotes; calibration fit on the same data
as training; purge/embargo gaps missing for overlapping labels.

Report each finding with file:line, why it leaks, and a failing test that would catch it. Do not fix
anything; only report.
