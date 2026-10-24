/* 01_schema.sql: raw landing tables and mart tables for the readmissions project.
   Target: SQL Server 2019+ (tested on SQL Server 2022 LocalDB). Database name is set by the loader. */

IF SCHEMA_ID('raw') IS NULL EXEC('CREATE SCHEMA raw');
IF SCHEMA_ID('mart') IS NULL EXEC('CREATE SCHEMA mart');
GO

DROP VIEW IF EXISTS mart.v_provider_oe, mart.v_monthly_readmission;
DROP TABLE IF EXISTS mart.index_stay_score, mart.attrition, mart.index_stay, mart.ip_stay,
                     raw.inpatient_claim, raw.beneficiary_year;
GO

-- One row per inpatient claim segment (DE-SynPUF Inpatient Claims file, subset of columns).
CREATE TABLE raw.inpatient_claim (
    desynpuf_id     CHAR(16)      NOT NULL,
    clm_id          BIGINT        NOT NULL,
    segment         TINYINT       NOT NULL,
    admit_dt        DATE          NOT NULL,   -- CLM_ADMSN_DT
    discharge_dt    DATE          NOT NULL,   -- NCH_BENE_DSCHRG_DT
    prvdr_num       VARCHAR(10)   NOT NULL,
    clm_pmt_amt     DECIMAL(12,2) NULL,       -- can be negative (adjustments)
    clm_drg_cd      VARCHAR(3)    NULL,
    icd9_dgns_cd_1  VARCHAR(5) NULL, icd9_dgns_cd_2 VARCHAR(5) NULL, icd9_dgns_cd_3 VARCHAR(5) NULL,
    icd9_dgns_cd_4  VARCHAR(5) NULL, icd9_dgns_cd_5 VARCHAR(5) NULL, icd9_dgns_cd_6 VARCHAR(5) NULL,
    icd9_dgns_cd_7  VARCHAR(5) NULL, icd9_dgns_cd_8 VARCHAR(5) NULL, icd9_dgns_cd_9 VARCHAR(5) NULL,
    icd9_dgns_cd_10 VARCHAR(5) NULL,
    CONSTRAINT pk_inpatient_claim PRIMARY KEY (clm_id, segment),
    CONSTRAINT ck_claim_dates CHECK (discharge_dt >= admit_dt)
);
CREATE INDEX ix_claim_bene ON raw.inpatient_claim (desynpuf_id, admit_dt);

-- One row per beneficiary per calendar year (DE-SynPUF Beneficiary Summary files 2008 to 2010).
CREATE TABLE raw.beneficiary_year (
    desynpuf_id  CHAR(16)      NOT NULL,
    file_year    SMALLINT      NOT NULL,
    birth_dt     DATE          NOT NULL,
    death_dt     DATE          NULL,      -- month-level in SynPUF (always the 1st)
    sex_cd       CHAR(1)       NOT NULL CHECK (sex_cd IN ('1','2')),
    race_cd      CHAR(1)       NOT NULL,
    esrd_ind     CHAR(1)       NOT NULL CHECK (esrd_ind IN ('0','Y')),
    hi_cov_mos   TINYINT       NOT NULL CHECK (hi_cov_mos BETWEEN 0 AND 12),
    hmo_cov_mos  TINYINT       NOT NULL CHECK (hmo_cov_mos BETWEEN 0 AND 12),
    medreimb_ip  DECIMAL(12,2) NOT NULL,
    -- chronic condition flags: 1 = yes, 2 = no
    sp_alzhdmta TINYINT NOT NULL, sp_chf TINYINT NOT NULL, sp_chrnkidn TINYINT NOT NULL,
    sp_cncr TINYINT NOT NULL, sp_copd TINYINT NOT NULL, sp_depressn TINYINT NOT NULL,
    sp_diabetes TINYINT NOT NULL, sp_ischmcht TINYINT NOT NULL, sp_osteoprs TINYINT NOT NULL,
    sp_ra_oa TINYINT NOT NULL, sp_strketia TINYINT NOT NULL,
    CONSTRAINT pk_beneficiary_year PRIMARY KEY (desynpuf_id, file_year)
);

-- One row per hospital stay after direct transfers are merged.
CREATE TABLE mart.ip_stay (
    desynpuf_id        CHAR(16)      NOT NULL,
    stay_seq           INT           NOT NULL,
    admit_dt           DATE          NOT NULL,
    discharge_dt       DATE          NOT NULL,
    prvdr_num          VARCHAR(10)   NOT NULL,   -- discharging hospital
    drg                VARCHAR(3)    NULL,
    paid               DECIMAL(14,2) NOT NULL,
    n_dx               TINYINT       NOT NULL,
    n_claims           INT           NOT NULL,
    los_days           INT           NOT NULL,
    days_to_next_admit INT           NULL,
    prior_stays_365    INT           NOT NULL,
    CONSTRAINT pk_ip_stay PRIMARY KEY (desynpuf_id, stay_seq)
);

-- PCR-style denominator with the outcome and pre-index features.
CREATE TABLE mart.index_stay (
    desynpuf_id      CHAR(16)     NOT NULL,
    stay_seq         INT          NOT NULL,
    split            VARCHAR(5)   NOT NULL CHECK (split IN ('train','test')),
    discharge_dt     DATE         NOT NULL,
    prvdr_num        VARCHAR(10)  NOT NULL,
    readmit_30       BIT          NOT NULL,
    died_30          BIT          NOT NULL,
    age              DECIMAL(5,2) NOT NULL,
    female           BIT NOT NULL, esrd BIT NOT NULL, sp_chf BIT NOT NULL, sp_diabetes BIT NOT NULL,
    los_days         INT          NOT NULL,
    prior_stays_365  INT          NOT NULL,
    CONSTRAINT pk_index_stay PRIMARY KEY (desynpuf_id, stay_seq)
);

CREATE TABLE mart.attrition (
    split   VARCHAR(5)  NOT NULL,
    step_no TINYINT     NOT NULL,
    step    VARCHAR(60) NOT NULL,
    n       INT         NOT NULL,
    CONSTRAINT pk_attrition PRIMARY KEY (split, step_no)
);

-- Expected probabilities written back from the Python GLM (outputs/index_stays_scored.csv).
CREATE TABLE mart.index_stay_score (
    desynpuf_id CHAR(16) NOT NULL,
    stay_seq    INT      NOT NULL,
    p_glm       FLOAT    NOT NULL CHECK (p_glm BETWEEN 0 AND 1),
    p_gbm       FLOAT    NOT NULL CHECK (p_gbm BETWEEN 0 AND 1),
    CONSTRAINT pk_index_stay_score PRIMARY KEY (desynpuf_id, stay_seq)
);
GO
