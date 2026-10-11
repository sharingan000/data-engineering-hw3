from __future__ import annotations

import argparse
import json
from typing import Any

import numpy as np

from pipeline import ROOT, duck_connection, load_sql_input, save_json, sql_counts


def dictionaries(result: Any) -> list[dict[str, Any]]:
    names: list[str] = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def bootstrap_difference(with_values: list[float], without_values: list[float],
                         rng: np.random.Generator) -> list[float]:
    with_array = np.asarray(with_values)
    without_array = np.asarray(without_values)
    differences: list[float] = []
    for _ in range(2000):
        differences.append(float(np.median(rng.choice(with_array, len(with_array)))
                                 - np.median(rng.choice(without_array, len(without_array)))))
    return np.quantile(differences, [0.025, 0.975]).tolist()


def salary_analysis(connection: Any, support: int) -> dict[str, Any]:
    """Compare skill combinations within the largest homogeneous ruble salary cohort.

    Args:
        connection: Any - DuckDB connection with vacancies and combinations tables.
        support: int - Minimum size of each compared group.

    Return:
        dict[str, Any]: Salary cohort, all supported contrasts and exploratory bootstrap intervals.
    """
    cohorts = dictionaries(connection.execute('''
        SELECT currency, gross, count(*) AS n, median(salary) AS median_salary
        FROM vacancies WHERE salary > 0 AND len(skills) > 0
        GROUP BY ALL ORDER BY n DESC, currency, gross
    '''))
    comparable = [cohort for cohort in cohorts if cohort['currency'] == 'RUR' and cohort['gross'] is not None]
    if not comparable:
        raise ValueError('No ruble salary cohort with known gross/net status')
    chosen: dict[str, Any] = comparable[0]
    params: dict[str, Any] = {'currency': chosen['currency'], 'gross': chosen['gross'], 'min_support': support}
    effects = dictionaries(connection.execute((ROOT / 'sql/salary_effects.sql').read_text(), params))
    tops: dict[str, list[dict[str, Any]]] = {}
    rng = np.random.default_rng(20261011)
    for size in (2, 3):
        for direction in ('increase', 'decrease'):
            candidates = [effect for effect in effects if effect['size'] == size and
                          (effect['difference'] > 0 if direction == 'increase' else effect['difference'] < 0)]
            candidates.sort(key=lambda row: ((-1 if direction == 'increase' else 1) * row['difference_pct'],
                                            -row['n_with'], row['skills']))
            tops[f'{size}_{direction}'] = candidates[:5]
            for effect in candidates[:5]:
                values = connection.execute('''
                    SELECT salary, list_has_all(skills, ?) AS includes
                    FROM vacancies WHERE salary > 0 AND currency = ? AND gross = ? AND len(skills) > 0
                ''', [effect['skills'], chosen['currency'], chosen['gross']]).fetchall()
                with_values: list[float] = [value for value, includes in values if includes]
                without_values: list[float] = [value for value, includes in values if not includes]
                effect['difference_ci95'] = bootstrap_difference(with_values, without_values, rng)
    bounded_count: int = connection.execute('''
        SELECT count(*) FROM vacancies WHERE salary > 0 AND currency = ? AND gross = ?
        AND salary_low IS NOT NULL AND salary_high IS NOT NULL AND len(skills) > 0
    ''', [chosen['currency'], chosen['gross']]).fetchone()[0]
    other: list[dict[str, Any]] = []
    for cohort in comparable[1:]:
        alternate = dictionaries(connection.execute((ROOT / 'sql/salary_effects.sql').read_text(),
                                 {**params, 'gross': cohort['gross']}))
        other.append({'cohort': cohort, 'supported_contrasts': len(alternate), 'effects': alternate})
    bounded_sql: str = (ROOT / 'sql/salary_effects.sql').read_text().replace(
        "WHERE salary > 0 AND currency = $currency AND gross = $gross",
        "WHERE salary > 0 AND currency = $currency AND gross = $gross "
        "AND salary_low IS NOT NULL AND salary_high IS NOT NULL")
    bounded_effects = dictionaries(connection.execute(bounded_sql, params))
    stronger_support = dictionaries(connection.execute((ROOT / 'sql/salary_effects.sql').read_text(),
                                   {**params, 'min_support': 10}))
    return {'cohorts': cohorts, 'chosen_cohort': chosen, 'minimum_support': support,
            'definition': 'Median midpoint/one-sided advertised bound in vacancies containing all skills '
                          'versus vacancies not containing the complete combination; other skills allowed',
            'supported_contrasts': len(effects), 'effects': effects, 'top': tops,
            'bounded_salary_rows': bounded_count, 'bounded_effects': bounded_effects,
            'support10_contrasts': stronger_support,
            'other_ruble_cohorts': other, 'bootstrap_repetitions': 2000, 'bootstrap_seed': 20261011,
            'bootstrap_scope': 'Pointwise exploratory intervals for selected extremes; not adjusted for selection or multiplicity'}


def regions_analysis(connection: Any, cohort: dict[str, Any]) -> list[dict[str, Any]]:
    regions = dictionaries(connection.execute('''
        SELECT region, count(*) AS vacancies, count_if(len(skills) > 0) AS with_skills,
               count_if(salary > 0) AS with_any_salary,
               count_if(salary > 0 AND currency = $currency AND gross = $gross) AS with_salary,
               median(salary) FILTER (WHERE currency = $currency AND gross = $gross) AS median_salary,
               quantile_cont(salary, 0.25) FILTER (WHERE currency = $currency AND gross = $gross) AS q25,
               quantile_cont(salary, 0.75) FILTER (WHERE currency = $currency AND gross = $gross) AS q75
        FROM vacancies WHERE region IN ('Москва', 'Санкт-Петербург', 'Новосибирск')
        GROUP BY region ORDER BY vacancies DESC, region LIMIT 3
    ''', {'currency': cohort['currency'], 'gross': cohort['gross']}))
    for region in regions:
        region['skill_frequencies'] = dictionaries(connection.execute('''
            SELECT skill, count(*) AS vacancies FROM skills JOIN vacancies USING (id)
            WHERE region = ? GROUP BY skill ORDER BY vacancies DESC, skill
        ''', [region['region']]))
        region['top_skills'] = region['skill_frequencies'][:10]
        region['experience'] = dictionaries(connection.execute('''
            SELECT experience, count(*) AS vacancies FROM vacancies WHERE region = ?
            GROUP BY experience ORDER BY vacancies DESC, experience
        ''', [region['region']]))
    if len(regions) != 3:
        raise ValueError('Fewer than three regions in the selected variant')
    return regions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--min-support', type=int, default=5)
    args = parser.parse_args()
    if args.min_support < 2:
        raise ValueError('Minimum support must be at least two vacancies')
    with duck_connection() as connection:
        load_sql_input(connection, 'full.jsonl')
        sql_counts(connection)
        salary = salary_analysis(connection, args.min_support)
        regions = regions_analysis(connection, salary['chosen_cohort'])
        top_skills = dictionaries(connection.execute('''
            SELECT skill, count(*) AS vacancies FROM skills
            GROUP BY skill ORDER BY vacancies DESC, skill LIMIT 20
        '''))
        analysis: dict[str, Any] = {'salary': salary, 'regions': regions, 'top_skills': top_skills}
        save_json(ROOT / 'artifacts/analysis.json', analysis)
        print(json.dumps({'salary_cohort': salary['chosen_cohort'],
                          'supported_contrasts': salary['supported_contrasts'],
                          'regions': [{k: v for k, v in region.items() if k not in ('top_skills', 'experience')}
                                      for region in regions]}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
