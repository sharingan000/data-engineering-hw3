from __future__ import annotations

import json
import os
import statistics
import textwrap
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT: Path = Path(__file__).resolve().parent
ARTIFACTS: Path = ROOT / 'artifacts'
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / '.matplotlib'))

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, PageBreak, Paragraph, Preformatted, SimpleDocTemplate, Spacer, Table, TableStyle

WIDTH: float = A4[0] - 36 * mm
BLUE: str = '#183F67'
MUTED: str = '#526577'


def load(name: str) -> Any:
    return json.loads((ARTIFACTS / name).read_text())


def number(value: float | int | None, decimals: int = 0) -> str:
    return '-' if value is None else f'{value:,.{decimals}f}'.replace(',', ' ')


def benchmark_summary(measurements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for method, workers, label in [('mapreduce', 1, 'MapReduce, 1 процесс'),
                                    ('mapreduce', 2, 'MapReduce, 2 процесса'),
                                    ('duckdb', 2, 'DuckDB, 2 потока')]:
        selected = [row for row in measurements if row['source'] == 'full'
                    and row['method'] == method and row['workers'] == workers]
        times: list[float] = [row['end_to_end_seconds'] for row in selected]
        rows.append({'label': label, 'runs': len(times), 'seconds': statistics.median(times),
                     'minimum': min(times), 'maximum': max(times),
                     'core_seconds': statistics.median(row['core_seconds'] for row in selected),
                     'cpu_seconds': statistics.median(row['cpu_seconds'] for row in selected),
                     'rss_mib': statistics.median(row['client_tree_peak_rss_bytes'] / 1024**2 for row in selected),
                     'max_rss_mib': max(row['client_tree_peak_rss_bytes'] / 1024**2 for row in selected)})
    return rows


def plots(analysis: dict[str, Any], benchmarks: list[dict[str, Any]], total: int) -> None:
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'axes.titleweight': 'bold'})
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.1), layout='constrained')
    labels: list[str] = ['MR 1', 'MR 2', 'DuckDB 2']
    for axis, field, title in zip(axes, ['seconds', 'rss_mib'], ['Полное время, с', 'Пик RSS клиентов, МиБ']):
        values = [row[field] for row in benchmarks]
        bars = axis.bar(labels, values, color=['#267592', '#73A6B5', '#183F67'])
        axis.set_title(title, fontsize=12)
        axis.set_ylim(0, max(values) * 1.25)
        axis.bar_label(bars, fmt='%.3f' if field == 'seconds' else '%.1f', padding=4)
    fig.savefig(ARTIFACTS / 'benchmark_time_and_memory.png', dpi=200)
    plt.close(fig)
    skills: list[dict[str, Any]] = analysis['top_skills'][:12][::-1]
    fig, axis = plt.subplots(figsize=(8.6, 3.3), layout='constrained')
    bars = axis.barh([row['skill'] for row in skills], [row['vacancies'] for row in skills], color='#267592')
    axis.bar_label(bars, padding=4)
    axis.set_xlabel('Вакансий с навыком')
    axis.set_xlim(0, max(row['vacancies'] for row in skills) * 1.15)
    fig.savefig(ARTIFACTS / 'ml_rnd_top_skills.png', dpi=200)
    plt.close(fig)
    regions: list[dict[str, Any]] = analysis['regions']
    top: list[str] = [row['skill'] for row in analysis['top_skills'][:5]]
    fig, axis = plt.subplots(figsize=(8.6, 3.5), layout='constrained')
    for index, region in enumerate(regions):
        counts: dict[str, int] = {row['skill']: row['vacancies'] for row in region['skill_frequencies']}
        values: list[float] = [100 * counts.get(skill, 0) / region['vacancies'] for skill in top]
        axis.bar([i + (index - 1) * 0.25 for i in range(len(top))], values, 0.25,
                 label=f"{region['region']} (n={region['vacancies']})",
                 color=['#183F67', '#267592', '#87B7BF'][index])
    axis.set_xticks(range(len(top)), top, rotation=12)
    axis.set_ylabel('Доля всех вакансий города, %')
    axis.legend(frameon=False, fontsize=9)
    fig.savefig(ARTIFACTS / 'regional_skill_demand.png', dpi=200)
    plt.close(fig)


