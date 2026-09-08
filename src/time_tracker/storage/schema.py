"""Initial schema. Once released, changes belong in a new migration."""

INITIAL_SCHEMA = (
    """
    CREATE TABLE applications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL CHECK (length(trim(name)) > 0),
        ignored INTEGER NOT NULL DEFAULT 0 CHECK (ignored IN (0, 1)),
        track_titles INTEGER NOT NULL DEFAULT 1 CHECK (track_titles IN (0, 1)),
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL CHECK (updated_at >= created_at)
    ) STRICT
    """,
    """
    CREATE TABLE executables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        path TEXT NOT NULL UNIQUE CHECK (length(path) > 0),
        exe_name TEXT NOT NULL CHECK (length(exe_name) > 0),
        first_seen_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL CHECK (last_seen_at >= first_seen_at),
        UNIQUE (id, application_id)
    ) STRICT
    """,
    """
    CREATE TABLE process_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        executable_id INTEGER REFERENCES executables(id),
        pid INTEGER NOT NULL CHECK (pid >= 0),
        process_started_at INTEGER,
        detected_at INTEGER NOT NULL,
        ended_at INTEGER CHECK (ended_at IS NULL OR ended_at >= detected_at)
    ) STRICT
    """,
    """
    CREATE TABLE application_running_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        started_at INTEGER NOT NULL,
        ended_at INTEGER CHECK (ended_at IS NULL OR ended_at >= started_at)
    ) STRICT
    """,
    """
    CREATE TABLE foreground_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id INTEGER NOT NULL REFERENCES applications(id),
        executable_id INTEGER REFERENCES executables(id),
        hwnd INTEGER,
        window_title TEXT,
        started_at INTEGER NOT NULL,
        ended_at INTEGER CHECK (ended_at IS NULL OR ended_at >= started_at),
        FOREIGN KEY (executable_id, application_id)
            REFERENCES executables(id, application_id)
    ) STRICT
    """,
    """
    CREATE TABLE system_state_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        state TEXT NOT NULL CHECK (state IN ('ACTIVE', 'IDLE', 'LOCKED', 'SLEEP')),
        started_at INTEGER NOT NULL,
        ended_at INTEGER CHECK (ended_at IS NULL OR ended_at >= started_at)
    ) STRICT
    """,
    """
    CREATE TABLE tracker_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        started_at INTEGER NOT NULL,
        last_heartbeat_at INTEGER NOT NULL CHECK (last_heartbeat_at >= started_at),
        last_persisted_at INTEGER NOT NULL CHECK (last_persisted_at >= started_at),
        ended_at INTEGER CHECK (
            ended_at IS NULL OR (
                ended_at >= started_at AND ended_at >= last_heartbeat_at
                AND ended_at >= last_persisted_at
            )
        ),
        exit_reason TEXT,
        version TEXT,
        CHECK ((ended_at IS NULL AND exit_reason IS NULL)
            OR (ended_at IS NOT NULL AND exit_reason IS NOT NULL))
    ) STRICT
    """,
    """
    CREATE TABLE application_aliases (
        application_id INTEGER PRIMARY KEY REFERENCES applications(id),
        canonical_application_id INTEGER NOT NULL REFERENCES applications(id),
        created_at INTEGER NOT NULL,
        CHECK (application_id <> canonical_application_id)
    ) STRICT
    """,
    """CREATE INDEX idx_running_app_time
        ON application_running_sessions(application_id, started_at, ended_at)""",
    """CREATE INDEX idx_foreground_app_time
        ON foreground_sessions(application_id, started_at, ended_at)""",
    """CREATE INDEX idx_system_state_time
        ON system_state_sessions(state, started_at, ended_at)""",
    "CREATE INDEX idx_process_executable ON process_sessions(executable_id, detected_at)",
    """CREATE UNIQUE INDEX idx_one_open_running_session
        ON application_running_sessions(application_id) WHERE ended_at IS NULL""",
    """CREATE UNIQUE INDEX idx_one_open_foreground_session
        ON foreground_sessions((1)) WHERE ended_at IS NULL""",
    """CREATE UNIQUE INDEX idx_one_open_system_state_session
        ON system_state_sessions((1)) WHERE ended_at IS NULL""",
    """CREATE UNIQUE INDEX idx_one_open_tracker_run
        ON tracker_runs((1)) WHERE ended_at IS NULL""",
    """CREATE UNIQUE INDEX idx_one_open_process_identity
        ON process_sessions(pid, process_started_at)
        WHERE ended_at IS NULL AND process_started_at IS NOT NULL""",
    """
    CREATE TRIGGER aliases_no_chain_insert BEFORE INSERT ON application_aliases
    WHEN EXISTS (SELECT 1 FROM application_aliases
                 WHERE application_id = NEW.canonical_application_id
                    OR canonical_application_id = NEW.application_id)
    BEGIN
        SELECT RAISE(ABORT, 'Application aliases must point directly to a root');
    END
    """,
    """
    CREATE TRIGGER aliases_no_chain_update BEFORE UPDATE ON application_aliases
    WHEN EXISTS (SELECT 1 FROM application_aliases
                 WHERE application_id <> OLD.application_id
                   AND (application_id = NEW.canonical_application_id
                        OR canonical_application_id = NEW.application_id))
    BEGIN
        SELECT RAISE(ABORT, 'Application aliases must point directly to a root');
    END
    """,
)
