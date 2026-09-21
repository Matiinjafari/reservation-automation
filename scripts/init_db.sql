CREATE TABLE IF NOT EXISTS reservations (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    start_time TIME NOT NULL,
    end_time TIME NOT NULL,
    name TEXT,
    email TEXT,
    phone TEXT,
    reason TEXT,
    room TEXT,
    deposit INTEGER,
    resource_type TEXT,
    attendees_count INTEGER
);

CREATE TABLE IF NOT EXISTS reservation_logs (
    id SERIAL PRIMARY KEY,
    email TEXT,
    name TEXT,
    phone TEXT,
    request_date DATE,
    request_time TIME,
    status TEXT,
    reason TEXT,
    room TEXT,
    resource_type TEXT,
    attendees_count INTEGER
);
