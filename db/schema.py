"""SQL DDL definitions for Zivon core tables (0001) and Wave-E addenda (0002).

Supports both PostgreSQL 16 (production / CI cluster) and SQLite 3 (local unit
and contract test execution in key-free / containerless environments). Every
table, column, CHECK constraint, and index traces to `docs/backend/db-spec.md`
and `docs/specs/gaps/gap-register.md` (GAP-014).
"""

from __future__ import annotations

from typing import Final

CORE_TABLES_0001: Final[tuple[str, ...]] = (
    "device",
    "consent_record",
    "session",
    "voice_turn",
    "credit_ledger",
    "guard_counter",
    "guard_profile",
    "telemetry_event",
    "problem_report",
    "content_page",
    "page_version",
    "live_pointer",
    "object_catalog",
    "narration_asset",
    "language_bundle",
    "outbox",
    "factory_run",
    "audit_log",
    "abuse_bucket",
    "deletion_request",
    "daily_stats",
)

ADDENDA_TABLES_0002: Final[tuple[str, ...]] = (
    "locale_fallback",
    "glossary_term",
    "translation_memory_entry",
    "block_translation",
    "ui_string",
    "eval_run",
    "eval_card_result",
    "eval_defect_sample_result",
    "eval_human_edit",
    "eval_kid_session",
    "log_events",
)

ALL_TABLES: Final[tuple[str, ...]] = CORE_TABLES_0001 + ADDENDA_TABLES_0002

LOCALE_ENUM_CHECK: Final[str] = (
    "('bn-IN','en-IN','gu-IN','hi-IN','kn-IN','ml-IN','mr-IN','pa-IN','ta-IN','te-IN','hinglish')"
)


