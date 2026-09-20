-- Fictional, independently designed teaching schema. No employer-derived data.
CREATE TABLE patients (
    id INTEGER PRIMARY KEY,
    first_name VARCHAR(80) NOT NULL,
    last_name VARCHAR(80) NOT NULL,
    email VARCHAR(120) UNIQUE,
    provider_npi VARCHAR(10) NOT NULL,
    diagnosis_code VARCHAR(10) NOT NULL
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    patient_id INTEGER NOT NULL REFERENCES patients(id),
    priority VARCHAR(10) NOT NULL CHECK (priority IN ('routine', 'urgent')),
    ordered_on DATE NOT NULL
);

CREATE TABLE lab_results (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    loinc_code VARCHAR(10) NOT NULL,
    result_value NUMERIC(6,2) NOT NULL CHECK (result_value >= 0),
    abnormal BOOLEAN NOT NULL
);
