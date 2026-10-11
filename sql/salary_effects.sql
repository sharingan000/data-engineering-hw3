WITH eligible AS (
    SELECT * FROM vacancies
    WHERE salary > 0 AND currency = $currency AND gross = $gross AND len(skills) > 0
), candidates AS (
    SELECT c.size, c.skills,
           count(*) AS n_with,
           median(v.salary) AS median_with,
           median(v.salary_low) AS median_low,
           median(v.salary_high) AS median_high
    FROM combinations c JOIN eligible v USING (id)
    WHERE c.size IN (2, 3)
    GROUP BY c.size, c.skills
    HAVING count(*) >= $min_support
), comparisons AS (
    SELECT c.*,
           (SELECT count(*) FROM eligible v
            WHERE NOT list_has_all(v.skills, c.skills)) AS n_without,
           (SELECT median(salary) FROM eligible v
            WHERE NOT list_has_all(v.skills, c.skills)) AS median_without
    FROM candidates c
)
SELECT *, median_with - median_without AS difference,
       100.0 * (median_with / median_without - 1) AS difference_pct
FROM comparisons
WHERE n_without >= $min_support AND median_without > 0
ORDER BY difference_pct DESC, n_with DESC, skills;
