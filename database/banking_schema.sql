-- Common banking schema installed independently on Shard A and Shard B.
CREATE TABLE IF NOT EXISTS
    accounts (
        account_id VARCHAR(20) PRIMARY KEY,
        balance_minor BIGINT DEFAULT 0 NOT NULL CHECK (balance_minor >= 0),
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );

CREATE TABLE IF NOT EXISTS
    request_receipts (
        request_id UUID PRIMARY KEY,
        request_hash CHAR(64) NOT NULL,
        operation_type VARCHAR(30) NOT NULL,
        status VARCHAR(20) NOT NULL CHECK (status IN ('PROCESSING', 'COMPLETED')),
        response_http_status INT,
        response_payload JSONB,
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        CHECK (
            status = 'PROCESSING'
            OR (
                response_http_status IS NOT NULL
                AND response_payload IS NOT NULL
            )
        )
    );

CREATE TABLE IF NOT EXISTS
    transfer_entries (
        transaction_id UUID NOT NULL,
        account_id VARCHAR(20) NOT NULL REFERENCES accounts (account_id),
        delta_minor BIGINT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        PRIMARY KEY (transaction_id, account_id)
    );

-- One durable outcome per 2PC participant transaction.
CREATE TABLE IF NOT EXISTS
    participant_outcomes (
        transaction_id UUID PRIMARY KEY,
        request_hash CHAR(64) NOT NULL,
        outcome VARCHAR(20) NOT NULL CHECK (outcome IN ('COMMITTED', 'ABORTED')),
        finalized_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
