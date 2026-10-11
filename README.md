# Homework 3: ML/RnD vacancies with RustFS, MapReduce and DuckDB

This project implements all seven stages of Homework 3. The source code, results and Russian [PDF report](output/pdf/ml_rnd_vacancies_report.pdf) are published in [sharingan000/data-engineering-hw3](https://github.com/sharingan000/data-engineering-hw3).

The experiment uses 710 ML/RnD vacancy postings selected from 68,770 real HeadHunter postings. Both Python MapReduce and DuckDB read the same private S3 object in a local RustFS instance. All 33,456 frequency rows match exactly: 587 skills, 5,811 pairs and 27,058 triples. Five separate-process runs of each of three configurations are recorded, including the serial MapReduce baseline.

## Reproduce

Use Python 3.12 or newer. These commands run from this directory. The scripts were executed on macOS ARM64; the PDF builder also supports standard DejaVu fonts on Linux. `pdftoppm` is required only for PDF visual checks.

```sh
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.lock
.venv/bin/python bootstrap.py
.venv/bin/python prepare.py --download
.venv/bin/python -m unittest -v
.venv/bin/python run_experiment.py --pilot-only
.venv/bin/python run_experiment.py --repeats 5
.venv/bin/python build_report.py
mkdir -p tmp/pdfs
pdftoppm -scale-to 1400 -png output/pdf/ml_rnd_vacancies_report.pdf tmp/pdfs/report
```

The archive already includes the canonical `data/full.jsonl` and `data/pilot.jsonl`, so a new source download is optional when reproducing the frozen experiment. To rebuild the selection, `prepare.py --download` retrieves Kaggle dataset version 1, verifies its pinned CSV SHA-256 and regenerates both objects. The 78 MB ZIP expands to a 294 MB CSV; preparation is separate from the measured methods.

`bootstrap.py` installs the official DuckDB `httpfs` extension before benchmarking. It reuses `../hw-2/bin/rustfs` if available, otherwise downloads the macOS ARM64 RustFS 1.0.1 release and verifies its published archive SHA-256. On another platform, provide an appropriate RustFS 1.0.1 binary:

```sh
.venv/bin/python run_experiment.py --rustfs /absolute/path/to/rustfs --repeats 5
```

The runner owns its RustFS process and stops it in `finally`. It uses four persistent directories under `runtime/`, `EC:2`, endpoint `127.0.0.1:19010`, bucket `hw3-ml-rnd`, and public disposable local credentials. `RUSTFS_UNSAFE_BYPASS_DISK_CHECK=true` permits this educational single-SSD configuration; the experiment does not test physical disk or node fault tolerance. No unrelated process is terminated and the homework 2 storage is not modified.

## Selection and counting

The input is [Ilya/ilyazawilsiv, IT Vacancies from HeadHunter Website](https://www.kaggle.com/datasets/ilyazawilsiv/it-vacancies-from-headhunter-website), version 1, Apache-2.0, with postings from September 18 to October 17, 2023. It includes Russia and other HeadHunter markets. The original file SHA-256 is `42b443e48059459b3d69393200628052e1168ea97833a3ea5769658fb166751e`.

The ML/RnD selection includes the professional role `Дата-сайентист` or an explicit ML/AI/Data Science/ML research title. The full regular expression is recorded in `artifacts/dataset.json`. The user supplied the segment name, without an official segment file or additional classification rules. Accordingly, the report describes the explicit selection rule rather than claiming that it is an official course-provided partition.

Skills are parsed from PostgreSQL array text, trimmed and Unicode-casefolded. Synonyms remain separate. Each skill and unordered combination is counted at most once per vacancy, regardless of repeated skills or ordering. Empty skill lists contribute no combinations.

MapReduce streams S3 bytes in 64 KiB chunks, retains incomplete UTF-8 JSON lines, maps batches of at most 250 records and reduces local counters. With two workers, at most four map tasks are in flight. Input buffering is bounded, but the final counter grows with the number of distinct combinations. DuckDB independently reads the same S3 object with `httpfs`, unnests unique skills, joins them using strict skill ordering and groups all combinations. The complete queries are in `sql/`.

## Profiling and analysis

The pilot precedes full runs. Each full configuration is measured five times in a fresh process with alternating method order and a warm RustFS/OS cache. End-to-end time includes interpreter startup, imports, S3 reads, computation and JSON output. Process-tree RSS is sampled separately from RustFS; shared pages may be counted more than once and brief peaks may be missed. CPU seconds and operation time are also recorded. DuckDB JSON profiles describe the final aggregate query, while external timings cover the complete worker.

There are 118 postings with any salary. Salary comparisons require known skills, currency and tax status. The largest homogeneous ruble cohort contains 58 postings with net salary (`RUR`, `gross=false`). Missing salaries and unknown skill lists are excluded from contrasts. A full salary range uses its midpoint; a one-sided range uses the reported bound. These are advertised salary proxies, not observed employee pay.

For each pair/triple, the comparison is against vacancies that do not contain the entire combination, within the same cohort. Both groups must contain at least five postings. All 41 qualifying contrasts, selected pointwise bootstrap intervals (2,000 repetitions, fixed seed), a support-10 check, a closed-range-only check and a separate gross salary analysis are saved. The small groups and selection of extremes prevent causal or general statistical-significance claims.

Moscow, Saint Petersburg and Novosibirsk are compared using vacancy counts, skill disclosure, skill frequencies and net ruble salary medians/quartiles. Regional salary groups contain 37, 8 and 8 postings respectively. Their median advertised salary proxies are 250,000, 200,000 and 137,500 rubles per month. The report explains the limits of these comparisons.

## Files and evidence

- `prepare.py`: versioned source acquisition, checksum verification, ML/RnD selection and normalization.
- `bootstrap.py`: extension and RustFS setup.
- `pipeline.py`: streamed MapReduce and independent DuckDB worker.
- `sql/combinations.sql`, `sql/salary_effects.sql`: complete SQL calculations.
- `run_experiment.py`: local storage lifecycle, upload verification, profiling and exact result checks.
- `analyze.py`: salary contrasts, sensitivity analyses and regional summaries.
- `build_report.py`: PDF and plots generated from saved evidence.
- `test_pipeline.py`: seven meaningful regression and property checks.
- `artifacts/dataset.json`, `uploads.json`, `verification.json`: input provenance, S3 round-trip hashes and full exact verification.
- `artifacts/measurements.json`, `environment.json`, `runs/`: timings, sampled memory, hardware/software, worker outputs and SQL profiles.
- `artifacts/frequencies.json`, `analysis.json`: complete frequency tables and business analysis.
- `artifacts/prepare.log`, `pilot.log`, `run.log`, `tests.log`: captured command outputs.
- `artifacts/*.png`: standalone readable plots, saved at 200 dpi.

Only local disposable test credentials are present. Runtime storage, binaries, environments, caches and the large original download are excluded by `.gitignore`.

## Attribution

Derived canonical records retain the source's Apache-2.0 attribution. See [DATA_SOURCES.md](DATA_SOURCES.md). This project does not imply endorsement by the dataset author, HeadHunter, Kaggle or the course. The data describe historical postings; they are not current labor-market estimates.
