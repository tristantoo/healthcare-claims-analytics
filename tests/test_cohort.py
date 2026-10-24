import pandas as pd

from claims import cohort


def claims(rows):
    df = pd.DataFrame(rows, columns=["DESYNPUF_ID", "CLM_ID", "admit", "discharge", "PRVDR_NUM"])
    return df.assign(admit_dt=pd.to_datetime(df["admit"]), discharge_dt=pd.to_datetime(df["discharge"]),
                     CLM_DRG_CD="100", paid=1000.0, n_dx=3)


def bene(ids, year=2009, death=None):
    b = pd.DataFrame({"DESYNPUF_ID": ids, "BENE_BIRTH_DT": "19400101", "BENE_DEATH_DT": death,
                      "BENE_SEX_IDENT_CD": "2", "BENE_RACE_CD": "1", "BENE_ESRD_IND": "0",
                      "BENE_HI_CVRAGE_TOT_MONS": "12", "BENE_HMO_CVRAGE_TOT_MONS": "0", "MEDREIMB_IP": "0"})
    for c in cohort.CHRONIC:
        b[c] = "2"
    return b.assign(file_year=year)


def test_transfer_within_one_day_is_one_stay():
    s = cohort.build_stays(claims([("A", 1, "2010-03-01", "2010-03-05", "H1"),
                                   ("A", 2, "2010-03-06", "2010-03-09", "H2")]))
    assert len(s) == 1
    assert s.loc[0, "prvdr_num"] == "H2"  # attributed to discharging hospital
    assert s.loc[0, "los_days"] == 8


def test_two_day_gap_is_a_readmission_and_day_30_counts_day_31_does_not():
    s = cohort.build_stays(claims([("A", 1, "2010-03-01", "2010-03-05", "H1"),
                                   ("A", 2, "2010-04-04", "2010-04-06", "H1"),   # day 30 after discharge
                                   ("B", 3, "2010-03-01", "2010-03-05", "H1"),
                                   ("B", 4, "2010-04-05", "2010-04-06", "H1")]))  # day 31
    c, _ = cohort.index_stays(s, bene(["A", "B"]), "2010-01-01", "2010-03-31")
    got = dict(zip(c["DESYNPUF_ID"], c["readmit_30"]))
    assert got == {"A": 1, "B": 0}


def test_death_during_stay_excluded_and_prior_stays_counted():
    s = cohort.build_stays(claims([("A", 1, "2009-12-01", "2009-12-03", "H1"),
                                   ("A", 2, "2010-02-01", "2010-02-10", "H1"),
                                   ("B", 3, "2010-02-01", "2010-02-10", "H1")]))
    b = pd.concat([bene(["A", "B"]), bene(["A", "B"], 2010, death=[None, "20100201"])])
    c, att = cohort.index_stays(s, b, "2010-01-01", "2010-11-30")
    assert list(c["DESYNPUF_ID"]) == ["A"]
    assert c.loc[0, "prior_stays_365"] == 1
    assert att["n_index_stays"].tolist() == [2, 2, 2, 1]


def test_features_use_prior_year_file_only():
    s = cohort.build_stays(claims([("A", 1, "2010-02-01", "2010-02-03", "H1")]))
    b = pd.concat([bene(["A"], 2009), bene(["A"], 2010).assign(SP_CHF="1")])  # CHF only in discharge year
    c, _ = cohort.index_stays(s, b, "2010-01-01", "2010-11-30")
    assert c.loc[0, "sp_chf"] == 0
