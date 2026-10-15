-- RDDH: схема БД компенсации расходов сотрудников (PostgreSQL 16).
-- Источник истины для ERD (database/erd.puml). Деньги — только в копейках (bigint), без float.
-- Владелец данных — сервис expense_store (ADR-0002); другие сервисы в БД не ходят.

BEGIN;

CREATE TYPE user_role AS ENUM ('employee', 'accountant');

-- draft        — расход создан, файл ещё не загружен
-- processing   — файл в очереди/конвейере распознавания
-- recognized   — поля распознаны, ждут подтверждения сотрудником
-- submitted    — сотрудник отправил расход
-- in_review    — спорный: требует решения бухгалтера (needs_review)
-- approved     — компенсируется, ждёт реестра
-- rejected     — отклонён с причиной
-- in_registry  — включён в реестр на выплату
-- reimbursed   — компенсирован
-- no_receipt   — заявлен без документа
CREATE TYPE expense_status AS ENUM (
    'draft', 'processing', 'recognized', 'submitted', 'in_review',
    'approved', 'rejected', 'in_registry', 'reimbursed', 'no_receipt'
);

CREATE TYPE receipt_kind AS ENUM ('photo', 'pdf');
CREATE TYPE payment_method AS ENUM ('cash', 'card', 'sbp', 'unknown');
CREATE TYPE recognition_source AS ENUM ('qr', 'pdf_text', 'ocr', 'manual');
CREATE TYPE registry_status AS ENUM ('draft', 'sent', 'approved', 'paid');

