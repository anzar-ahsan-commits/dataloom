CREATE TABLE accounts (id INT PRIMARY KEY, company_name VARCHAR(100) NOT NULL);
CREATE TABLE tickets (id INT PRIMARY KEY, account_id INT NOT NULL REFERENCES accounts(id), urgent BOOLEAN NOT NULL, target_minutes INT NOT NULL, response_minutes INT NOT NULL CHECK(response_minutes >= 1), overrun_minutes INT NOT NULL, breached BOOLEAN NOT NULL, notes TEXT);
CREATE TABLE replies (ticket_id INT NOT NULL REFERENCES tickets(id), reply_no INT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(ticket_id,reply_no));
