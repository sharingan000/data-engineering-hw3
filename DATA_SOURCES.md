# Data attribution

The canonical JSONL files are derived from **IT Vacancies from HeadHunter Website**, published by **Ilya (`ilyazawilsiv`)** on Kaggle, dataset version 1, Apache License 2.0.

- Dataset: https://www.kaggle.com/datasets/ilyazawilsiv/it-vacancies-from-headhunter-website
- Versioned download: https://www.kaggle.com/api/v1/datasets/download/ilyazawilsiv/it-vacancies-from-headhunter-website/IT_vacancies.csv?datasetVersionNumber=1
- Upstream source: publicly advertised HeadHunter vacancies.
- Posting dates stated by the dataset publisher: September 18 through October 17, 2023.
- Downloaded and analyzed: October 11, 2026.
- Original CSV SHA-256: `42b443e48059459b3d69393200628052e1168ea97833a3ea5769658fb166751e`.
- License: https://www.apache.org/licenses/LICENSE-2.0

Changes made: select ML/RnD postings by the documented role/title rule; keep only fields needed for the assignment; parse skill arrays, trim and casefold skill strings; derive salary proxies from positive advertised bounds; serialize the result as UTF-8 JSONL. Names of source skills are retained apart from whitespace and case normalization. Personal contact details, descriptions and employer data are not included in the derived files.

The source version and all derived input hashes are recorded in `artifacts/dataset.json`. `artifacts/uploads.json` records verified S3 object hashes. The exact source rows can be regenerated with `prepare.py --download`.
