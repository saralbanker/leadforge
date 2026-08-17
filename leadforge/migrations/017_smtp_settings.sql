-- Migration 017: Seed default SMTP Configuration Keys into Settings Table

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000001', 'smtp.host', '', 'SMTP Hostname (e.g. smtp.gmail.com)');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000002', 'smtp.port', '587', 'SMTP Port (e.g. 587 or 465)');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000003', 'smtp.username', '', 'SMTP Account Username');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000004', 'smtp.password', '', 'SMTP Account Password');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000005', 'smtp.from_email', '', 'Sender Email Address');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000006', 'smtp.from_name', 'Orvion', 'Sender Display Name');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000007', 'smtp.use_tls', 'true', 'Enable TLS (true/false)');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000008', 'smtp.reply_to', '', 'Reply-To Email Address');

INSERT OR IGNORE INTO settings (id, key, value, description)
VALUES ('019fa2bf-1000-7000-8000-000000000009', 'smtp.timeout', '30', 'SMTP Connection Timeout (seconds)');
