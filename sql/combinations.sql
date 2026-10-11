CREATE TABLE skills AS
SELECT id, unnest(skills) AS skill
FROM vacancies;

CREATE TABLE combinations AS
SELECT id, 1 AS size, [skill] AS skills
FROM skills
UNION ALL
SELECT a.id, 2 AS size, [a.skill, b.skill] AS skills
FROM skills a
JOIN skills b ON a.id = b.id AND a.skill < b.skill
UNION ALL
SELECT a.id, 3 AS size, [a.skill, b.skill, c.skill] AS skills
FROM skills a
JOIN skills b ON a.id = b.id AND a.skill < b.skill
JOIN skills c ON a.id = c.id AND b.skill < c.skill;
