INSERT INTO
    accounts (account_id, balance_minor)
SELECT
    'A' || LPAD(n::text, 4, '0'),
    100000
FROM
    generate_series(1, 1000) AS n ON CONFLICT (account_id)
DO NOTHING;
