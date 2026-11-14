CREATE TABLE clients (
    client_id SERIAL PRIMARY KEY,
    username VARCHAR(64) UNIQUE NOT NULL,
    full_name VARCHAR(128) NOT NULL,
    prosthesis_model VARCHAR(64) NOT NULL,
    prosthesis_type VARCHAR(32) NOT NULL,
    device_id VARCHAR(64) UNIQUE NOT NULL
);

INSERT INTO clients (username, full_name, prosthesis_model, prosthesis_type, device_id) VALUES
    ('prothetic1', 'Prothetic One',   'BionicPRO Flex v2', 'кистевой', 'd67d279a-b64a-4646-8ea6-4a562fbb960e'),
    ('prothetic2', 'Prothetic Two',   'BionicPRO Grip v3', 'кистевой', '4d070f89-5fd1-4853-a7cf-66be63f27217'),
    ('prothetic3', 'Prothetic Three', 'BionicPRO Arm v1',  'локтевой', 'ffa00c7a-d9f1-42b4-a8bc-c3ed6e46eda3');