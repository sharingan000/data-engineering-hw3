from __future__ import annotations

import itertools
import random
import unittest
import hashlib
from collections import Counter
from typing import Any
from unittest.mock import patch

import duckdb

from pipeline import ROOT, count_rows, map_reduce, sql_counts, streamed_records
from prepare import parse_boolean, parse_skills, positive


def sql_result(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    with duckdb.connect() as connection:
        connection.execute('CREATE TABLE vacancies (id VARCHAR, skills VARCHAR[])')
        connection.executemany('INSERT INTO vacancies VALUES (?, list_sort(list_distinct(?)))',
                               [(str(i), row['skills']) for i, row in enumerate(records)])
        return sql_counts(connection)


class FrequencyTests(unittest.TestCase):
    def test_hand_calculated_frequencies(self) -> None:
        records: list[dict[str, Any]] = [{'skills': ['python', 'sql', 'python']},
                                        {'skills': ['sql', 'git', 'python']},
                                        {'skills': []}, {'skills': ['git']}]
        expected: Counter[tuple[str, ...]] = Counter({('python',): 2, ('sql',): 2, ('git',): 2,
                                                     ('python', 'sql'): 2, ('git', 'python'): 1,
                                                     ('git', 'sql'): 1, ('git', 'python', 'sql'): 1})
        actual, tasks = map_reduce(iter(records), batch_rows=2, workers=1)
        self.assertEqual(actual, expected)
        self.assertEqual(tasks, 2)
        self.assertEqual(sql_result(records), count_rows(expected))

    def test_parallel_batches_match_serial(self) -> None:
        records: list[dict[str, Any]] = [{'skills': ['a', 'b', 'c']}, {'skills': ['b', 'a']},
                                        {'skills': []}, {'skills': ['c', 'c']}]
        self.assertEqual(map_reduce(records, 1, 2), map_reduce(records, 1, 1))

    def test_random_against_subset_membership_oracle(self) -> None:
        rng = random.Random(20261011)
        vocabulary: list[str] = ['c++', 'c#', 'sql', 'python', 'машинное обучение', 'a\nb', 'x"y']
        records: list[dict[str, Any]] = [{'skills': rng.choices(vocabulary, k=rng.randrange(12))}
                                        for _ in range(80)]
        expected: Counter[tuple[str, ...]] = Counter()
        for size in (1, 2, 3):
            for combo in itertools.combinations(sorted(vocabulary), size):
                frequency: int = sum(set(combo).issubset(record['skills']) for record in records)
                if frequency:
                    expected[combo] = frequency
        actual, _ = map_reduce(iter(records), 7, 1)
        self.assertEqual(actual, expected)
        self.assertEqual(sql_result(records), count_rows(expected))

    def test_invalid_configuration(self) -> None:
        with self.assertRaises(ValueError):
            map_reduce([], 1, 0)
        with self.assertRaises(ValueError):
            map_reduce([], 0, 1)


class SourceTests(unittest.TestCase):
    def test_postgres_arrays_preserve_punctuation(self) -> None:
        self.assertEqual(parse_skills('{Python,"Machine Learning","a,b",Python}'),
                         ['python', 'machine learning', 'a,b', 'python'])
        self.assertEqual(parse_skills('{}'), [])
        self.assertEqual(parse_boolean('false'), False)
        self.assertEqual(parse_boolean(''), None)
        self.assertEqual(positive('not a salary'), None)
        self.assertEqual(positive('-5'), None)
        self.assertEqual(positive('nan'), None)
        self.assertEqual(positive('inf'), None)
        self.assertEqual(positive('100'), 100)

    def test_stream_handles_utf8_split_and_no_final_newline(self) -> None:
        records: list[dict[str, Any]] = [{'skills': ['машинное обучение', 'a\nb']}, {'skills': []}]
        import json

        data: bytes = '\n'.join(json.dumps(row, ensure_ascii=False) for row in records).encode()

        class Body:
            closed: bool = False

            def iter_chunks(self, chunk_size: int) -> Any:
                for index in range(0, len(data), chunk_size):
                    yield data[index:index + chunk_size]

            def close(self) -> None:
                self.closed = True

        class Client:
            def get_object(self, **kwargs: Any) -> dict[str, Any]:
                return {'Body': body, 'ResponseMetadata': {'HTTPStatusCode': 200}}

        body = Body()
        stats: dict[str, Any] = {}
        with patch('pipeline.s3_client', return_value=Client()):
            self.assertEqual(list(streamed_records('fixture', 1, stats)), records)
        self.assertTrue(body.closed)
        self.assertEqual(stats['sha256'], hashlib.sha256(data).hexdigest())
        self.assertEqual(stats['rows'], 2)
        self.assertEqual(stats['chunks'], len(data))


class SalaryTests(unittest.TestCase):
    def test_complement_baseline_and_support(self) -> None:
        with duckdb.connect() as connection:
            connection.execute('''CREATE TABLE vacancies (
                id VARCHAR, skills VARCHAR[], salary DOUBLE, salary_low DOUBLE,
                salary_high DOUBLE, currency VARCHAR, gross BOOLEAN
            )''')
            connection.executemany('INSERT INTO vacancies VALUES (?, ?, ?, ?, ?, ?, ?)', [
                ('1', ['a', 'b', 'c'], 200, 180, 220, 'RUR', False),
                ('2', ['a', 'b', 'c'], 300, 280, 320, 'RUR', False),
                ('3', ['a'], 100, 100, 100, 'RUR', False),
                ('4', ['c'], 120, 120, 120, 'RUR', False),
                ('5', ['a', 'b'], 9000, 9000, 9000, 'USD', False),
                ('6', ['a', 'b'], 9000, 9000, 9000, 'RUR', True),
                ('7', ['a', 'b'], None, None, None, 'RUR', False),
            ])
            sql_counts(connection)
            columns = ['size', 'skills', 'n_with', 'median_with', 'median_low', 'median_high',
                       'n_without', 'median_without', 'difference', 'difference_pct']
            rows = connection.execute((ROOT / 'sql/salary_effects.sql').read_text(),
                                      {'gross': False, 'currency': 'RUR', 'min_support': 2}).fetchall()
            pair = next(dict(zip(columns, row)) for row in rows if row[1] == ['a', 'b'])
            self.assertEqual(pair['n_with'], 2)
            self.assertEqual(pair['n_without'], 2)
            self.assertEqual(pair['median_with'], 250)
            self.assertEqual(pair['median_without'], 110)
            self.assertAlmostEqual(pair['difference_pct'], 100 * (250 / 110 - 1))


if __name__ == '__main__':
    unittest.main(verbosity=2)
