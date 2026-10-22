# Upload samples

Small CSV files for the dashboard's "Upload a Dataset" box. Every row is a transaction from the public ULB credit-card dataset (the same sample as `../creditcard_sample.csv`), with the columns `Time, V1..V28, Amount, Class`. Each file mixes in a few frauds so that some rows are flagged.

| File | Rows | Frauds |
|---|---|---|
| `transactions_50.csv` | 50 | 3 |
| `transactions_100.csv` | 100 | 5 |
| `transactions_200.csv` | 200 | 10 |

Upload one file at a time and wait for it to finish. On the free hosting each row takes about half a second or more because the database is far away, so large files can run past the host's time limits.
