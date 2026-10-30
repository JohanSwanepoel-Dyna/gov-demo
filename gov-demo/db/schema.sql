CREATE TABLE citizens (
  id              integer PRIMARY KEY,
  name            text NOT NULL,
  dob             date NOT NULL,
  tfn             char(9) NOT NULL,
  medicare_number char(10) NOT NULL,
  irn             smallint NOT NULL,
  address         text NOT NULL,
  risk_flag       boolean NOT NULL DEFAULT false,
  passcode_hash   text NOT NULL
);

CREATE TABLE claims (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  citizen_id         integer NOT NULL REFERENCES citizens(id),
  payment_type       text NOT NULL,
  status             text NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','eligible','ineligible','submitted','paid','failed')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  submitted_at       timestamptz,
  details            jsonb,
  eligibility_result jsonb,
  reference          text
);
CREATE INDEX claims_citizen_idx ON claims(citizen_id);

CREATE TABLE documents (
  id          bigserial PRIMARY KEY,
  claim_id    uuid NOT NULL REFERENCES claims(id),
  filename    text NOT NULL,
  size_bytes  integer NOT NULL CHECK (size_bytes <= 1048576),
  content     bytea NOT NULL,
  uploaded_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE payment_queue (
  id           bigserial PRIMARY KEY,
  claim_id     uuid NOT NULL REFERENCES claims(id),
  status       text NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','processing','done','failed')),
  attempts     integer NOT NULL DEFAULT 0,
  available_at timestamptz NOT NULL DEFAULT now(),
  locked_at    timestamptz,
  traceparent  text,
  tracestate   text,
  last_error   text
);
CREATE INDEX payment_queue_poll_idx ON payment_queue(status, available_at);

CREATE TABLE payments (
  id           bigserial PRIMARY KEY,
  claim_id     uuid NOT NULL REFERENCES claims(id),
  amount_cents integer NOT NULL,
  legacy_ref   text NOT NULL,
  posted_at    timestamptz NOT NULL DEFAULT now()
);
