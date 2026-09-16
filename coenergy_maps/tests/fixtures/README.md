# コピー元の数値参照

`source_reference.npz`は、`main`の`1b65b45a84682aca2784f77f48f75d48a3fe2dcf`にある
`code_flux/dense_jmag_rt_flux_identification.py`の`_identify_mirror()`／`_identify_single()`と
`code_flux/coenergy_forward_fit.py`の`fit_coenergy_model()`で2026-09-17に生成した。
開発時だけコピー元をimportし、配布テストはこのfixtureだけを読む。

- 入力: `examples/motor_a_vi.csv`の合成VI 221行。13単点＋104ペア＝117観測。
- 設定: `examples/motor_a.toml`。GL4を設定knotの各spanに配置し、全域でsupport／span／gauge／roughnessを積分する。
- mask: 単点はdのみ、ペアはdq。観測成分のweightは1/117。
- 保存内容: 点磁束4列と、Id=-97〜91 A、Iq=-93〜87 Aの19組でのW・磁束・Hessian全7値。
- 許容差（結果取得前にテストへ定義）: 点磁束は絶対2e-14、面評価は相対2e-11＋絶対2e-12。
- 生成環境: Python 3.13.7、NumPy 2.5.1、SciPy 1.18.0、pandas 2.3.3。

コピーした`test_coenergy_forward_fit.py`の17テストは、同revisionの同名テストから
import先だけを独立packageへ変更したもの。数値コア本体はコピー元とbyte一致を確認する。
このfixtureを新コードの出力で上書きして比較を通してはならない。

## 工程③の参照

`stage3_source_reference.npz`は2026-09-17、同じ`1b65b45`の
`coenergy_prior_correction.fit_prior_correction`、`inverse_fit.build_inverse_domain`、
`inverse_fit.fit_inverse_map`を開発時だけimportして生成した。配布テストは元repositoryを参照しない。

- 補正入力: motor_aの保存prior、`motor_a_correction_vi.csv`から同定した88観測、`build_maps_a.toml`の差分Fit／support。
- 補正参照: core・taper・outer外・負Iqを含む14点でのW・磁束・Hessian全7量。相対2e-11＋絶対2e-12で照合。
- 順LUT: 同じ25×17の軸、コピー元の最終面を8桁へ丸めた磁束2列。半丸め位置の浮動小数差を考慮して絶対1e-8以内。
- 逆入力: 公開順LUTの425節点を共通入力とする。コピー元の準備表へ変換し、追加constraintなし、
  smoothing=0、入力／出力ddof=0、同じ順序でRBFを作る。既存のCV・merge選定は照合対象外。
- 逆参照: 正Iqの非節点17点の連続RBF（相対2e-11＋絶対2e-12）、31×31の公開逆2マップ（配列完全一致）。
  q=0の公開値は両側とも0。新実装はこの境界値を明示的に固定する。
- 確認環境: Python 3.13.7、NumPy 2.5.3、SciPy 1.18.1、pandas 2.3.3。

`test_prior_correction.py`はコピー元テストのうち補正に必要な8件をimport先だけ変更して移植した。
適応選点のテスト・実装は持ち込まない。補正本体は適応選点部分とその専用importだけを除去し、
逆Fitは正規化・RBF生成・成分評価を抽出、LUT補間は`flux_map_model.py`の必要な補間器だけを抽出した。
