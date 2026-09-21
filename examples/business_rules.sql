-- Fictional fulfillment fixture demonstrating cross-field business consistency.
CREATE TABLE fulfillments (
    id INTEGER PRIMARY KEY,
    units INTEGER NOT NULL CHECK (units >= 1),
    unit_price NUMERIC(7,2) NOT NULL,
    subtotal NUMERIC(9,2) NOT NULL,
    discount NUMERIC(7,2) NOT NULL,
    total NUMERIC(9,2) NOT NULL CHECK (total >= 0),
    created_on DATE NOT NULL,
    shipped_on DATE NOT NULL CHECK (shipped_on >= created_on),
    service_tier VARCHAR(12) NOT NULL
);
