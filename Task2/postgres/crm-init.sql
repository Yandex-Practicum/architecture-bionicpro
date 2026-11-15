CREATE SCHEMA crm;

CREATE TABLE crm.clients (
    id UUID PRIMARY KEY,
    identity_subject UUID NOT NULL UNIQUE,
    country_code TEXT NOT NULL
);

CREATE TABLE crm.prostheses (
    id UUID PRIMARY KEY,
    client_id UUID NOT NULL REFERENCES crm.clients(id),
    serial_number TEXT NOT NULL,
    model TEXT NOT NULL
);

INSERT INTO crm.clients VALUES
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', '11111111-1111-1111-1111-111111111111', 'RU'),
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', '22222222-2222-2222-2222-222222222222', 'RU'),
    ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3', '33333333-3333-3333-3333-333333333333', 'RU');

INSERT INTO crm.prostheses VALUES
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1', 'P-TEST-001', 'Hand-X'),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2', 'P-TEST-002', 'Hand-Y'),
    ('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3', 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa3', 'P-TEST-003', 'Hand-Z');