CREATE TABLE company (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app_user (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id     bigint NOT NULL REFERENCES company (id),
    email          text NOT NULL UNIQUE,
    full_name      text NOT NULL,
    role           user_role NOT NULL,
    password_hash  text NOT NULL,
    is_active      boolean NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now()
);

-- Справочник категорий = политика компенсации компании (SC-14: категория только отсюда).
CREATE TABLE expense_category (
    id                     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id             bigint NOT NULL REFERENCES company (id),
    parent_id              bigint REFERENCES expense_category (id),
    code                   text NOT NULL,
    name                   text NOT NULL,
    is_reimbursable        boolean NOT NULL,
    monthly_limit_kopecks  bigint CHECK (monthly_limit_kopecks IS NULL OR monthly_limit_kopecks > 0),
    is_active              boolean NOT NULL DEFAULT true,
    UNIQUE (company_id, code)
);

CREATE TABLE merchant (
    id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_name       text NOT NULL UNIQUE,
    inn                  varchar(12),
    default_category_id  bigint REFERENCES expense_category (id)
);

-- «ООО Спорт-Лайф», «СПОРТЛАЙФ МСК» → один merchant (SC-04).
CREATE TABLE merchant_alias (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    merchant_id  bigint NOT NULL REFERENCES merchant (id),
    raw_name     text NOT NULL UNIQUE,
    confirmed    boolean NOT NULL DEFAULT false
);

CREATE TABLE expense (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id          bigint NOT NULL REFERENCES company (id),
    employee_id         bigint NOT NULL REFERENCES app_user (id),
    status              expense_status NOT NULL DEFAULT 'draft',
    merchant_raw        text,
    merchant_id         bigint REFERENCES merchant (id),
    amount_kopecks      bigint CHECK (amount_kopecks IS NULL OR amount_kopecks > 0),
    purchased_at        timestamptz,
    payment_method      payment_method NOT NULL DEFAULT 'unknown',
    -- Фискальные реквизиты из QR (54-ФЗ): ФН + ФД + ФП — ключ дедупликации чека.
    fiscal_fn           varchar(16),
    fiscal_fd           varchar(10),
    fiscal_fp           varchar(10),
    category_id         bigint REFERENCES expense_category (id),
    is_reimbursable     boolean,
    confidence          numeric(4, 3) CHECK (confidence BETWEEN 0 AND 1),
    needs_review        boolean NOT NULL DEFAULT false,
    review_reason       text,
    employee_comment    text,
    duplicate_of        bigint REFERENCES expense (id),
    no_receipt          boolean NOT NULL DEFAULT false,
    rejection_reason    text,
    decided_by          bigint REFERENCES app_user (id),
    submitted_at        timestamptz,
    flagged_at          timestamptz,
    decided_at          timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT rejected_has_reason CHECK (status <> 'rejected' OR rejection_reason IS NOT NULL),
    CONSTRAINT review_has_reason CHECK (NOT needs_review OR review_reason IS NOT NULL),
    CONSTRAINT no_receipt_status CHECK (NOT no_receipt OR status IN ('no_receipt', 'rejected'))
);

CREATE UNIQUE INDEX expense_fiscal_uniq
    ON expense (fiscal_fn, fiscal_fd, fiscal_fp)
    WHERE fiscal_fn IS NOT NULL AND duplicate_of IS NULL;
CREATE INDEX expense_employee_status_idx ON expense (employee_id, status);
CREATE INDEX expense_company_status_idx ON expense (company_id, status);

-- Позиции чека: смешанный чек (абонемент + массаж) делится по категориям на уровне позиции.
CREATE TABLE expense_item (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    expense_id      bigint NOT NULL REFERENCES expense (id) ON DELETE CASCADE,
    name            text NOT NULL,
    quantity        numeric(12, 3) NOT NULL DEFAULT 1 CHECK (quantity > 0),
    price_kopecks   bigint NOT NULL CHECK (price_kopecks >= 0),
    amount_kopecks  bigint NOT NULL CHECK (amount_kopecks >= 0),
    vat_rate        varchar(8),
    category_id     bigint REFERENCES expense_category (id),
    is_reimbursable boolean
);

-- Метаданные файла; сам объект лежит в S3-хранилище (SeaweedFS) по storage_key (E-04: ≤ 5 МБ после сжатия).
CREATE TABLE receipt_file (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    expense_id      bigint NOT NULL REFERENCES expense (id) ON DELETE CASCADE,
    kind            receipt_kind NOT NULL,
    storage_key     text NOT NULL UNIQUE,
    mime_type       text NOT NULL,
    sha256          char(64) NOT NULL,
    bytes_original  bigint NOT NULL CHECK (bytes_original > 0),
    bytes_stored    bigint NOT NULL CHECK (bytes_stored > 0 AND bytes_stored <= 5242880),
    uploaded_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX receipt_file_sha_idx ON receipt_file (sha256);

-- Один прогон конвейера: тайминги, токены и стоимость (E-01…E-03, SC-15).
CREATE TABLE recognition_run (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    expense_id        bigint NOT NULL REFERENCES expense (id) ON DELETE CASCADE,
    receipt_file_id   bigint REFERENCES receipt_file (id),
    rerun_of          bigint REFERENCES recognition_run (id),
    source            recognition_source NOT NULL,
    llm_provider      text,
    llm_model         text,
    prompt_version    text,
    tokens_in         integer CHECK (tokens_in >= 0),
    tokens_out        integer CHECK (tokens_out >= 0),
    cost_kopecks      numeric(12, 4) CHECK (cost_kopecks >= 0),
    t_ocr_ms          integer,
    t_extract_ms      integer,
    t_classify_ms     integer,
    t_total_ms        integer,
    json_valid        boolean,
    degraded          boolean NOT NULL DEFAULT false,
    error             text,
    raw_result        jsonb,
    created_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX recognition_run_expense_idx ON recognition_run (expense_id);

-- История смен статуса (SC-20: у каждого события есть время и актор).
CREATE TABLE expense_status_log (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    expense_id   bigint NOT NULL REFERENCES expense (id) ON DELETE CASCADE,
    from_status  expense_status,
    to_status    expense_status NOT NULL,
    actor_id     bigint REFERENCES app_user (id),
    actor_kind   text NOT NULL CHECK (actor_kind IN ('employee', 'accountant', 'system')),
    comment      text,
    at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX expense_status_log_expense_idx ON expense_status_log (expense_id, at);

CREATE TABLE registry (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id     bigint NOT NULL REFERENCES company (id),
    period_start   date NOT NULL,
    period_end     date NOT NULL,
    status         registry_status NOT NULL DEFAULT 'draft',
    total_kopecks  bigint NOT NULL DEFAULT 0 CHECK (total_kopecks >= 0),
    created_by     bigint NOT NULL REFERENCES app_user (id),
    created_at     timestamptz NOT NULL DEFAULT now(),
    sent_at        timestamptz,
    CHECK (period_end >= period_start),
    UNIQUE (company_id, period_start, period_end)
);

-- Строка реестра: включённая или исключённая с причиной (SC-17 сумма, SC-18 причина).
CREATE TABLE registry_item (
    registry_id       bigint NOT NULL REFERENCES registry (id) ON DELETE CASCADE,
    expense_id        bigint NOT NULL REFERENCES expense (id),
    included          boolean NOT NULL,
    amount_kopecks    bigint NOT NULL CHECK (amount_kopecks >= 0),
    exclusion_reason  text,
    PRIMARY KEY (registry_id, expense_id),
    CONSTRAINT excluded_has_reason CHECK (included OR exclusion_reason IS NOT NULL)
);

CREATE UNIQUE INDEX registry_item_expense_included_uniq
    ON registry_item (expense_id) WHERE included;

COMMIT;