def get_revision_0001_up_sql(dialect: str = "postgresql") -> list[str]:
    """Return DDL statements for revision 0001 (20 core tables + guard_profile seed)."""
    auto_pk = (
        "BIGSERIAL PRIMARY KEY"
        if dialect == "postgresql"
        else "INTEGER PRIMARY KEY AUTOINCREMENT"
    )
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"
    ts_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TEXT"
    now_default = "NOW()" if dialect == "postgresql" else "CURRENT_TIMESTAMP"
    bool_false = "FALSE" if dialect == "postgresql" else "0"

    stmts = [
        f"""
        CREATE TABLE IF NOT EXISTS device (
            device_pseudo_id TEXT PRIMARY KEY,
            first_seen_at {ts_type} NOT NULL DEFAULT {now_default},
            last_seen_at {ts_type} NOT NULL DEFAULT {now_default},
            locale TEXT DEFAULT 'en-IN' CHECK (locale IS NULL OR locale IN {LOCALE_ENUM_CHECK})
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS consent_record (
            consent_id TEXT PRIMARY KEY,
            device_pseudo_id TEXT NOT NULL REFERENCES device(device_pseudo_id) ON DELETE CASCADE,
            consent_version TEXT NOT NULL,
            notice_version TEXT NOT NULL,
            guardian_flag BOOLEAN NOT NULL,
            action TEXT NOT NULL CHECK (action IN ('granted', 'declined', 'withdrawn')),
            source TEXT NOT NULL DEFAULT 'overlay' CHECK (source IN ('overlay', 'imported')),
            recorded_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_consent_device_recorded ON consent_record(device_pseudo_id, recorded_at DESC)",
        f"""
        CREATE TABLE IF NOT EXISTS session (
            session_id TEXT PRIMARY KEY,
            device_pseudo_id TEXT NOT NULL REFERENCES device(device_pseudo_id) ON DELETE CASCADE,
            course_id TEXT,
            class_level INTEGER CHECK (class_level IS NULL OR (class_level >= 6 AND class_level <= 12)),
            lang TEXT NOT NULL CHECK (lang IN {LOCALE_ENUM_CHECK}),
            mode TEXT NOT NULL DEFAULT 'guide' CHECK (mode IN ('guide', 'tell')),
            consent_ref TEXT REFERENCES consent_record(consent_id) ON DELETE SET NULL,
            guardian_ref TEXT,
            flags {json_type} NOT NULL DEFAULT '{{}}',
            coverage {json_type} DEFAULT '[]',
            coverage_rev INTEGER NOT NULL DEFAULT 0,
            coverage_updated_at {ts_type},
            started_at {ts_type} NOT NULL DEFAULT {now_default},
            ended_at {ts_type},
            turn_count INTEGER NOT NULL DEFAULT 0,
            coverage_synced BOOLEAN NOT NULL DEFAULT {bool_false}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_session_device_started ON session(device_pseudo_id, started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_session_started_at ON session(started_at)",
        f"""
        CREATE TABLE IF NOT EXISTS voice_turn (
            turn_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES session(session_id) ON DELETE CASCADE,
            turn_seq INTEGER NOT NULL,
            modality TEXT NOT NULL CHECK (modality IN ('voice', 'typed')),
            transcript TEXT,
            tutor_text TEXT NOT NULL,
            tags {json_type} NOT NULL DEFAULT '[]',
            detected_lang TEXT CHECK (detected_lang IS NULL OR detected_lang IN {LOCALE_ENUM_CHECK}),
            anchor {json_type},
            latency {json_type} NOT NULL DEFAULT '{{}}',
            redirect_flag BOOLEAN NOT NULL DEFAULT {bool_false},
            mode TEXT NOT NULL DEFAULT 'guide' CHECK (mode IN ('guide', 'tell')),
            audio_retained BOOLEAN NOT NULL DEFAULT {bool_false} CHECK (audio_retained = {bool_false}),
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (session_id, turn_seq)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_voice_turn_created_at ON voice_turn(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_voice_turn_session_seq ON voice_turn(session_id, turn_seq)",
        f"""
        CREATE TABLE IF NOT EXISTS credit_ledger (
            entry_id TEXT PRIMARY KEY,
            session_id TEXT REFERENCES session(session_id) ON DELETE SET NULL,
            device_pseudo_id TEXT NOT NULL,
            model TEXT NOT NULL CHECK (model IN ('prisma', 'timbre', 'gemma_gpu')),
            units TEXT NOT NULL CHECK (units IN ('seconds', 'chars', 'tokens')),
            amount NUMERIC NOT NULL CHECK (amount >= 0),
            bucket TEXT NOT NULL DEFAULT 'daily' CHECK (bucket IN ('daily', 'reserved')),
            cost_credits NUMERIC,
            created_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_credit_ledger_created_at ON credit_ledger(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_credit_ledger_device_created ON credit_ledger(device_pseudo_id, created_at)",
        f"""
        CREATE TABLE IF NOT EXISTS guard_counter (
            counter_id TEXT PRIMARY KEY,
            period TEXT NOT NULL,
            scope TEXT NOT NULL CHECK (scope IN ('global', 'device')),
            scope_key TEXT NOT NULL,
            used_credits NUMERIC NOT NULL DEFAULT 0 CHECK (used_credits >= 0),
            state TEXT NOT NULL DEFAULT 'ok' CHECK (state IN ('ok', 'warn', 'exhausted', 'reserved_mode')),
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (period, scope, scope_key)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS guard_profile (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            mode TEXT NOT NULL DEFAULT 'normal' CHECK (mode IN ('normal', 'demo')),
            global_tranche NUMERIC NOT NULL DEFAULT 1000,
            per_user_cap NUMERIC NOT NULL DEFAULT 30,
            demo_global_tranche NUMERIC NOT NULL DEFAULT 1000,
            demo_per_user_cap NUMERIC NOT NULL DEFAULT 100,
            warn_threshold_pct NUMERIC NOT NULL DEFAULT 15,
            total_budget_credits NUMERIC NOT NULL DEFAULT 10000,
            demo_reserve_pct NUMERIC NOT NULL DEFAULT 40,
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            updated_by TEXT NOT NULL DEFAULT 'system'
        )
        """,
        """
        INSERT INTO guard_profile (
            id, mode, global_tranche, per_user_cap,
            demo_global_tranche, demo_per_user_cap, warn_threshold_pct,
            total_budget_credits, demo_reserve_pct, updated_by
        ) VALUES (1, 'normal', 1000, 30, 1000, 100, 15, 10000, 40, 'seed')
        ON CONFLICT (id) DO NOTHING
        """,
        f"""
        CREATE TABLE IF NOT EXISTS telemetry_event (
            event_id TEXT PRIMARY KEY,
            event_uuid TEXT UNIQUE,
            evt_id TEXT NOT NULL,
            session_id TEXT REFERENCES session(session_id) ON DELETE CASCADE,
            device_pseudo_id TEXT NOT NULL REFERENCES device(device_pseudo_id) ON DELETE CASCADE,
            course_id TEXT,
            block_id TEXT,
            props {json_type} NOT NULL DEFAULT '{{}}',
            ts {ts_type} NOT NULL DEFAULT {now_default},
            client_ts {ts_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_telemetry_ts ON telemetry_event(ts)",
        "CREATE INDEX IF NOT EXISTS idx_telemetry_evt_ts ON telemetry_event(evt_id, ts)",
        "CREATE INDEX IF NOT EXISTS idx_telemetry_device ON telemetry_event(device_pseudo_id)",
        f"""
        CREATE TABLE IF NOT EXISTS problem_report (
            report_id TEXT PRIMARY KEY,
            report_nonce TEXT UNIQUE,
            device_pseudo_id TEXT,
            course_id TEXT NOT NULL,
            class_level INTEGER CHECK (class_level IS NULL OR (class_level >= 6 AND class_level <= 12)),
            block_id TEXT,
            category TEXT NOT NULL CHECK (category IN ('wrong_physics', 'bad_translation', 'broken_sim', 'other')),
            text TEXT CHECK (text IS NULL OR length(text) <= 500),
            status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'fixed', 'shipped_next_run')),
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            resolved_at {ts_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_problem_report_status_created ON problem_report(status, created_at)",
        f"""
        CREATE TABLE IF NOT EXISTS content_page (
            course_id TEXT NOT NULL,
            class_level INTEGER NOT NULL CHECK (class_level >= 6 AND class_level <= 12),
            title TEXT NOT NULL,
            chapter TEXT,
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            PRIMARY KEY (course_id, class_level)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS object_catalog (
            object_id TEXT PRIMARY KEY,
            class_id TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            content_type TEXT NOT NULL,
            version_ref TEXT,
            ssd_path TEXT,
            cold_provider TEXT,
            cold_key TEXT,
            cold_verified_at {ts_type},
            evicted_at {ts_type},
            retention_until {ts_type},
            pinned BOOLEAN NOT NULL DEFAULT {bool_false},
            subject_ref TEXT,
            encryption_key_ref TEXT,
            state TEXT NOT NULL DEFAULT 'ssd_only' CHECK (
                state IN ('ssd_only', 'uploading', 'cold_verified', 'evicted', 'deleting', 'deleted', 'quarantined')
            ),
            created_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_object_catalog_class_state ON object_catalog(class_id, state)",
        "CREATE INDEX IF NOT EXISTS idx_object_catalog_subject ON object_catalog(subject_ref)",
        f"""
        CREATE TABLE IF NOT EXISTS page_version (
            page_version_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            class_level INTEGER NOT NULL,
            version TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'reviewed', 'published', 'retired')),
            sha256 TEXT NOT NULL,
            size_bytes BIGINT NOT NULL,
            manifest {json_type} NOT NULL,
            sources {json_type} NOT NULL,
            block_counts {json_type},
            translation_flags {json_type} DEFAULT '{{}}',
            run_id TEXT,
            object_id TEXT REFERENCES object_catalog(object_id),
            generated_at {ts_type} NOT NULL DEFAULT {now_default},
            published_at {ts_type},
            UNIQUE (course_id, class_level, version),
            FOREIGN KEY (course_id, class_level) REFERENCES content_page(course_id, class_level)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS live_pointer (
            course_id TEXT NOT NULL,
            class_level INTEGER NOT NULL,
            locale TEXT NOT NULL DEFAULT 'en-IN' CHECK (locale IN {LOCALE_ENUM_CHECK}),
            page_version_id TEXT NOT NULL REFERENCES page_version(page_version_id),
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            PRIMARY KEY (course_id, class_level, locale)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_live_pointer_version ON live_pointer(page_version_id)",
        f"""
        CREATE TABLE IF NOT EXISTS narration_asset (
            asset_id TEXT PRIMARY KEY,
            course_id TEXT NOT NULL,
            class_level INTEGER NOT NULL,
            block_id TEXT NOT NULL,
            locale TEXT NOT NULL CHECK (locale IN {LOCALE_ENUM_CHECK}),
            voice TEXT NOT NULL,
            speed NUMERIC NOT NULL DEFAULT 1.0 CHECK (speed IN (0.75, 1.0, 1.25)),
            page_version_id TEXT NOT NULL REFERENCES page_version(page_version_id) ON DELETE CASCADE,
            text_hash TEXT NOT NULL,
            object_id TEXT NOT NULL REFERENCES object_catalog(object_id),
            duration_ms INTEGER,
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (course_id, class_level, block_id, locale, text_hash, voice, speed)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_narration_lookup ON narration_asset(course_id, class_level, block_id, locale)",
        f"""
        CREATE TABLE IF NOT EXISTS language_bundle (
            bundle_id TEXT PRIMARY KEY,
            page_version_id TEXT NOT NULL REFERENCES page_version(page_version_id) ON DELETE CASCADE,
            locale TEXT NOT NULL CHECK (locale IN {LOCALE_ENUM_CHECK}),
            strings {json_type} NOT NULL,
            mt_flag BOOLEAN NOT NULL DEFAULT {bool_false},
            reviewed_flag BOOLEAN NOT NULL DEFAULT {bool_false},
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'reviewed', 'published', 'retired')),
            version TEXT NOT NULL,
            UNIQUE (page_version_id, locale)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS outbox (
            outbox_id {auto_pk},
            idempotency_key TEXT NOT NULL UNIQUE,
            object_id TEXT REFERENCES object_catalog(object_id) ON DELETE CASCADE,
            job_type TEXT NOT NULL CHECK (job_type IN ('upload', 'verify', 'archive', 'delete', 'snapshot')),
            payload {json_type} NOT NULL DEFAULT '{{}}',
            attempts INTEGER NOT NULL DEFAULT 0,
            next_retry_at {ts_type},
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            processed_at {ts_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_outbox_unprocessed ON outbox(processed_at, created_at)",
        f"""
        CREATE TABLE IF NOT EXISTS factory_run (
            run_id TEXT PRIMARY KEY,
            topic TEXT,
            class_level INTEGER,
            stage TEXT,
            verdict TEXT CHECK (verdict IS NULL OR verdict IN ('pass', 'repair', 'fail', 'in_progress')),
            stage_durations {json_type},
            ts {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_factory_run_ts ON factory_run(ts)",
        f"""
        CREATE TABLE IF NOT EXISTS audit_log (
            audit_id TEXT PRIMARY KEY,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            before_hash TEXT,
            after_hash TEXT,
            at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_audit_log_at ON audit_log(at DESC)",
        f"""
        CREATE TABLE IF NOT EXISTS abuse_bucket (
            bucket_id {auto_pk},
            bucket_key TEXT NOT NULL,
            endpoint_family TEXT NOT NULL CHECK (
                endpoint_family IN ('static', 'audio', 'api', 'ws', 'events', 'reports', 'delete')
            ),
            window_start {ts_type} NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            expires_at {ts_type} NOT NULL,
            UNIQUE (bucket_key, endpoint_family, window_start)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_abuse_bucket_expires ON abuse_bucket(expires_at)",
        f"""
        CREATE TABLE IF NOT EXISTS deletion_request (
            request_id TEXT PRIMARY KEY,
            device_pseudo_id TEXT NOT NULL,
            scope TEXT NOT NULL DEFAULT 'device' CHECK (scope IN ('device')),
            status TEXT NOT NULL DEFAULT 'requested' CHECK (
                status IN ('requested', 'in_progress', 'completed', 'failed')
            ),
            counts {json_type},
            requested_at {ts_type} NOT NULL DEFAULT {now_default},
            completed_at {ts_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_deletion_request_device ON deletion_request(device_pseudo_id)",
        """
        CREATE TABLE IF NOT EXISTS daily_stats (
            day TEXT PRIMARY KEY,
            sessions INTEGER NOT NULL DEFAULT 0,
            voice_sessions INTEGER NOT NULL DEFAULT 0,
            typed_sessions INTEGER NOT NULL DEFAULT 0,
            turns INTEGER NOT NULL DEFAULT 0,
            events INTEGER NOT NULL DEFAULT 0,
            stt_seconds NUMERIC NOT NULL DEFAULT 0,
            tts_chars NUMERIC NOT NULL DEFAULT 0,
            llm_tokens NUMERIC NOT NULL DEFAULT 0,
            guard_warns INTEGER NOT NULL DEFAULT 0,
            guard_exhaustions INTEGER NOT NULL DEFAULT 0,
            errors INTEGER NOT NULL DEFAULT 0,
            check_pass_rate NUMERIC
        )
        """,
    ]
    return [s.strip() for s in stmts]


def get_revision_0001_down_sql() -> list[str]:
    """Return DROP TABLE statements for revision 0001 in reverse dependency order."""
    ordered = [
        "daily_stats",
        "deletion_request",
        "abuse_bucket",
        "audit_log",
        "factory_run",
        "outbox",
        "language_bundle",
        "narration_asset",
        "live_pointer",
        "page_version",
        "object_catalog",
        "content_page",
        "problem_report",
        "telemetry_event",
        "guard_profile",
        "guard_counter",
        "credit_ledger",
        "voice_turn",
        "session",
        "consent_record",
        "device",
    ]
    return [f"DROP TABLE IF EXISTS {tbl}" for tbl in ordered]


def get_revision_0002_up_sql(dialect: str = "postgresql") -> list[str]:
    """Return DDL statements for revision 0002 (GAP-014 C3, C4 evals, and log_events)."""
    json_type = "JSONB" if dialect == "postgresql" else "TEXT"
    ts_type = "TIMESTAMPTZ" if dialect == "postgresql" else "TEXT"
    now_default = "NOW()" if dialect == "postgresql" else "CURRENT_TIMESTAMP"
    bool_false = "FALSE" if dialect == "postgresql" else "0"
    bool_true = "TRUE" if dialect == "postgresql" else "1"

    log_events_ddl = (
        """
        CREATE TABLE IF NOT EXISTS log_events (
            id BIGSERIAL,
            ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            schema_version INT NOT NULL DEFAULT 1,
            severity TEXT NOT NULL,
            event TEXT NOT NULL,
            component TEXT NOT NULL,
            env TEXT NOT NULL,
            run_id TEXT,
            session_id TEXT,
            turn_id TEXT,
            request_id TEXT,
            stage TEXT,
            latency_ms BIGINT,
            error_class TEXT,
            fields JSONB NOT NULL DEFAULT '{}'::jsonb,
            trace_id TEXT,
            span_id TEXT,
            PRIMARY KEY (id, ts)
        ) PARTITION BY RANGE (ts)
        """
        if dialect == "postgresql"
        else """
        CREATE TABLE IF NOT EXISTS log_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            schema_version INT NOT NULL DEFAULT 1,
            severity TEXT NOT NULL,
            event TEXT NOT NULL,
            component TEXT NOT NULL,
            env TEXT NOT NULL,
            run_id TEXT,
            session_id TEXT,
            turn_id TEXT,
            request_id TEXT,
            stage TEXT,
            latency_ms BIGINT,
            error_class TEXT,
            fields TEXT NOT NULL DEFAULT '{}',
            trace_id TEXT,
            span_id TEXT
        )
        """
    )

    stmts = [
        f"""
        CREATE TABLE IF NOT EXISTS locale_fallback (
            locale TEXT PRIMARY KEY,
            autonym TEXT NOT NULL,
            script_code TEXT NOT NULL,
            fallback_locale TEXT REFERENCES locale_fallback(locale),
            baseline_nudge_px NUMERIC NOT NULL DEFAULT 0.0,
            launch_tier TEXT NOT NULL,
            is_active BOOLEAN NOT NULL DEFAULT {bool_false}
        )
        """,
        f"""
        INSERT INTO locale_fallback (locale, autonym, script_code, fallback_locale, baseline_nudge_px, launch_tier, is_active)
        VALUES
            ('en', 'English', 'Latn', NULL, 0.0, 'P0', {bool_true}),
            ('hi', 'हिन्दी', 'Deva', 'en', -1.5, 'P0', {bool_true}),
            ('hi-Latn', 'Hinglish', 'Latn', 'hi', 0.0, 'P0', {bool_true}),
            ('ta', 'தமிழ்', 'Taml', 'en', -1.0, 'P1', {bool_false}),
            ('te', 'తెలుగు', 'Telu', 'en', -2.0, 'P1', {bool_false}),
            ('mr', 'मराठी', 'Deva', 'en', -1.5, 'P1', {bool_false}),
            ('bn', 'বাংলা', 'Beng', 'en', -1.0, 'P1', {bool_false}),
            ('gu', 'ગુજરાતી', 'Gujr', 'en', -1.0, 'P1', {bool_false}),
            ('kn', 'ಕನ್ನಡ', 'Knda', 'en', -2.0, 'P1', {bool_false}),
            ('ml', 'മലയാളം', 'Mlym', 'en', -2.0, 'P1', {bool_false}),
            ('pa', 'ਪੰਜਾਬੀ', 'Guru', 'en', -1.0, 'P1', {bool_false})
        ON CONFLICT (locale) DO NOTHING
        """,
        f"""
        CREATE TABLE IF NOT EXISTS glossary_term (
            id TEXT PRIMARY KEY,
            term_slug TEXT NOT NULL,
            locale TEXT NOT NULL,
            english_term TEXT NOT NULL,
            native_term TEXT NOT NULL,
            first_mention_gloss TEXT NOT NULL,
            short_label TEXT NOT NULL,
            do_not_translate BOOLEAN NOT NULL DEFAULT {bool_false},
            pronunciation_hint TEXT,
            glossary_version TEXT NOT NULL DEFAULT '1.0.0',
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (term_slug, locale, glossary_version)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_glossary_term_locale_ver ON glossary_term(locale, glossary_version)",
        f"""
        CREATE TABLE IF NOT EXISTS translation_memory_entry (
            tm_key TEXT PRIMARY KEY,
            source_content_sha256 TEXT NOT NULL,
            unit_type TEXT NOT NULL,
            locale TEXT NOT NULL,
            glossary_version TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            source_payload {json_type} NOT NULL,
            translated_payload {json_type} NOT NULL,
            translation_source TEXT NOT NULL DEFAULT 'machine' CHECK (translation_source IN ('machine', 'human')),
            model_id TEXT NOT NULL DEFAULT 'evon-v3.3',
            review_status TEXT NOT NULL DEFAULT 'machine_verified' CHECK (review_status IN ('machine_verified', 'human_approved')),
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            last_used_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (source_content_sha256, locale, glossary_version, prompt_version)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_tm_source_sha_locale ON translation_memory_entry(source_content_sha256, locale)",
        f"""
        CREATE TABLE IF NOT EXISTS block_translation (
            id TEXT PRIMARY KEY,
            lesson_version_id TEXT NOT NULL REFERENCES page_version(page_version_id) ON DELETE RESTRICT,
            content_block_id TEXT,
            block_id_str TEXT NOT NULL,
            locale TEXT NOT NULL,
            source_content_sha256 TEXT NOT NULL,
            tm_key TEXT REFERENCES translation_memory_entry(tm_key) ON DELETE SET NULL,
            translated_spec {json_type} NOT NULL,
            translation_source TEXT NOT NULL DEFAULT 'machine' CHECK (translation_source IN ('machine', 'human')),
            status TEXT NOT NULL DEFAULT 'draft' CHECK (
                status IN ('draft', 'verified', 'human_approved', 'rejected', 'fallback_en')
            ),
            reviewer_report {json_type},
            reviewed_by TEXT,
            reviewed_at {ts_type},
            created_at {ts_type} NOT NULL DEFAULT {now_default},
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            UNIQUE (lesson_version_id, block_id_str, locale)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_block_trans_version_locale ON block_translation(lesson_version_id, locale, status)",
        f"""
        CREATE TABLE IF NOT EXISTS ui_string (
            copy_key TEXT NOT NULL,
            locale TEXT NOT NULL,
            text_value TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'human',
            updated_at {ts_type} NOT NULL DEFAULT {now_default},
            PRIMARY KEY (copy_key, locale)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS eval_run (
            id TEXT PRIMARY KEY,
            suite TEXT NOT NULL CHECK (suite IN ('smoke', 'full', 'calibration')),
            pipeline_version INTEGER NOT NULL,
            factory_image_tag TEXT,
            generator_model TEXT,
            judge_model TEXT,
            git_sha TEXT,
            prompt_bundle_sha256 TEXT,
            started_at {ts_type} NOT NULL DEFAULT {now_default},
            completed_at {ts_type},
            duration_s NUMERIC,
            overall_pass BOOLEAN,
            regression_detected BOOLEAN,
            baseline_eval_run_id TEXT,
            model_calls_count INTEGER,
            total_thinking_s NUMERIC,
            report_object_id TEXT REFERENCES object_catalog(object_id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_eval_run_suite_started ON eval_run(suite, pipeline_version, started_at DESC)",
        f"""
        CREATE TABLE IF NOT EXISTS eval_card_result (
            id TEXT PRIMARY KEY,
            eval_run_id TEXT NOT NULL REFERENCES eval_run(id) ON DELETE CASCADE,
            card_id TEXT NOT NULL,
            topic_slug TEXT,
            lesson_version_id TEXT,
            verdict TEXT NOT NULL CHECK (verdict IN ('pass', 'fail', 'skip')),
            deterministic_score NUMERIC,
            judge_score NUMERIC,
            fatal_count INTEGER NOT NULL DEFAULT 0,
            major_count INTEGER NOT NULL DEFAULT 0,
            minor_count INTEGER NOT NULL DEFAULT 0,
            unverified_count INTEGER NOT NULL DEFAULT 0,
            metrics {json_type} NOT NULL DEFAULT '{{}}',
            issues {json_type} NOT NULL DEFAULT '[]',
            created_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_eval_card_topic_created ON eval_card_result(card_id, topic_slug, created_at DESC)",
        """
        CREATE TABLE IF NOT EXISTS eval_defect_sample_result (
            id TEXT PRIMARY KEY,
            eval_card_result_id TEXT NOT NULL REFERENCES eval_card_result(id) ON DELETE CASCADE,
            sample_id TEXT NOT NULL,
            expected_verdict TEXT,
            actual_verdict TEXT,
            expected_severity TEXT,
            actual_severity TEXT,
            target_block_matched BOOLEAN,
            source_quoted BOOLEAN,
            outcome_class TEXT CHECK (outcome_class IN ('TP', 'TN', 'FP', 'FN')),
            latency_s NUMERIC,
            thinking_s NUMERIC,
            completion_tokens INTEGER
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_eval_defect_sample ON eval_defect_sample_result(sample_id, outcome_class)",
        f"""
        CREATE TABLE IF NOT EXISTS eval_human_edit (
            id TEXT PRIMARY KEY,
            topic_slug TEXT NOT NULL,
            course_id TEXT NOT NULL,
            class_level INTEGER NOT NULL,
            factory_run_id TEXT,
            pipeline_version INTEGER NOT NULL,
            lesson_version_id TEXT,
            generated_git_sha TEXT,
            published_git_sha TEXT,
            total_generated_lines INTEGER NOT NULL DEFAULT 0,
            manual_added_lines INTEGER NOT NULL DEFAULT 0,
            manual_deleted_lines INTEGER NOT NULL DEFAULT 0,
            human_edit_rate NUMERIC NOT NULL DEFAULT 0,
            edit_categories {json_type} NOT NULL DEFAULT '[]',
            notes TEXT,
            recorded_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS eval_kid_session (
            id TEXT PRIMARY KEY,
            session_code TEXT NOT NULL,
            consent_record_id TEXT REFERENCES consent_record(consent_id) ON DELETE CASCADE,
            topic_slug TEXT NOT NULL,
            lesson_version_id TEXT,
            tester_class INTEGER,
            topic_class INTEGER,
            is_above_class_level BOOLEAN,
            restated_in_own_words BOOLEAN,
            followup_1_correct BOOLEAN,
            followup_2_correct BOOLEAN,
            gate_b_pass BOOLEAN,
            confusion_blocks {json_type} NOT NULL DEFAULT '[]',
            notes TEXT,
            promoted_defect_id TEXT,
            recorded_at {ts_type} NOT NULL DEFAULT {now_default}
        )
        """,
        log_events_ddl,
        "CREATE INDEX IF NOT EXISTS idx_log_events_event_ts ON log_events(event, ts DESC)",
        "CREATE INDEX IF NOT EXISTS idx_log_events_session_ts ON log_events(session_id, ts)",
        "CREATE INDEX IF NOT EXISTS idx_log_events_run_id ON log_events(run_id)",
        "CREATE INDEX IF NOT EXISTS idx_log_events_request_id ON log_events(request_id)",
    ]
    if dialect == "postgresql":
        stmts.append(
            "CREATE TABLE IF NOT EXISTS log_events_default PARTITION OF log_events DEFAULT"
        )
    return [s.strip() for s in stmts]


def get_revision_0002_down_sql() -> list[str]:
    """Return DROP TABLE statements for revision 0002 in reverse dependency order."""
    ordered = [
        "log_events",
        "eval_kid_session",
        "eval_human_edit",
        "eval_defect_sample_result",
        "eval_card_result",
        "eval_run",
        "ui_string",
        "block_translation",
        "translation_memory_entry",
        "glossary_term",
        "locale_fallback",
    ]
    return [f"DROP TABLE IF EXISTS {tbl}" for tbl in ordered]
