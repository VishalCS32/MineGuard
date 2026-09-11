-- MineGuard Authentication Schema Migration (§002)
-- PostgreSQL / TimescaleDB compatible schema for production deployments

-- 1. Users table
CREATE TABLE IF NOT EXISTS users (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(128) NOT NULL,
    email          VARCHAR(255) UNIQUE,
    phone_number   VARCHAR(32) UNIQUE,
    password_hash  VARCHAR(255),
    google_id      VARCHAR(128) UNIQUE,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    phone_verified BOOLEAN NOT NULL DEFAULT FALSE,
    role           VARCHAR(32) NOT NULL DEFAULT 'user',
    created_at     DOUBLE PRECISION NOT NULL,
    updated_at     DOUBLE PRECISION NOT NULL,
    last_login_at  DOUBLE PRECISION
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone_number);
CREATE INDEX IF NOT EXISTS idx_users_google ON users(google_id);

-- 2. User Sessions table
CREATE TABLE IF NOT EXISTS user_sessions (
    id          VARCHAR(64) PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) UNIQUE NOT NULL,
    expires_at  DOUBLE PRECISION NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL,
    ip_address  VARCHAR(64),
    user_agent  VARCHAR(255)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_hash ON user_sessions(token_hash);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON user_sessions(expires_at);

-- 3. Password Reset Tokens
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  VARCHAR(64) UNIQUE NOT NULL,
    expires_at  DOUBLE PRECISION NOT NULL,
    used        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reset_user ON password_reset_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_reset_hash ON password_reset_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_reset_expiry ON password_reset_tokens(expires_at);

-- 4. Verification Codes (Email and SMS verification)
CREATE TABLE IF NOT EXISTS verification_codes (
    id          SERIAL PRIMARY KEY,
    user_id     INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_type   VARCHAR(16) NOT NULL,
    code        VARCHAR(64) NOT NULL,
    expires_at  DOUBLE PRECISION NOT NULL,
    created_at  DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_verify_user ON verification_codes(user_id);
