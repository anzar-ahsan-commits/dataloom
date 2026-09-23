CREATE TABLE customers (id INT PRIMARY KEY, full_name VARCHAR(80) NOT NULL, email VARCHAR(100) NOT NULL UNIQUE);
CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT NOT NULL REFERENCES customers(id), status VARCHAR(16) NOT NULL CHECK(status IN ('pending','paid','shipped')), note TEXT);
CREATE TABLE order_lines (order_id INT NOT NULL REFERENCES orders(id), line_no INT NOT NULL, units INT NOT NULL CHECK(units BETWEEN 1 AND 8), unit_price NUMERIC(8,2) NOT NULL CHECK(unit_price >= 5), line_total NUMERIC(10,2) NOT NULL CHECK(line_total >= 0), PRIMARY KEY(order_id,line_no));
