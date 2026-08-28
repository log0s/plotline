# STAC enrichment of synthesized scenes — dry run

Started 2026-08-28T18:03:28+00:00. Queue at start: **88** rows with `provenance = 'mosaic_url'`.

## Totals

| Outcome | Rows |
|---|---|
| already-exact (candidate id was catalogued) | 31 |
| id-corrected (found by search under another id) | 57 |
| merged into an existing scenes row | 0 |
| unmatched (left in the queue) | 0 |
| error | 0 |

Rows enriched in place: **88**. Queue after this run: **0**.

## Capture-date disagreements

None. Every matched item's `datetime` equals the date parsed from
the tile filename.

## Merges

None.

## Per row

| Candidate item id | Outcome | Detail |
|---|---|---|
| `ca_m_3712230_se_10_060_20180804_20190210` | already-exact |  |
| `ca_m_3712230_se_10_060_20200524` | already-exact |  |
| `ca_m_3712230_se_10_060_20220518` | already-exact |  |
| `ca_m_3712230_se_10_1_20120520` | id-corrected | item GET 404; found by search as ca_m_3712230_se_10_1_20120520_20120730 |
| `ca_m_3712230_se_10_1_20140608` | id-corrected | item GET 404; found by search as ca_m_3712230_se_10_1_20140608_20141007 |
| `ca_m_3712230_se_10_h_20160531` | id-corrected | item GET 404; found by search as ca_m_3712230_se_10_.6_20160531_20161004 |
| `co_m_3910516_se_13_030_20230925_20240104` | already-exact |  |
| `co_m_3910516_se_13_060_20190803` | id-corrected | item GET 404; found by search as co_m_3910516_se_13_060_20190803_20191121 |
| `co_m_3910516_se_13_060_20210728` | already-exact |  |
| `co_m_3910516_se_13_1_20110723` | id-corrected | item GET 404; found by search as co_m_3910516_se_13_1_20110723_20110901 |
| `co_m_3910516_se_13_1_20130716` | id-corrected | item GET 404; found by search as co_m_3910516_se_13_1_20130716_20130917 |
| `co_m_3910516_se_13_1_20150912` | id-corrected | item GET 404; found by search as co_m_3910516_se_13_1_20150912_20151102 |
| `co_m_3910516_se_13_1_20170902` | id-corrected | item GET 404; found by search as co_m_3910516_se_13_1_20170902_20171017 |
| `co_m_3910524_ne_13_030_20230925_20240104` | already-exact |  |
| `co_m_3910524_ne_13_060_20190803` | id-corrected | item GET 404; found by search as co_m_3910524_ne_13_060_20190803_20191121 |
| `co_m_3910524_ne_13_060_20210813` | already-exact |  |
| `co_m_3910524_ne_13_1_20110723` | id-corrected | item GET 404; found by search as co_m_3910524_ne_13_1_20110723_20110901 |
| `co_m_3910524_ne_13_1_20130716` | id-corrected | item GET 404; found by search as co_m_3910524_ne_13_1_20130716_20130917 |
| `co_m_3910524_ne_13_1_20150912` | id-corrected | item GET 404; found by search as co_m_3910524_ne_13_1_20150912_20151102 |
| `co_m_3910524_ne_13_1_20170902` | id-corrected | item GET 404; found by search as co_m_3910524_ne_13_1_20170902_20171017 |
| `co_m_4010532_sw_13_030_20230925_20240104` | already-exact |  |
| `co_m_4010532_sw_13_060_20190803` | id-corrected | item GET 404; found by search as co_m_4010532_sw_13_060_20190803_20191121 |
| `co_m_4010532_sw_13_060_20210726` | already-exact |  |
| `co_m_4010532_sw_13_1_20110718` | id-corrected | item GET 404; found by search as co_m_4010532_sw_13_1_20110718_20111101 |
| `co_m_4010532_sw_13_1_20130716` | id-corrected | item GET 404; found by search as co_m_4010532_sw_13_1_20130716_20131119 |
| `co_m_4010532_sw_13_1_20150825` | id-corrected | item GET 404; found by search as co_m_4010532_sw_13_1_20150825_20151102 |
| `co_m_4010532_sw_13_1_20170827` | id-corrected | item GET 404; found by search as co_m_4010532_sw_13_1_20170827_20180102 |
| `co_m_4010540_nw_13_030_20230925_20240104` | already-exact |  |
| `co_m_4010540_nw_13_060_20190803` | id-corrected | item GET 404; found by search as co_m_4010540_nw_13_060_20190803_20191121 |
| `co_m_4010540_nw_13_060_20210726` | already-exact |  |
| `co_m_4010540_nw_13_1_20110718` | id-corrected | item GET 404; found by search as co_m_4010540_nw_13_1_20110718_20111101 |
| `co_m_4010540_nw_13_1_20130716` | id-corrected | item GET 404; found by search as co_m_4010540_nw_13_1_20130716_20131119 |
| `co_m_4010540_nw_13_1_20150825` | id-corrected | item GET 404; found by search as co_m_4010540_nw_13_1_20150825_20151102 |
| `co_m_4010540_nw_13_1_20170827` | id-corrected | item GET 404; found by search as co_m_4010540_nw_13_1_20170827_20180102 |
| `co_m_4010564_sw_13_030_20230925_20240104` | already-exact |  |
| `co_m_4010564_sw_13_060_20190803` | id-corrected | item GET 404; found by search as co_m_4010564_sw_13_060_20190803_20191121 |
| `co_m_4010564_sw_13_060_20210813` | already-exact |  |
| `co_m_4010564_sw_13_1_20110718` | id-corrected | item GET 404; found by search as co_m_4010564_sw_13_1_20110718_20111004 |
| `co_m_4010564_sw_13_1_20130716` | id-corrected | item GET 404; found by search as co_m_4010564_sw_13_1_20130716_20131119 |
| `co_m_4010564_sw_13_1_20150825` | id-corrected | item GET 404; found by search as co_m_4010564_sw_13_1_20150825_20151102 |
| `co_m_4010564_sw_13_1_20170902` | id-corrected | item GET 404; found by search as co_m_4010564_sw_13_1_20170902_20171017 |
| `id_m_4311623_sw_11_060_20190719` | id-corrected | item GET 404; found by search as id_m_4311623_sw_11_060_20190719_20191016 |
| `id_m_4311623_sw_11_060_20210604` | already-exact |  |
| `id_m_4311623_sw_11_060_20230711_20231127` | already-exact |  |
| `id_m_4311623_sw_11_1_20110617` | id-corrected | item GET 404; found by search as id_m_4311623_sw_11_1_20110617_20110929 |
| `id_m_4311623_sw_11_1_20150719` | id-corrected | item GET 404; found by search as id_m_4311623_sw_11_1_20150719_20160104 |
| `id_m_4311623_sw_11_1_20170622` | id-corrected | item GET 404; found by search as id_m_4311623_sw_11_1_20170622_20180102 |
| `id_m_4311623_sw_11_h_20130830` | id-corrected | item GET 404; found by search as id_m_4311623_sw_11_.5_20130830_20131114 |
| `il_m_4108711_ne_16_030_20230710_20240209` | already-exact |  |
| `il_m_4108711_ne_16_060_20190802` | id-corrected | item GET 404; found by search as il_m_4108711_ne_16_060_20190802_20191221 |
| `il_m_4108711_ne_16_060_20210908` | already-exact |  |
| `il_m_4108711_ne_16_1_20110826` | id-corrected | item GET 404; found by search as il_m_4108711_ne_16_1_20110826_20111017 |
| `il_m_4108711_ne_16_1_20120619` | id-corrected | item GET 404; found by search as il_m_4108711_ne_16_1_20120619_20120820 |
| `il_m_4108711_ne_16_1_20140613` | id-corrected | item GET 404; found by search as il_m_4108711_ne_16_1_20140613_20141029 |
| `il_m_4108711_ne_16_1_20150822` | id-corrected | item GET 404; found by search as il_m_4108711_ne_16_1_20150822_20151021 |
| `il_m_4108711_ne_16_1_20170903` | id-corrected | item GET 404; found by search as il_m_4108711_ne_16_1_20170903_20170927 |
| `md_m_3807609_nw_18_030_20230901_20231018` | already-exact |  |
| `md_m_3807609_nw_18_060_20181019` | id-corrected | item GET 404; found by search as md_m_3807609_nw_18_060_20181019_20190211 |
| `md_m_3807609_nw_18_060_20210617` | already-exact |  |
| `md_m_3807609_nw_18_1_20110629` | id-corrected | item GET 404; found by search as md_m_3807609_nw_18_1_20110629_20111116 |
| `md_m_3807609_nw_18_1_20130924` | id-corrected | item GET 404; found by search as md_m_3807609_nw_18_1_20130924_20131112 |
| `md_m_3807609_nw_18_1_20150722` | id-corrected | item GET 404; found by search as md_m_3807609_nw_18_1_20150722_20150914 |
| `md_m_3807609_nw_18_1_20170716` | id-corrected | item GET 404; found by search as md_m_3807609_nw_18_1_20170716_20170907 |
| `nj_m_4007416_se_18_030_20230820_20231019` | already-exact |  |
| `nj_m_4007416_se_18_1_20100731` | already-exact |  |
| `nj_m_4007416_se_18_1_20130802` | id-corrected | item GET 404; found by search as nj_m_4007416_se_18_1_20130802_20130826 |
| `nj_m_4007416_se_18_1_20150729` | id-corrected | item GET 404; found by search as nj_m_4007416_se_18_1_20150729_20150909 |
| `nj_m_4007416_se_18_1_20170719` | id-corrected | item GET 404; found by search as nj_m_4007416_se_18_1_20170719_20171102 |
| `nj_m_4007424_ne_18_030_20230820_20231019` | already-exact |  |
| `nj_m_4007424_ne_18_1_20100731` | already-exact |  |
| `ny_m_4007416_se_18_060_20190917` | id-corrected | item GET 404; found by search as ny_m_4007416_se_18_060_20190917_20191209 |
| `ny_m_4007416_se_18_060_20211105` | already-exact |  |
| `ny_m_4007416_se_18_060_20220719` | already-exact |  |
| `ny_m_4007416_se_18_1_20110705` | id-corrected | item GET 404; found by search as ny_m_4007416_se_18_1_20110705_20111114 |
| `pa_m_3907507_nw_18_060_20191019` | id-corrected | item GET 404; found by search as pa_m_3907507_nw_18_060_20191019_20191203 |
| `pa_m_3907507_nw_18_060_20220510` | already-exact |  |
| `pa_m_3907507_nw_18_1_20100704` | already-exact |  |
| `pa_m_3907507_nw_18_1_20130605` | id-corrected | item GET 404; found by search as pa_m_3907507_nw_18_1_20130605_20130729 |
| `pa_m_3907507_nw_18_1_20150816` | id-corrected | item GET 404; found by search as pa_m_3907507_nw_18_1_20150816_20151201 |
| `pa_m_3907507_nw_18_1_20170611` | id-corrected | item GET 404; found by search as pa_m_3907507_nw_18_1_20170611_20171207 |
| `ut_m_4011126_nw_12_060_20180909` | id-corrected | item GET 404; found by search as ut_m_4011126_nw_12_060_20180909_20181209 |
| `ut_m_4011126_nw_12_060_20211113` | already-exact |  |
| `ut_m_4011126_nw_12_1_20110720` | id-corrected | item GET 404; found by search as ut_m_4011126_nw_12_1_20110720_20111011 |
| `ut_m_4011126_nw_12_1_20140701` | id-corrected | item GET 404; found by search as ut_m_4011126_nw_12_1_20140701_20141030 |
| `ut_m_4011126_nw_12_1_20160627` | id-corrected | item GET 404; found by search as ut_m_4011126_nw_12_1_20160627_20161017 |
| `va_m_3807708_se_18_060_20210910` | already-exact |  |
| `va_m_3807708_se_18_060_20231113_20240103` | already-exact |  |
| `va_m_3807708_se_18_1_20110530` | already-exact |  |
