-- Durable coordinator decisions and acknowledgments.
CREATE TABLE IF NOT EXISTS
    distributed_transactions (
        transaction_id UUID PRIMARY KEY,
        client_request_id UUID NOT NULL UNIQUE,
        request_hash CHAR(64) NOT NULL,
        source_account VARCHAR(20) NOT NULL,
        destination_account VARCHAR(20) NOT NULL,
        source_shard VARCHAR(20) NOT NULL,
        destination_shard VARCHAR(20) NOT NULL,
        amount_minor BIGINT NOT NULL CHECK (amount_minor > 0),
        status VARCHAR(30) NOT NULL CHECK (
            status IN (
                'INITIATED',
                'PREPARING',
                'PREPARED',
                'COMMIT_DECIDED',
                'ABORT_DECIDED',
                'COMPLETED'
            )
        ),
        decision VARCHAR(10) CHECK (decision IN ('COMMIT', 'ABORT')),
        created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
        decided_at TIMESTAMPTZ,
        CHECK (source_account <> destination_account)
    );

CREATE TABLE IF NOT EXISTS
    transaction_participants (
        transaction_id UUID NOT NULL REFERENCES distributed_transactions (transaction_id),
        shard_id VARCHAR(20) NOT NULL,
        prepared_gid VARCHAR(200) NOT NULL UNIQUE,
        prepare_ack_at TIMESTAMPTZ,
        decision_ack_at TIMESTAMPTZ,
        PRIMARY KEY (transaction_id, shard_id)
    );

-- Durable one-shot fault injection markers survive Coordinator container restarts.
CREATE TABLE IF NOT EXISTS
    fault_injections (
        name VARCHAR(100) PRIMARY KEY,
        injected_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
    );
