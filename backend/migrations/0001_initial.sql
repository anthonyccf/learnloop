-- LearnLoop initial schema. New ll_* tables only.

CREATE TABLE ll_courses (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(100) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_ll_courses_owner_id ON ll_courses (owner_id);

CREATE TABLE ll_documents (
	id VARCHAR(36) NOT NULL, 
	course_id VARCHAR(36) NOT NULL, 
	filename VARCHAR(240) NOT NULL, 
	sha256 VARCHAR(64) NOT NULL, 
	content_type VARCHAR(100) NOT NULL, 
	content BYTEA NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	pages INTEGER NOT NULL, 
	graph JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (course_id, sha256), 
	FOREIGN KEY(course_id) REFERENCES ll_courses (id)
);

CREATE INDEX ix_ll_documents_course_id ON ll_documents (course_id);

CREATE TABLE ll_learner_states (
	id VARCHAR(36) NOT NULL, 
	course_id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(100) NOT NULL, 
	version INTEGER NOT NULL, 
	evidence JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (course_id, owner_id), 
	FOREIGN KEY(course_id) REFERENCES ll_courses (id)
);

CREATE TABLE ll_runs (
	id VARCHAR(36) NOT NULL, 
	course_id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(100) NOT NULL, 
	snapshot JSON NOT NULL, 
	input JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(course_id) REFERENCES ll_courses (id)
);

CREATE INDEX ix_ll_runs_course_id ON ll_runs (course_id);

CREATE TABLE ll_sessions (
	id VARCHAR(36) NOT NULL, 
	course_id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(100) NOT NULL, 
	status VARCHAR(40) NOT NULL, 
	current_activity_id VARCHAR(36), 
	PRIMARY KEY (id), 
	FOREIGN KEY(course_id) REFERENCES ll_courses (id)
);

CREATE INDEX ix_ll_sessions_course_id ON ll_sessions (course_id);

CREATE TABLE ll_activities (
	id VARCHAR(36) NOT NULL, 
	session_id VARCHAR(36) NOT NULL, 
	concept_id VARCHAR(100) NOT NULL, 
	difficulty VARCHAR(20) NOT NULL, 
	public JSON NOT NULL, 
	private JSON NOT NULL, 
	hinted BOOLEAN NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES ll_sessions (id)
);

CREATE INDEX ix_ll_activities_session_id ON ll_activities (session_id);

CREATE TABLE ll_chunks (
	id VARCHAR(36) NOT NULL, 
	document_id VARCHAR(36) NOT NULL, 
	course_id VARCHAR(36) NOT NULL, 
	ordinal INTEGER NOT NULL, 
	page INTEGER NOT NULL, 
	text TEXT NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (document_id, ordinal), 
	FOREIGN KEY(document_id) REFERENCES ll_documents (id), 
	FOREIGN KEY(course_id) REFERENCES ll_courses (id)
);

CREATE INDEX ix_ll_chunks_course_id ON ll_chunks (course_id);

CREATE INDEX ix_ll_chunks_document_id ON ll_chunks (document_id);

CREATE TABLE ll_commands (
	id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(100) NOT NULL, 
	operation_id VARCHAR(100) NOT NULL, 
	run_id VARCHAR(36) NOT NULL, 
	body JSON NOT NULL, 
	receipt JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (owner_id, operation_id), 
	FOREIGN KEY(run_id) REFERENCES ll_runs (id)
);

CREATE TABLE ll_jobs (
	id VARCHAR(36) NOT NULL, 
	run_id VARCHAR(36) NOT NULL, 
	status VARCHAR(30) NOT NULL, 
	attempts INTEGER NOT NULL, 
	lease_until TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	UNIQUE (run_id), 
	FOREIGN KEY(run_id) REFERENCES ll_runs (id)
);

CREATE INDEX ix_ll_jobs_status ON ll_jobs (status);

CREATE TABLE ll_run_events (
	id VARCHAR(36) NOT NULL, 
	run_id VARCHAR(36) NOT NULL, 
	sequence INTEGER NOT NULL, 
	data JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, sequence), 
	FOREIGN KEY(run_id) REFERENCES ll_runs (id)
);

CREATE INDEX ix_ll_run_events_run_id ON ll_run_events (run_id);

CREATE TABLE ll_submissions (
	id VARCHAR(36) NOT NULL, 
	activity_id VARCHAR(36) NOT NULL, 
	owner_id VARCHAR(100) NOT NULL, 
	operation_id VARCHAR(100) NOT NULL, 
	expected_version INTEGER NOT NULL, 
	choice_id VARCHAR(20) NOT NULL, 
	assessment JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (activity_id), 
	UNIQUE (owner_id, operation_id), 
	FOREIGN KEY(activity_id) REFERENCES ll_activities (id)
);
