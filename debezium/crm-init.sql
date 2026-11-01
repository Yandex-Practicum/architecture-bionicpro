CREATE TABLE IF NOT EXISTS public.crm_clients (
    client_id text PRIMARY KEY,
    user_id text NOT NULL,
    client_name text NOT NULL,
    prosthesis_ids text[] NOT NULL
);

ALTER TABLE public.crm_clients REPLICA IDENTITY FULL;

INSERT INTO public.crm_clients (
    client_id,
    user_id,
    client_name,
    prosthesis_ids
)
VALUES
(
    '101',
    '77f882ae-ab7f-4a96-a7c9-4302405d2195',
    'Первый клиент',
    ARRAY['P001', 'P002']
),
(
    '102',
    'demo-user-2',
    'Второй клиент',
    ARRAY['P003']
)
ON CONFLICT (client_id) DO NOTHING;