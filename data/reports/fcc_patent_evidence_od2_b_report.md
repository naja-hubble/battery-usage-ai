# OD2 Phase 4 - B response hazard (CIF) per mechanism

_Event = first >=50 mWh FCC step after opportunity END; matched-pseudo excludes +/-7d of any true union END; user-clustered bootstrap CI._

> Reading: `sep_168h` >> `sep_72h` for Type B would confirm the charge-side response emerges specifically after 72h, justifying the 168h primary window.

| mechanism   |   n_true |   median_resp_h |   true_CIF_72h |   pseudo_CIF_72h |   sep_72h |   true_CIF_168h |   pseudo_CIF_168h |   sep_168h |
|:------------|---------:|----------------:|---------------:|-----------------:|----------:|----------------:|------------------:|-----------:|
| A           |      408 |           47.62 |         0.4134 |           0.2896 |    0.1237 |          0.6434 |            0.3677 |     0.2756 |
| B           |    32228 |           48.18 |         0.2643 |           0.1592 |    0.1051 |          0.3685 |            0.2383 |     0.1302 |
| union       |    30511 |           48.29 |         0.2575 |           0.1536 |    0.104  |          0.3591 |            0.2341 |     0.125  |