def footer(canvas: Any, document: Any) -> None:
    canvas.saveState()
    canvas.setFont('Body', 8)
    canvas.setFillColor(colors.HexColor(MUTED))
    canvas.drawString(18 * mm, 12 * mm, 'Data Engineering | ДЗ 3 | ML, RnD | 11.10.2026')
    canvas.drawRightString(A4[0] - 18 * mm, 12 * mm, str(document.page))
    canvas.restoreState()


def main() -> None:
    """Build the Russian homework report from recorded experiment evidence.

    Args:
        None

    Return:
        None: A PDF report and three reproducible PNG figures are written to disk.
    """
    fonts: Path = Path('/System/Library/Fonts/Supplemental')
    if not fonts.exists():
        fonts = Path('/usr/share/fonts/truetype/dejavu')
    for name, mac, linux in [('Body', 'Arial.ttf', 'DejaVuSans.ttf'),
                              ('Bold', 'Arial Bold.ttf', 'DejaVuSans-Bold.ttf'),
                              ('Mono', 'Courier New.ttf', 'DejaVuSansMono.ttf')]:
        pdfmetrics.registerFont(TTFont(name, str(fonts / (mac if (fonts / mac).exists() else linux))))
    pdfmetrics.registerFontFamily('Body', normal='Body', bold='Bold', italic='Body', boldItalic='Bold')
    styles: dict[str, ParagraphStyle] = {
        'body': ParagraphStyle('body', fontName='Body', fontSize=10, leading=14, spaceAfter=9),
        'small': ParagraphStyle('small', fontName='Body', fontSize=8.7, leading=12, spaceAfter=7),
        'title': ParagraphStyle('title', fontName='Bold', fontSize=23, leading=28, spaceAfter=14, textColor=colors.HexColor(BLUE)),
        'h1': ParagraphStyle('h1', fontName='Bold', fontSize=17, leading=22, spaceAfter=12, textColor=colors.HexColor(BLUE)),
        'h2': ParagraphStyle('h2', fontName='Bold', fontSize=11.5, leading=15, spaceBefore=7, spaceAfter=7, keepWithNext=True, textColor=colors.HexColor(BLUE)),
        'cell': ParagraphStyle('cell', fontName='Body', fontSize=8.4, leading=11.2),
        'code': ParagraphStyle('code', fontName='Mono', fontSize=7.6, leading=10.2, spaceAfter=10),
    }
    story: list[Any] = []

    def paragraph(text: str, style: str = 'body') -> None:
        story.append(Paragraph(text, styles[style]))

    def table(rows: list[list[str]], widths: list[float]) -> None:
        cells = [[Paragraph(escape(str(value)), styles['cell']) for value in row] for row in rows]
        item = Table(cells, colWidths=widths, repeatRows=1, hAlign='LEFT')
        item.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#EAF1F7')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LINEBELOW', (0, 0), (-1, 0), 0.8, colors.HexColor('#B8CADA')),
            ('LINEBELOW', (0, 1), (-1, -1), 0.25, colors.HexColor('#D8E2EC')),
            ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ]))
        story.extend([item, Spacer(1, 8)])

    def code(value: str) -> None:
        wrapped: str = '\n'.join('\n'.join(textwrap.wrap(line, width=98, replace_whitespace=False,
                                                        drop_whitespace=False) or [''])
                                 for line in value.splitlines())
        story.append(Preformatted(wrapped, styles['code']))

    dataset: dict[str, Any] = load('dataset.json')
    analysis: dict[str, Any] = load('analysis.json')
    verification: dict[str, Any] = load('verification.json')
    measurements: list[dict[str, Any]] = load('measurements.json')
    environment: dict[str, Any] = load('environment.json')
    salary: dict[str, Any] = analysis['salary']
    benchmarks = benchmark_summary(measurements)
    plots(analysis, benchmarks, dataset['selected_rows'])
    (ROOT / 'output/pdf').mkdir(parents=True, exist_ok=True)

    paragraph('ДЗ 3. Аналитика вакансий<br/>с RustFS и DuckDB', 'title')
    paragraph('Карпов Данил Иванович, группа J3310<br/>Индивидуальный вариант: ML, RnD. Эксперимент: 11 октября 2026 года.', 'small')
    paragraph('1. Цель и источник данных', 'h2')
    paragraph('Построен воспроизводимый пайплайн: отбор вакансий своего варианта, загрузка в объектное хранилище, независимый подсчёт частот средствами MapReduce и SQL, полная сверка результатов, профилирование, анализ зарплат и трёх регионов.')
    paragraph('Использован открытый набор Ilya (ilyazawilsiv) «IT Vacancies from HeadHunter Website», Kaggle, версия 1, Apache 2.0 [1]. Период исходных публикаций: 18.09-17.10.2023. Файл содержит вакансии России и других стран присутствия HeadHunter. Это историческая выборка, а не состояние рынка в октябре 2026 года.')
    table([['Показатель', 'Значение'],
           ['Исходный CSV', f"{number(dataset['source_rows'])} записей; {number(dataset['source_bytes'])} байт"],
           ['Вакансии ML/RnD', str(dataset['selected_rows'])],
           ['С указанными навыками', f"{dataset['rows_with_skills']} ({100 * dataset['rows_with_skills'] / dataset['selected_rows']:.1f}%)"],
           ['С указанной зарплатой в любой валюте', f"{dataset['rows_with_salary']} ({100 * dataset['rows_with_salary'] / dataset['selected_rows']:.1f}%)"],
           ['Повторяющиеся id', str(dataset['duplicates_removed'])],
           ['Объект full.jsonl', f"{number(dataset['full_bytes'])} байт; UTF-8, одна вакансия на строку"]],
          [WIDTH * 0.54, WIDTH * 0.46])
    paragraph('Отбор включает профессиональную роль «Дата-сайентист» либо названия с ML, AI, Data Science, Machine/Deep Learning, R&amp;D/RnD, Research Engineer/Scientist, машинным обучением, нейронными сетями или компьютерным зрением. Это явное воспроизводимое правило для указанного пользователем сегмента; официальная готовая выгрузка варианта не предоставлялась.', 'small')
    paragraph('Навыки очищены от пробелов по краям и приведены к единому регистру Unicode casefold. Синонимы не объединяются: «machine learning» и «машинное обучение» остаются разными исходными метками. Отсутствие списка навыков не считается доказательством отсутствия навыков.', 'small')
    paragraph('В ДЗ 2 использовался другой CSV без зарплат. Здесь повторно применён проверенный бинарный файл RustFS 1.0.1, а данные и хранилище ДЗ 3 изолированы от предыдущего опыта.', 'small')

    story.append(PageBreak())
    paragraph('2. Хранилище и независимые расчёты', 'h1')
    paragraph(f"Стенд: {escape(environment['platform'])}; Python {environment['python']}, DuckDB {environment['duckdb']}. RustFS 1.0.1 запущен на 127.0.0.1:19010, bucket hw3-ml-rnd. Использованы четыре локальные папки и EC:2; это один компьютер и один SSD. Физическая отказоустойчивость и распределённый кластер этим опытом не проверяются.")
    paragraph('Загружены pilot.jsonl (100 вакансий) и full.jsonl (710 вакансий). Оба объекта прочитаны обратно через GetObject; размеры и SHA-256 совпали с локальными исходниками. Перед и после серии замеров проверяется неизменность ETag объекта.', 'small')
    paragraph('Собственная реализация MapReduce', 'h2')
    paragraph('S3 GetObject читается блоками по 65 536 байт. Незавершённая JSON-строка переносится в следующий блок, поэтому граница чанка может проходить внутри UTF-8 символа. Map получает до 250 вакансий, удаляет повторные навыки внутри каждой вакансии и выдаёт счётчики неупорядоченных сочетаний размеров 1, 2 и 3. Reduce суммирует локальные счётчики. Для двух процессов одновременно ожидаются не более четырёх map-задач.')
    paragraph('Сложность по времени пропорциональна сумме C(k,1)+C(k,2)+C(k,3), где k - число уникальных навыков вакансии. Чтение входа ограничено чанками и пакетами, но итоговый словарь занимает память пропорционально числу разных сочетаний. Этот вариант не обещает постоянного расхода памяти.', 'small')
    paragraph('Независимый SQL в DuckDB', 'h2')
    paragraph('Расширение httpfs и S3 secret дают прямое чтение s3://hw3-ml-rnd/full.jsonl [2]. DuckDB самостоятельно разворачивает списки навыков и строит сочетания соединениями по id; частоты считаются GROUP BY. SQL не использует результат Python MapReduce.')
    code("SELECT a.id, [a.skill, b.skill, c.skill] AS skills\nFROM skills a\nJOIN skills b ON a.id = b.id AND a.skill < b.skill\nJOIN skills c ON a.id = c.id AND b.skill < c.skill;\n\nSELECT size, skills, count(*)\nFROM combinations\nGROUP BY ALL;")
    table([['Полная сверка', 'Навыки', 'Пары', 'Тройки'],
           ['Пилот: 100 вакансий', *[str(verification['pilot']['distinct_combinations'][str(n)]) for n in (1, 2, 3)]],
           ['Полный набор: 710 вакансий', *[number(verification['full']['distinct_combinations'][str(n)]) for n in (1, 2, 3)]]],
          [WIDTH * 0.52, WIDTH * 0.16, WIDTH * 0.16, WIDTH * 0.16])
    paragraph('Совпали все 33 456 строк (размер сочетания, список навыков, частота) во всех 15 полных запусках. Дополнительно прошли 7 тестов: ручной пример, случайные множества, повторные навыки, параллельность, PostgreSQL-массивы, UTF-8 на границе чанка и зарплатная база сравнения.', 'small')

    story.append(PageBreak())
    paragraph('3. Время и использование памяти', 'h1')
    paragraph('Каждый запуск выполнен в новом процессе. Измеряется полное время от запуска до выхода, включая импорты, чтение S3, расчёт и запись одной и той же полной таблицы JSON. Отдельно сохранены время основной функции и CPU-время родителя вместе с завершёнными дочерними процессами.')
    paragraph('После пилота сделано по 5 запусков трёх конфигураций; порядок методов чередовался. Кеш ОС и RustFS не сбрасывался. Следовательно, это измерения с прогретым хранилищем, а не холодного скачивания. Настройка расширений, подготовка данных, загрузка S3, аналитика и PDF в сравнение методов не входят.', 'small')
    table([['Метод', 'Полное время, с', 'Мин.-макс., с', 'Пик RSS, МиБ'],
           *[[row['label'], number(row['seconds'], 3), f"{row['minimum']:.3f}-{row['maximum']:.3f}", number(row['rss_mib'], 1)] for row in benchmarks]],
          [WIDTH * 0.35, WIDTH * 0.21, WIDTH * 0.24, WIDTH * 0.20])
    story.append(Image(str(ARTIFACTS / 'benchmark_time_and_memory.png'), width=WIDTH, height=WIDTH * 3.1 / 9))
    paragraph('На графике и в таблице показаны медианы по пяти запускам. RSS измерялся как сумма резидентной памяти всего дерева клиентских процессов, включая map-процессы; RustFS измерялся отдельно. Пауза между опросами - 5 мс плюс время самого обхода дерева. Короткие пики могут быть пропущены, а общие страницы процессов могут учитываться повторно: это оценка RSS, не PSS.', 'small')
    server_peak: float = max(row['rustfs_peak_rss_bytes'] for row in measurements) / 1024**2
    paragraph(f'Максимум наблюдаемого RSS RustFS за всю серию: {server_peak:.1f} МиБ. Лимит памяти DuckDB - 1 ГиБ; SQL материализует вход и строки сочетаний. Подробный профиль финального GROUP BY сохранён отдельно в *.duckdb-profile.json; он не заменяет замер всего процесса.', 'small')
    mr_serial: float = benchmarks[0]['seconds']
    mr_parallel: float = benchmarks[1]['seconds']
    duck: float = benchmarks[2]['seconds']
    paragraph(f'На этой выборке DuckDB выполнил полный цикл за {duck:.3f} с, последовательный MapReduce - за {mr_serial:.3f} с, параллельный - за {mr_parallel:.3f} с. Два map-процесса здесь не ускорили обработку: их запуск и передача пакетов дороже выигрыша на 710 записях. Разрыв между DuckDB и последовательным вариантом невелик; переносить его на большие данные без нового измерения нельзя.')

    story.append(PageBreak())
    paragraph('4. Навыки и зарплата: методика', 'h1')
    paragraph('Единица анализа - вакансия, а не упоминание навыка. Для закрытой зарплатной вилки используется середина (from+to)/2; для односторонней - единственная объявленная граница. Это оценка предложенной оплаты, а не фактическая зарплата сотрудника. Пропуски не заменяются нулями; неположительные, нечисловые и обратные вилки исключаются из зарплатных расчётов.')
    paragraph('Валюты и зарплаты до/после налога не смешиваются. Основная группа выбрана по максимальному числу вакансий с известными навыками, рублёвой зарплатой и известным налоговым статусом: RUR, gross=false, то есть оплата «на руки». Валютный пересчёт и предположения о ставке налога не применяются.')
    cohort: dict[str, Any] = salary['chosen_cohort']
    table([['Основная зарплатная группа', 'Значение'],
           ['С известной зарплатой и списком навыков', str(cohort['n'])],
           ['Медиана группы, рублей в месяц', number(cohort['median_salary'])],
           ['Из них с обеими границами вилки', str(salary['bounded_salary_rows'])],
           ['Минимальный размер каждой сравниваемой группы', str(salary['minimum_support'])],
           ['Пар и троек, прошедших этот порог', str(salary['supported_contrasts'])]],
          [WIDTH * 0.72, WIDTH * 0.28])
    paragraph('Для каждого сочетания сравниваются две непересекающиеся группы одной зарплатной когорты: вакансии, содержащие все навыки сочетания, и остальные вакансии с известным списком навыков. Дополнительные навыки разрешены. Разница = медиана первой группы минус медиана второй; относительная разница = 100 × (медиана первой / медиана второй - 1).')
    paragraph('В каждой группе требуется не меньше 5 вакансий. Это исследовательский порог для ограниченной зарплатной выборки, а не гарантия устойчивости. Для отобранных крайних результатов рассчитаны точечные 95% бутстреп-интервалы разницы медиан: 2 000 повторов, seed=20261011. Интервалы не скорректированы на перебор сочетаний и выбор крайних результатов.', 'small')
    paragraph('Наиболее частые навыки во всех 710 вакансиях', 'h2')
    story.append(Image(str(ARTIFACTS / 'ml_rnd_top_skills.png'), width=WIDTH, height=WIDTH * 3.3 / 8.6))

    story.append(PageBreak())
    paragraph('5. Наибольшие различия медиан', 'h1')
    paragraph('Все суммы в таблицах указаны в тысячах рублей в месяц «на руки». n+ - число вакансий с сочетанием, n- - без полного сочетания. Сравнение проведено внутри основной группы из 58 вакансий. Полная таблица из 41 сочетания сохранена в analysis.json.', 'small')

    def effects_table(key: str, title: str) -> None:
        paragraph(title, 'h2')
        rows: list[list[str]] = [['Сочетание', 'n+ / n-', 'Медиана + / -', 'Разница, %']]
        for row in salary['top'][key][:3]:
            rows.append([' + '.join(row['skills']), f"{row['n_with']} / {row['n_without']}",
                         f"{row['median_with'] / 1000:g} / {row['median_without'] / 1000:g}",
                         f"{row['difference_pct']:+.1f}"])
        table(rows, [WIDTH * 0.48, WIDTH * 0.14, WIDTH * 0.23, WIDTH * 0.15])

    effects_table('2_increase', 'Пары с наибольшим превышением медианы')
    effects_table('3_increase', 'Тройки с наибольшим превышением медианы')
    effects_table('2_decrease', 'Пары с наименьшей медианой относительно базы')
    effects_table('3_decrease', 'Тройки с наименьшей медианой относительно базы')
    paragraph('В положительном направлении выделяются NLP + PyTorch и NLP + Python + PyTorch. Отрицательная разница у Git + Python и других сочетаний не означает, что эти навыки вредят доходу: группы могут различаться опытом, работодателем, регионом и характером позиции. Одновременные «machine learning» и «машинное обучение» означают две исходные метки, а не два независимых умения.', 'small')

    story.append(PageBreak())
    paragraph('6. Устойчивость зарплатных выводов', 'h1')
    rows: list[list[str]] = [['Сочетание', 'Разница медиан, тыс. руб.', 'Точечный 95% интервал, тыс. руб.']]
    for key in ['2_increase', '3_increase', '2_decrease', '3_decrease']:
        row = salary['top'][key][0]
        interval = row['difference_ci95']
        rows.append([' + '.join(row['skills']), f"{row['difference'] / 1000:+g}",
                     f"[{interval[0] / 1000:g}; {interval[1] / 1000:g}]"])
    table(rows, [WIDTH * 0.47, WIDTH * 0.23, WIDTH * 0.30])
    paragraph('При повышении порога до 10 наблюдений в каждой группе остаётся только одна пара и ни одной тройки. Следовательно, результаты для троек чувствительны к малой выборке. Нельзя назвать весь рейтинг устойчивым или статистически подтверждённым только на основании этой выгрузки.')
    paragraph(f"Если оставить только закрытые вилки, остаются {salary['bounded_salary_rows']} зарплатных наблюдений и {len(salary['bounded_effects'])} допустимых сочетаний при пороге 5. Для gross=true расчёт выполнен отдельно; эта группа содержит {salary['other_ruble_cohorts'][0]['cohort']['n'] if salary['other_ruble_cohorts'] else 0} вакансий с навыками. Полные результаты обеих проверок сохранены в analysis.json.")
    bounded: dict[tuple[str, ...], dict[str, Any]] = {tuple(row['skills']): row for row in salary['bounded_effects']}
    sensitivity: list[list[str]] = [['Сочетание', 'Все вилки: n / Δ, %', 'Только закрытые: n / Δ, %']]
    for key in ['2_increase', '3_increase', '2_decrease', '3_decrease']:
        row = salary['top'][key][0]
        counterpart = bounded.get(tuple(row['skills']))
        sensitivity.append([' + '.join(row['skills']), f"{row['n_with']} / {row['difference_pct']:+.1f}",
                            f"{counterpart['n_with']} / {counterpart['difference_pct']:+.1f}" if counterpart else 'Не проходит порог 5'])
    table(sensitivity, [WIDTH * 0.47, WIDTH * 0.25, WIDTH * 0.28])
    paragraph('Только 118 из 710 вакансий раскрывают зарплату, а известные навыки и сопоставимая оплата «на руки» одновременно доступны лишь для 58. Пропуски, выборочная публикация зарплат и отсутствие поправок на опыт могут смещать оценку. Работа показывает наблюдаемые различия в исторических объявлениях; причинный эффект конкретного навыка здесь не установлен.')

    story.append(PageBreak())
    paragraph('7. Сравнение трёх регионов', 'h1')
    paragraph('Выбраны Москва, Санкт-Петербург и Новосибирск - три российских города с наибольшим числом ML/RnD-вакансий в этой выборке. Регион вакансии относится к месту объявления, а не обязательно к месту проживания удалённого сотрудника.')
    regions = analysis['regions']
    table([['Город', 'Всего / с навыками', 'n зарплат RUR net', 'Медиана, тыс. руб.', 'Q25-Q75, тыс. руб.'],
           *[[row['region'], f"{row['vacancies']} / {row['with_skills']}", str(row['with_salary']),
              f"{row['median_salary'] / 1000:g}", f"{row['q25'] / 1000:g}-{row['q75'] / 1000:g}"] for row in regions]],
          [WIDTH * 0.24, WIDTH * 0.19, WIDTH * 0.19, WIDTH * 0.18, WIDTH * 0.20])
    paragraph('Для медиан города взяты все вакансии с известной рублёвой зарплатой «на руки», включая объявления без списка навыков; это отличается от зарплатного сравнения сочетаний, где список навыков обязателен. Прочие валюты и gross=true исключены одинаково для трёх городов.', 'small')
    story.append(Image(str(ARTIFACTS / 'regional_skill_demand.png'), width=WIDTH, height=WIDTH * 3.5 / 8.6))
    paragraph('Спрос на навык показан как доля всех вакансий соответствующего города, где навык явно указан, а не как число упоминаний. Разный уровень заполнения списков навыков влияет на доли: у Москвы они известны в 263 из 438 объявлений, у Петербурга в 31 из 58, у Новосибирска в 11 из 16.', 'small')
    paragraph('Москва лидирует по числу объявлений и медиане раскрытых зарплат. Интерквартильные интервалы городов перекрываются, а для Петербурга и Новосибирска доступны только по 8 сопоставимых зарплат. Поэтому разница медиан описывает эту выборку; её недостаточно для вывода о гарантированной региональной надбавке.')

    story.append(PageBreak())
    paragraph('8. Воспроизведение и выводы команд', 'h1')
    paragraph('Все команды выполняются из корня репозитория data-engineering-hw3 (локально: homeworks/hw-3). Зависимости закреплены в requirements.lock. bootstrap.py устанавливает httpfs и использует бинарный RustFS из ДЗ 2 либо скачивает проверенный релиз 1.0.1. Повторная подготовка сверяет SHA-256 исходного CSV.', 'small')
    code('uv venv .venv --python 3.12\nuv pip install --python .venv/bin/python -r requirements.lock\n.venv/bin/python bootstrap.py\n.venv/bin/python prepare.py --download\n.venv/bin/python -m unittest -v\n.venv/bin/python run_experiment.py --repeats 5\n.venv/bin/python build_report.py')
    paragraph('Фрагменты фактического вывода', 'h2')
    serial: dict[str, Any] = next(row for row in measurements if row['source'] == 'full'
                                 and row['method'] == 'mapreduce' and row['workers'] == 1)
    worker_stats: dict[str, Any] = json.loads((ROOT / serial['result_path']).with_suffix('.stats.json').read_text())
    code(json.dumps({key: worker_stats[key] for key in ['method', 'rows', 'bytes', 'chunks', 'map_tasks',
                                                      'core_seconds', 'cpu_seconds']}, ensure_ascii=False, indent=2))
    code(json.dumps(verification['full'], ensure_ascii=False, indent=2))
    paragraph('Полные выводы: artifacts/prepare.log, pilot.log, run.log, tests.log; измерения: measurements.json; сверка: verification.json; S3: uploads.json. Схема и контрольные суммы: dataset.json. SQL-профили и выводы каждого процесса находятся в artifacts/runs/.', 'small')
    paragraph('Источники', 'h2')
    paragraph('[1] Ilya (ilyazawilsiv). IT Vacancies from HeadHunter Website, version 1. Kaggle, Apache 2.0. '
              '<link href="https://www.kaggle.com/datasets/ilyazawilsiv/it-vacancies-from-headhunter-website" color="#267592">Страница набора</link>. Период 18.09-17.10.2023.', 'small')
    paragraph('[2] DuckDB. S3 API Support: httpfs, secrets и прямое чтение объектов. '
              '<link href="https://duckdb.org/docs/current/core_extensions/httpfs/s3api" color="#267592">Официальная документация</link>.', 'small')
    paragraph('[3] RustFS 1.0.1, повторно использованный локальный стенд ДЗ 2. '
              '<link href="https://github.com/rustfs/rustfs/releases/tag/1.0.1" color="#267592">Релиз</link>.', 'small')
    paragraph('Код, результаты вычислений, профили времени и памяти и PDF опубликованы в публичном репозитории '
              '<link href="https://github.com/sharingan000/data-engineering-hw3" color="#267592">sharingan000/data-engineering-hw3</link>.', 'small')
    document = SimpleDocTemplate(str(ROOT / 'output/pdf/ml_rnd_vacancies_report.pdf'), pagesize=A4,
                                 leftMargin=18 * mm, rightMargin=18 * mm, topMargin=17 * mm,
                                 bottomMargin=22 * mm, title='Data Engineering - Homework 3 - ML, RnD',
                                 author='Данил Карпов')
    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(str(ROOT / 'output/pdf/ml_rnd_vacancies_report.pdf'))


if __name__ == '__main__':
    main()
