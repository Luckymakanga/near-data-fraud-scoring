# Training Data

`creditcard_sample.csv` is a sample drawn from the **ULB Credit Card Fraud
Detection dataset** - the canonical, extensively-studied fraud detection
benchmark dataset, used in thousands of papers and tutorials. It contains
real anonymized European credit card transactions from September 2013.

Source: [David-Egea/Creditcard-fraud-detection](https://huggingface.co/datasets/David-Egea/Creditcard-fraud-detection)
on Hugging Face, mirroring the original
[Kaggle `mlg-ulb/creditcardfraud`](https://www.kaggle.com/datasets/mlg-ulb/creditcardfraud)
dataset. This file is a 20,492-row sample: every fraudulent transaction in
the full 284,807-row dataset (492 rows) plus a random sample of 20,000
non-fraud transactions, to keep the fraud rate usable for training (2.4%)
without bloating the repo with the full ~150MB file.

Columns: `Time` (seconds elapsed since the first transaction in the
dataset), `V1`-`V28` (anonymized features - the result of a PCA
transformation applied to the original transaction features to protect
cardholder confidentiality, so they have no individually interpretable
real-world meaning), `Amount` (transaction amount), `Class` (1 = fraud).

**Why this dataset, and not the system's earlier Uganda-context data:**
`V1`-`V28` genuinely correlate with fraud (up to 0.33 for `V17`) - verified
before adopting it, after an earlier PaySim-style mirror turned out to have
essentially zero correlation between its fraud label and any feature
(a dead end; see project history). Because the predictive features here are
anonymized PCA components with no human-meaningful interpretation, the
admin dashboard's "Analyze a Transaction" feature works by loading a real
transaction from this dataset rather than letting an admin type one in by
hand - there's nothing meaningful a person could type for `V1`-`V28`.
